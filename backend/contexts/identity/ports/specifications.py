"""Identity-context specifications — business intent for the User repository.

Business services use these instead of crafting Mongo queries. The repository
is the only translator.
"""
from __future__ import annotations

from contexts.identity.domain.value_objects import AccountStatus
from kernel.persistence.specification import Specification


class ActiveUsersSpecification(Specification):
    def __init__(self) -> None:
        super().__init__(clauses=(("eq:account_status", AccountStatus.ACTIVE.value),))


class SuspendedUsersSpecification(Specification):
    def __init__(self) -> None:
        super().__init__(clauses=(("eq:account_status", AccountStatus.SUSPENDED.value),))


class UsersByTenantSpecification(Specification):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(clauses=(("eq:tenant_id", tenant_id),))


class UsersByCountrySpecification(Specification):
    def __init__(self, country_code: str) -> None:
        super().__init__(clauses=(("eq:country", country_code.upper()),))


class UsersByRoleSpecification(Specification):
    def __init__(self, role: str) -> None:
        super().__init__(clauses=(("eq:role", role),))


class UsersByOrganizationSpecification(Specification):
    def __init__(self, organization_id: str) -> None:
        super().__init__(clauses=(("eq:organization_id", organization_id),))
