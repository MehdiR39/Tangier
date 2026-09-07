"""Order execution: safety envelope, order construction, journal.

Dry-run by default. Nothing here reads a private key unless execution is explicitly enabled and
the key is supplied through the environment at signing time; it is never stored or logged.
"""
