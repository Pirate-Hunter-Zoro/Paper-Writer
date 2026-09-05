"""What a provider is, and the one delivery contract text calls are written against.

One service: Claude, for text. This module holds the declarations around it — what a
provider can do, what a failure means, and the contract every call is written against.
No I/O, so it can be read on its own.

## The delivery contract

The project's spine is *the model proposes to a file; deterministic code disposes*.
Every stage names an output path and reads that file afterwards, and Claude — which
holds the tools — writes it itself. The closing instruction that says so is generated
here rather than baked into each prompt template, so the one-shot discipline below is
applied uniformly instead of being remembered eleven times.

This used to be two contracts, because a completion endpoint has no filesystem and
had to be told to *reply* with the artifact instead. Those providers are gone (see
`providers/__init__.py`), and with them the class of bug where the wrong contract was
handed to a provider and every call it made failed the same way.
"""

from .. import config


class Capability:
    """What a provider can do, declared rather than discovered mid-run."""

    def __init__(self, writes_own_file=False, supports_tools=False,
                 supports_web=False):
        # Does the provider write the artifact itself (agentic, has tools)?
        self.writes_own_file = writes_own_file
        # Can it be granted file/search tools at all?
        self.supports_tools = supports_tools
        # Can it reach the live web and the filesystem? The gathering stage is
        # impossible without both.
        self.supports_web = supports_web


def is_transient(detail):
    """Whether a failure message looks like a retryable blip.

    A denylist of network reality rather than a vendor's error taxonomy. Anything that
    reads as a blip is retried; the cost of retrying a genuine failure is one call, and
    the cost of parking on a blip is a manuscript."""
    low = (detail or "").lower()
    return any(sig in low for sig in config.TRANSIENT_SIGNATURES)


def is_quota(detail):
    """Whether a failure is an allowance ceiling rather than a fault.

    Checked before `is_transient`, whose list contains "rate limit": a rate limit
    clears on its own and wants a fast retry, while a spend or session ceiling wants a
    human and a long wait. Both mean "come back later"; only one comes back by
    itself. A ceiling must never park a unit — see `errors.QuotaExceeded`."""
    low = (detail or "").lower()
    return any(sig in low for sig in config.QUOTA_SIGNATURES)


def file_contract(out_path, artifact, shape=None, oneshot=False):
    """The closing instruction telling Claude where to put its artifact.

    `oneshot` is the token-discipline half of the contract, and it is worth more than
    any model choice. An agentic CLI re-sends the entire conversation — system prompt,
    every prior tool call, every tool *result* — on every turn. A writer that opens the
    previous draft, greps the ledger, and then lays a section down in eight appends pays
    for that whole accumulating transcript eight times over: a draft measured at
    ~227,000 input tokens to produce ~7,200 output tokens, and a critique at ~363,000.

    Nothing in those transcripts was information the harness did not already have on
    disk. So the prompt carries the content inline and the model is told to read
    nothing and write once — which collapses the same work to two or three turns and
    roughly an order of magnitude fewer input tokens, at identical model and identical
    output. The propose/dispose spine is untouched: still one file at one known path,
    still validated before anything is committed.

    The instruction is emphatic about the single write because a partial first write
    followed by an append is the one failure this shape has: `Write` overwrites whole
    documents, so two writes means the artifact is whatever the last one said."""
    parts = []
    if oneshot:
        parts += [
            "IMPORTANT — how to do this work:",
            "Everything you need is already in this prompt. Do NOT read, search, or "
            "list any files: no Read, no Grep, no Glob, no Bash. The paths mentioned "
            "above are for your reference only; their contents are quoted inline.",
            "Think first, then produce the COMPLETE artifact and write it in exactly "
            "ONE Write tool call. Do not write a partial artifact and extend it — "
            "Write overwrites the whole file, so a second call throws away the first. "
            "After that one write, stop and reply with a single short sentence.",
            "",
        ]
    parts += [f"Write {artifact} to EXACTLY this path, overwriting if present:",
              str(out_path)]
    if shape:
        parts += ["", "It must have this shape:", shape.strip()]
    return "\n".join(parts)
