"""Identity bounded context — canonical identity authority for AquaSavannah
LandVault (Decision 4 of Phase 1 sign-off).

Identity owns: User, Identity, Role, Permission, Country, Tenant, Organisation,
Security Policies, Session Lifecycle, Audit Metadata. External authentication
providers (Local password, Emergent Google, Microsoft Entra, government IDPs,
SAML/OIDC providers) authenticate users but DO NOT own them — they are
adapters behind the Identity Provider port.
"""
