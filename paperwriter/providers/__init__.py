"""How the harness reaches a model, and what each kind of work is allowed to spend.

One service, and there is no longer a choice about it: text is Claude, through the
logged-in CLI. All of it — gathering, grounding, planning, the argument map,
outlining, drafting, review, ledger merges. One model, `config.MODEL`.

## Why the swappable-provider machinery is gone

This package used to be a registry: five text backends behind one contract, a
per-role `provider` override so a hybrid setup could send the cheap roles to a cheap
vendor, capability declarations so a provider without web access could refuse the
gathering stage up front, and a price table spanning eleven models so the cost
estimator could compare them. It was well built and it answered a question nobody was
asking.

Every one of those seams cost something real:

  * **Two tiers meant two answers to every quality question.** A cheap model wrote and
    an expensive one judged, so a bad section had two suspects, and the fix for
    anything was always "try moving the tier". Prose quality is the entire product
    here. There is no volume argument that beats it, and the split was quietly costing
    work — roles kept having to be dragged back up to the judge tier after the cheap
    one produced something unusable, and none of those moves was ever measured.
  * **Provider-agnosticism was theatre.** The gathering stage needs live filesystem and
    web access and only the CLI has both, so the "swappable" pipeline had one role
    that could never swap. Every prompt in `prompts/` is written against Claude's
    habits.
  * **The generic contract layer existed for providers that no longer exist.** An HTTP
    endpoint has no filesystem, so `base.py` carried two delivery contracts and every
    call site had to ask which one applied.

So: one model, one contract, one place the numbers live. What survives is the part
that was earning its keep — the role table, which says what each kind of work may
spend, in one column where the numbers can be compared.

## The role table still matters

Before it existed, eight stages each hand-tuned `max_turns` and `timeout` at their own
call site, and drafting sat at the smallest budget in the pipeline against the largest
artifact in it, because nobody was looking at the numbers side by side. That is the
whole argument for `role(name)`, and it is unaffected by there being one model now.
"""

from .. import config
from . import text_cli

# The one text provider. Named rather than registered: adding a second would mean
# re-earning the argument above, and a module attribute is a much clearer thing to
# grep for than a dict lookup.
TEXT = text_cli


class Role:
    """What one kind of work is allowed to spend, and how it is expected to work."""

    def __init__(self, name, spec):
        self.name = name
        self.model = spec.get("model") or config.MODEL
        self.max_turns = spec.get("max_turns", 30)
        self.timeout = spec.get("timeout", 1200)
        self.tools = tuple(spec.get("tools", ("Read", "Write")))
        # Whether this role's whole input is inlined in the prompt, so the model reads
        # nothing and writes once. On an agentic CLI that is roughly ten times fewer
        # input tokens for the same artifact at the same model; see
        # `base.file_contract`.
        self.oneshot = bool(spec.get("oneshot"))

    def __repr__(self):                                          # pragma: no cover
        return f"<Role {self.name} model={self.model}>"


def role(name):
    """Resolve one role from the config table. An unknown name is a programming error,
    not a runtime condition, so this raises rather than defaulting."""
    try:
        spec = config.TEXT_ROLES[name]
    except KeyError:
        raise KeyError(
            f"unknown text role {name!r}; known roles: "
            f"{', '.join(sorted(config.TEXT_ROLES))}") from None
    return Role(name, spec)


def text():
    """The text provider. Claude, through the CLI."""
    return TEXT


def describe():
    """One line for the startup log, so a broken setup is visible in the first three
    lines of a daemon log rather than inferred from a failure much later."""
    sources = ", ".join(str(p) for p in config.SOURCE_DIRS) or "(none configured)"
    return (f"text: {config.MODEL} via {config.CLI_BIN!r} (logged-in session, no API "
            f"key) | evidence sources: {sources} | output: {config.OUT_DIR}")
