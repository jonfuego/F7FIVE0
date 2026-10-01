"""External art-source adapters for the Edit-art modal's Search tab.

Each module here exposes one or more callables that return a list of
`{source, ref, url, label}` dicts in the same shape the *arr aggregator
already uses. They are best-effort fallbacks: any network or parse error
inside a source returns `[]` instead of propagating, so a single dead
upstream never blocks the overall candidate list.
"""
