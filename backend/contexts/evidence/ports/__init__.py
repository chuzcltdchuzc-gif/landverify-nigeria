"""Provider ports for the Evidence context (Phase 3.1+).

The domain depends only on these Protocols. Concrete adapters
(LocalFs WORM, R2, software KMS, internal CT-log, OTS, …) live under
`adapters/` and are wired by the composition root.
"""
