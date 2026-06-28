"""Platform Kernel (ADR-012, immutable core).

This package is the **permanent architectural core** of AquaSavannah LandVault.
It owns Identity, Authorization, Audit, Event Infrastructure, Configuration,
the Repository Framework, Storage Abstractions, Observability and Shared
Contracts. Business domains depend on the Kernel; the Kernel depends on no
business domain. Per ADR-012 the Kernel may only evolve through rare,
governed, backwards-compatible releases reviewed by the Chief Architect.
"""
