"""Identity Admin Service — account suspension/activation, role assignment,
service-account lifecycle, delegation lifecycle.

All operations publish immutable Domain Events via the outbox (Section 2.3),
write audit entries, and emit business metrics (Section 2.6).
"""
from __future__ import annotations

import secrets

from contexts.identity.adapters.mongo_service_and_delegation import (
    MongoDelegationRepository,
    MongoServiceAccountRepository,
)
from contexts.identity.adapters.mongo_user_repository import MongoUserRepository
from contexts.identity.domain.delegation import DelegationGrant
from contexts.identity.domain.service_account import ServiceAccount
from contexts.identity.domain.value_objects import ALL_ROLES
from kernel.audit import audit
from kernel.errors.problem import bad_request, not_found
from kernel.events import new_envelope, publish
from kernel.observability.metrics import increment
from kernel.persistence.context import current_context
from kernel.security.tokens import hash_token, new_opaque_token


class IdentityAdminService:
    def __init__(self, users: MongoUserRepository,
                 service_accounts: MongoServiceAccountRepository,
                 delegations: MongoDelegationRepository) -> None:
        self.users = users
        self.service_accounts = service_accounts
        self.delegations = delegations

    # ---- Account suspension / activation -------------------------------
    async def suspend_user(self, *, user_id: str, reason: str) -> dict:
        ctx = current_context()
        user = await self.users.get(user_id)
        if not user:
            raise not_found("user not found", code="identity.user.not_found")
        prev_version = user.version
        user.suspend(reason=reason, by_principal_id=ctx.principal_id)
        user = await self.users.update(user, expected_version=prev_version)
        await audit("identity.account.suspended", resource_type="user",
                    resource_id=user.user_id,
                    payload={"reason": reason, "suspended_by": ctx.principal_id})
        await publish(new_envelope(
            event_type="identity.account.suspended", event_version=1,
            aggregate_type="user", aggregate_id=user.user_id,
            aggregate_version=user.version, producer="identity",
            payload={"reason": reason, "suspended_by": ctx.principal_id,
                     "suspended_at": user.suspended_at},
            tenant_id=user.tenant_id, country=user.country,
            organization_id=user.organization_id, actor=ctx.principal_id,
            correlation_id=ctx.correlation_id,
        ))
        await increment("suspension", labels={"reason_short": reason[:20]})
        return user.public_view()

    async def activate_user(self, *, user_id: str) -> dict:
        ctx = current_context()
        user = await self.users.get(user_id)
        if not user:
            raise not_found("user not found", code="identity.user.not_found")
        prev_version = user.version
        user.activate()
        user = await self.users.update(user, expected_version=prev_version)
        await audit("identity.account.activated", resource_type="user",
                    resource_id=user.user_id, payload={"activated_by": ctx.principal_id})
        await publish(new_envelope(
            event_type="identity.account.activated", event_version=1,
            aggregate_type="user", aggregate_id=user.user_id,
            aggregate_version=user.version, producer="identity",
            payload={"activated_by": ctx.principal_id},
            tenant_id=user.tenant_id, country=user.country,
            organization_id=user.organization_id, actor=ctx.principal_id,
            correlation_id=ctx.correlation_id,
        ))
        return user.public_view()

    async def assign_role(self, *, user_id: str, role: str) -> dict:
        if role not in ALL_ROLES:
            raise bad_request(f"unknown role: {role}", code="identity.unknown_role")
        ctx = current_context()
        user = await self.users.get(user_id)
        if not user:
            raise not_found("user not found", code="identity.user.not_found")
        prev_role = user.role
        prev_version = user.version
        user.assign_role(role)
        user = await self.users.update(user, expected_version=prev_version)
        await audit("identity.role.assigned", resource_type="user",
                    resource_id=user.user_id,
                    payload={"previous_role": prev_role, "new_role": role,
                             "assigned_by": ctx.principal_id})
        await publish(new_envelope(
            event_type="identity.role.assigned", event_version=1,
            aggregate_type="user", aggregate_id=user.user_id,
            aggregate_version=user.version, producer="identity",
            payload={"previous_role": prev_role, "new_role": role,
                     "assigned_by": ctx.principal_id},
            tenant_id=user.tenant_id, country=user.country,
            organization_id=user.organization_id, actor=ctx.principal_id,
            correlation_id=ctx.correlation_id,
        ))
        await increment("role_change", labels={"to": role})
        return user.public_view()

    # ---- Service accounts ----------------------------------------------
    async def create_service_account(self, *, name: str, description: str,
                                     scopes: list[str], tenant_id=None,
                                     country=None, organization_id=None) -> dict:
        ctx = current_context()
        plaintext_secret, secret_hash = new_opaque_token()
        sa = ServiceAccount.new(
            name=name, description=description, scopes=scopes,
            secret_hash=secret_hash, tenant_id=tenant_id,
            country=country, organization_id=organization_id,
            created_by=ctx.principal_id,
        )
        await self.service_accounts.add(sa)
        await audit("identity.service_account.created", resource_type="service_account",
                    resource_id=sa.account_id,
                    payload={"name": sa.name, "scopes": sa.scopes,
                             "created_by": ctx.principal_id})
        await publish(new_envelope(
            event_type="identity.service_account.created", event_version=1,
            aggregate_type="service_account", aggregate_id=sa.account_id,
            aggregate_version=sa.version, producer="identity",
            payload={"name": sa.name, "scopes": list(sa.scopes),
                     "created_by": ctx.principal_id},
            tenant_id=sa.tenant_id, country=sa.country,
            organization_id=sa.organization_id, actor=ctx.principal_id,
            correlation_id=ctx.correlation_id,
        ))
        # Return the secret plaintext exactly once (caller must store it).
        view = sa.public_view()
        view["secret"] = plaintext_secret
        return view

    async def revoke_service_account(self, account_id: str) -> dict:
        ctx = current_context()
        sa = await self.service_accounts.get(account_id)
        if not sa:
            raise not_found("service account not found",
                            code="identity.service_account.not_found")
        prev_version = sa.version
        sa.revoke(ctx.principal_id)
        sa = await self.service_accounts.update(sa, expected_version=prev_version)
        await audit("identity.service_account.revoked", resource_type="service_account",
                    resource_id=sa.account_id)
        await publish(new_envelope(
            event_type="identity.service_account.revoked", event_version=1,
            aggregate_type="service_account", aggregate_id=sa.account_id,
            aggregate_version=sa.version, producer="identity",
            payload={"revoked_by": ctx.principal_id},
            tenant_id=sa.tenant_id, country=sa.country,
            organization_id=sa.organization_id, actor=ctx.principal_id,
            correlation_id=ctx.correlation_id,
        ))
        return sa.public_view()

    # ---- Delegation grants ---------------------------------------------
    async def grant_delegation(self, *, delegator_id: str, delegate_id: str,
                               scope: list[str], valid_from: str, valid_until: str,
                               reason: str) -> dict:
        ctx = current_context()
        delegator = await self.users.get(delegator_id)
        delegate = await self.users.get(delegate_id)
        if not delegator or not delegate:
            raise not_found("delegator or delegate not found",
                            code="identity.user.not_found")
        grant = DelegationGrant.new(
            delegator_id=delegator_id, delegate_id=delegate_id, scope=scope,
            valid_from=valid_from, valid_until=valid_until, reason=reason,
            granted_by=ctx.principal_id,
        )
        await self.delegations.add(grant)
        await audit("identity.delegation.granted", resource_type="delegation",
                    resource_id=grant.grant_id,
                    payload={"delegator_id": delegator_id,
                             "delegate_id": delegate_id, "scope": scope})
        await publish(new_envelope(
            event_type="identity.delegation.granted", event_version=1,
            aggregate_type="delegation", aggregate_id=grant.grant_id,
            aggregate_version=grant.version, producer="identity",
            payload={"delegator_id": delegator_id, "delegate_id": delegate_id,
                     "scope": list(scope), "valid_from": valid_from,
                     "valid_until": valid_until, "reason": reason,
                     "granted_by": ctx.principal_id},
            tenant_id=delegator.tenant_id, country=delegator.country,
            organization_id=delegator.organization_id,
            actor=ctx.principal_id, correlation_id=ctx.correlation_id,
        ))
        await increment("delegation_granted", labels={"scope_count": str(len(scope))})
        return grant.to_doc()

    async def revoke_delegation(self, grant_id: str, reason: str) -> dict:
        ctx = current_context()
        grant = await self.delegations.get(grant_id)
        if not grant:
            raise not_found("delegation not found",
                            code="identity.delegation.not_found")
        prev_version = grant.version
        grant.revoke(by_principal_id=ctx.principal_id, reason=reason)
        grant = await self.delegations.update(grant, expected_version=prev_version)
        await audit("identity.delegation.revoked", resource_type="delegation",
                    resource_id=grant.grant_id, payload={"reason": reason})
        await publish(new_envelope(
            event_type="identity.delegation.revoked", event_version=1,
            aggregate_type="delegation", aggregate_id=grant.grant_id,
            aggregate_version=grant.version, producer="identity",
            payload={"revoked_by": ctx.principal_id, "reason": reason},
            actor=ctx.principal_id, correlation_id=ctx.correlation_id,
        ))
        return grant.to_doc()
