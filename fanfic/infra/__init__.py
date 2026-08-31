"""Durable plumbing. Knows nothing about novels.

  * `log`      — timestamped stdout + per-daemon file mirror.
  * `journal`  — the append-only, last-writer-wins state record.
  * `storage`  — atomic write / place / hash, and JSON on top of it.
  * `locks`    — one flock per daemon, so launchd can never run two copies.
  * `budget`   — the spend ceiling the engine checks before starting work.

Everything here is safe to import from anywhere in the package and imports
nothing above `config`/`paths`.
"""
