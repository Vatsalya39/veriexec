"""Team C audit service — the tamper-evident chain, the privacy boundary and the chatbot.

Nothing in this package imports from `packages/signal/` (Team A) or `packages/core/` (Team B).
Where a rule is shared — canonical JSON, the event vocabulary, the record hash — it is *copied*
with a test that proves both implementations agree, rather than imported across an ownership
boundary that does not exist yet.
"""
