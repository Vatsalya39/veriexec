"""INTENTLOCK core — Team B. Risk fusion, transaction fingerprint, authorization.

Ownership boundary (00_SHARED_CONTEXT.md §4): this package is Team B's. It imports
from `contracts/` and from nothing else in the repo. Dependency direction is strictly
one-way A -> B -> C, so nothing here may import from `apps/console/`,
`services/audit/`, `packages/bench/` or `packages/signal/`.
"""

__version__ = "1.0.0"
