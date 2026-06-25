"""Credit-wallet concurrency / race-condition tests.

Validates that simultaneous credit deductions never produce a negative balance,
never grant more credits than the wallet held, and that the idempotency-key
guard prevents double-charging on retried requests.

These exercise the `atomic_transaction()` wrapper in `services/payments.py`
end-to-end through the parcel creation endpoint.
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _fresh_citizen(starting_balance: int = 25):
    """Create an isolated citizen + reset wallet to a precise starting balance."""
    email = f"concur_{uuid.uuid4().hex[:8]}@landvault.test"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/test-bootstrap-citizen", json={"email": email}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['session_token']}"})
    # Cap balance via the test-only endpoint
    r = s.post(f"{API}/auth/test-set-balance", json={"balance": starting_balance}, timeout=15)
    assert r.status_code == 200, r.text
    return s, data


def _make_parcel(s: requests.Session, suffix: str) -> requests.Response:
    return s.post(f"{API}/parcels", json={
        "community": f"CONC_{suffix}", "ward": "w", "lga": "l", "state": "Lagos",
    }, timeout=30)


def _balance(s: requests.Session) -> int:
    return s.get(f"{API}/credits/balance", timeout=10).json()["wallet"]["balance"]


@pytest.mark.tx_test
def test_concurrent_deductions_never_overdraw():
    """Wallet has 25 credits — enough for 5 parcel uploads. Fire 10 in parallel.

    Exactly 5 must succeed (200) and the rest must fail with 402. Wallet must
    never go negative. With multi-doc TX active on a replica set, the
    transaction wrapper guarantees no torn writes.
    """
    s, _ = _fresh_citizen(starting_balance=25)
    assert _balance(s) == 25

    n = 10
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_make_parcel, s, f"{i}_{uuid.uuid4().hex[:4]}") for i in range(n)]
        results = [f.result() for f in cf.as_completed(futures)]

    statuses = [r.status_code for r in results]
    successes = sum(1 for c in statuses if c == 200)
    failures_402 = sum(1 for c in statuses if c == 402)
    other = [c for c in statuses if c not in (200, 402)]

    assert other == [], f"unexpected statuses: {statuses}"
    assert successes == 5, f"expected exactly 5 successes (25/5), got {successes}: {statuses}"
    assert failures_402 == n - 5, f"expected {n-5} 402s, got {failures_402}: {statuses}"

    # Wallet must end up at exactly 0, never negative.
    final = _balance(s)
    assert final == 0, f"wallet drifted: expected 0, got {final}"


@pytest.mark.tx_test
def test_idempotency_prevents_double_deduction():
    s, _ = _fresh_citizen(starting_balance=20)
    assert _balance(s) == 20

    idem_key = f"idem_{uuid.uuid4().hex}"
    body = {"community": f"IDEM_{uuid.uuid4().hex[:5]}", "ward": "w", "lga": "l", "state": "Lagos"}

    r1 = s.post(f"{API}/parcels", json=body, timeout=15,
                headers={"Idempotency-Key": idem_key})
    assert r1.status_code == 200, r1.text
    assert _balance(s) == 15

    # Replay with same idempotency key — must not deduct again.
    body2 = {**body, "community": f"IDEM_REPLAY_{uuid.uuid4().hex[:5]}"}
    r2 = s.post(f"{API}/parcels", json=body2, timeout=15,
                headers={"Idempotency-Key": idem_key})
    # The parcel itself is a new doc but the credit deduction is skipped via
    # the idempotency-key guard: balance must remain at 15.
    assert r2.status_code == 200, r2.text
    assert _balance(s) == 15, f"replay double-charged: {_balance(s)}"
