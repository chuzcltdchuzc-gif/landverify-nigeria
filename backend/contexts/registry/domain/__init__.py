"""Registry domain — value objects, aggregate, events, invariants.

This package contains pure Python domain code (no DB, no FastAPI, no IO).
The aggregate raises events; the Application Service persists them through
the transactional outbox.
"""
