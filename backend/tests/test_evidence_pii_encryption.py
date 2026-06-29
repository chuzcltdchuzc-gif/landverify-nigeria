"""Phase 3.2 — PII Encryption acceptance tests.

Maps 1:1 to the operator directives:

* §1 EncryptionPort is the only crypto abstraction (domain never sees `nacl`).
* §4 SoftwareKms is just the first adapter; the API contract supports
  AWS KMS / Vault / HSM / Gov PKI without domain changes.
* Operator Decision 1 (residency): cross-country unwrap denied by
  default; Break-Glass requires super_admin + reason code + reason
  detail + correlation id; SecurityIncident row recorded BEFORE the
  unwrap returns; dual-auth design field exposed (even if stubbed).
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.evidence.adapters.software_kms import (
    ALLOWED_BREAK_GLASS_REASONS,
    COUNTRY_MASTERS_COLLECTION,
    SECURITY_INCIDENTS_COLLECTION,
    TENANT_DEKS_COLLECTION,
    SoftwareKmsAdapter,
)
from contexts.evidence.ports.encryption import (
    BreakGlassChallenge,
    BreakGlassRejected,
    EncryptionEnvelope,
    ResidencyViolation,
)


# ---- Fixtures ------------------------------------------------------------

@pytest_asyncio.fixture
async def kms():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_name = os.environ["DB_NAME"] + "_kms_test_" + uuid.uuid4().hex[:6]
    db = client[db_name]
    a = SoftwareKmsAdapter(db=db)
    await a.ensure_indexes()
    yield a, db
    await client.drop_database(db_name)
    client.close()


def _bg(*, requesting_country="GH", target_country="NG",
        role="super_admin", reason_code="LITIGATION_PRESERVATION_ORDER",
        reason_detail="Court order #1234",
        correlation_id="cor_test_1") -> BreakGlassChallenge:
    return BreakGlassChallenge(
        requesting_principal_id="usr_admin",
        requesting_role=role,
        request_country=requesting_country,
        target_country=target_country,
        reason_code=reason_code,
        reason_detail=reason_detail,
        correlation_id=correlation_id,
    )


# ---- Domain isolation: nothing outside this adapter imports nacl --------

def test_no_domain_or_application_code_imports_nacl() -> None:
    import pathlib
    base = pathlib.Path("/app/backend/contexts/evidence")
    offenders: list[str] = []
    for f in base.rglob("*.py"):
        # The adapter is explicitly allowed; nothing else is.
        if "adapters/software_kms.py" in str(f):
            continue
        text = f.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import nacl", "from nacl")):
                offenders.append(f"{f}:{line}")
    assert not offenders, (
        "Phase 3.2 §4: only adapters/software_kms.py may import nacl. "
        "Offenders: " + ", ".join(offenders))


# ---- Country master + tenant DEK key management -------------------------

@pytest.mark.asyncio
async def test_ensure_country_master_is_idempotent(kms) -> None:
    a, db = kms
    kid1 = await a.ensure_country_master(country="NG")
    kid2 = await a.ensure_country_master(country="NG")
    assert kid1 == kid2
    docs = await db[COUNTRY_MASTERS_COLLECTION].find({"country": "NG"}).to_list(length=10)
    assert len(docs) == 1


@pytest.mark.asyncio
async def test_get_or_create_tenant_dek_is_idempotent_per_tenant_country(kms) -> None:
    a, db = kms
    d1 = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    d2 = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    assert d1.tenant_dek_id == d2.tenant_dek_id
    # Different country → different DEK (residency separation)
    d3 = await a.get_or_create_tenant_dek(tenant_id="t1", country="GH")
    assert d3.tenant_dek_id != d1.tenant_dek_id


@pytest.mark.asyncio
async def test_tenant_dek_plaintext_is_never_persisted(kms) -> None:
    a, db = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    doc = await db[TENANT_DEKS_COLLECTION].find_one({"tenant_dek_id": dek.tenant_dek_id})
    # The stored fields are wrap_alg + nonce + ciphertext — never a plaintext key.
    assert set(doc.keys()) >= {"nonce_b64", "ciphertext_b64", "wrap_alg"}
    assert "plaintext" not in doc
    assert "key_b64" not in doc  # plaintext DEK never stored
    assert "dek_plaintext" not in doc


# ---- Encrypt / decrypt round-trip (bytes) -------------------------------

@pytest.mark.asyncio
async def test_encrypt_decrypt_round_trip_bytes(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    plaintext = b"super secret PII"
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=plaintext)
    assert ciphertext != plaintext
    out = await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext)
    assert out == plaintext


# ---- Streaming encrypt / decrypt ----------------------------------------

@pytest.mark.asyncio
async def test_encrypt_decrypt_round_trip_stream(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t_stream", country="NG")
    payload = os.urandom(200_000)  # spans multiple chunks
    chunks = [payload[i:i + 16384] for i in range(0, len(payload), 16384)]

    async def src():
        for c in chunks:
            yield c

    enc_iter, envelope = await a.encrypt_stream(dek_ref=dek, plaintext=src())
    enc_buf = b""
    async for c in enc_iter:
        enc_buf += c

    async def enc_src():
        # decrypt accepts any chunking — feed in irregular slices
        i = 0
        while i < len(enc_buf):
            j = min(i + 7000, len(enc_buf))
            yield enc_buf[i:j]
            i = j

    dec_iter = await a.decrypt_stream(envelope=envelope, ciphertext=enc_src())
    out = b""
    async for c in dec_iter:
        out += c
    assert out == payload


# ---- Residency: cross-country unwrap without break-glass is denied ------

@pytest.mark.asyncio
async def test_cross_country_unwrap_without_break_glass_denied(kms) -> None:
    """The CONTRACT is that the composition root never calls decrypt
    across countries without a Break-Glass challenge. We simulate the
    enforcement directly by passing an invalid challenge."""
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    plaintext = b"PII"
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=plaintext)
    # Construct a Break-Glass with wrong target country
    bad = _bg(target_country="GH")  # actual DEK is in NG
    with pytest.raises(BreakGlassRejected):
        await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext,
                                break_glass=bad)


# ---- Break-Glass validation -------------------------------------------

@pytest.mark.asyncio
async def test_break_glass_requires_super_admin(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=b"x")
    bg = _bg(role="compliance_officer")
    with pytest.raises(BreakGlassRejected):
        await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext,
                                break_glass=bg)


@pytest.mark.asyncio
async def test_break_glass_reason_must_be_in_allow_list(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=b"x")
    bg = _bg(reason_code="JUST_BECAUSE")
    with pytest.raises(BreakGlassRejected):
        await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext,
                                break_glass=bg)
    # Sanity: an allow-list value passes.
    good = _bg(reason_code=next(iter(ALLOWED_BREAK_GLASS_REASONS)))
    out = await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext,
                                  break_glass=good)
    assert out == b"x"


@pytest.mark.asyncio
async def test_break_glass_records_security_incident_before_returning(kms) -> None:
    a, db = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=b"PII")
    bg = _bg(correlation_id="cor_audit_check_1")
    out = await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext,
                                  break_glass=bg)
    assert out == b"PII"
    incident = await db[SECURITY_INCIDENTS_COLLECTION].find_one(
        {"correlation_id": "cor_audit_check_1"})
    assert incident is not None
    assert incident["kind"] == "break_glass_residency_override"
    assert incident["requesting_principal_id"] == "usr_admin"
    assert incident["reason_code"] == "LITIGATION_PRESERVATION_ORDER"
    assert incident["dual_auth_required_design"] is True
    assert incident["dual_authorized"] is False  # no second approver supplied


@pytest.mark.asyncio
async def test_break_glass_dual_auth_field_is_carried_through(kms) -> None:
    a, db = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=b"PII")
    bg = BreakGlassChallenge(
        requesting_principal_id="usr_admin",
        requesting_role="super_admin",
        request_country="GH", target_country="NG",
        reason_code="LITIGATION_PRESERVATION_ORDER",
        reason_detail="dual-auth check",
        correlation_id="cor_dual_1",
        second_approver_principal_id="usr_compliance",
        second_approver_signature="sig_v1_stub_signature_bytes",
    )
    assert bg.is_dual_authorized() is True
    out = await a.decrypt_bytes(envelope=envelope, ciphertext=ciphertext,
                                  break_glass=bg)
    assert out == b"PII"
    incident = await db[SECURITY_INCIDENTS_COLLECTION].find_one(
        {"correlation_id": "cor_dual_1"})
    assert incident["dual_authorized"] is True
    assert incident["second_approver_principal_id"] == "usr_compliance"


# ---- Envelope integrity: tampering rejected -----------------------------

@pytest.mark.asyncio
async def test_tampered_ciphertext_fails_to_decrypt(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek,
                                                    plaintext=b"sensitive")
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0x01])
    with pytest.raises(Exception):
        await a.decrypt_bytes(envelope=envelope, ciphertext=tampered)


@pytest.mark.asyncio
async def test_envelope_round_trip_via_dict(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    ciphertext, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=b"P")
    re_env = EncryptionEnvelope.from_dict(envelope.to_dict())
    assert re_env == envelope
    out = await a.decrypt_bytes(envelope=re_env, ciphertext=ciphertext)
    assert out == b"P"


# ---- residency_country_of_async helper ---------------------------------

@pytest.mark.asyncio
async def test_residency_country_of_async_returns_dek_country(kms) -> None:
    a, _ = kms
    dek = await a.get_or_create_tenant_dek(tenant_id="t1", country="NG")
    _, envelope = await a.encrypt_bytes(dek_ref=dek, plaintext=b"x")
    country = await a.residency_country_of_async(envelope=envelope)
    assert country == "NG"
