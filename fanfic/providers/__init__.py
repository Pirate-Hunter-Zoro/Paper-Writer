"""How the fleet reaches a model, and what each kind of work is allowed to spend.

Two services, and there is no longer a choice about either:

  * **Text** is Claude, through the logged-in CLI. All of it — research, planning,
    outlining, drafting, editing, art direction, vision critique. One model,
    `config.MODEL`.
  * **Pictures** are Gemini, through a signed-in browser session. No API key, no
    bill; see `providers/image_browser.py` for why the API path was removed rather
    than kept as an option.

## Why the swappable-provider machinery is gone

This package used to be a registry: five text backends behind one contract, a
per-role `provider` override so a hybrid setup could send the cheap roles to a cheap
vendor, capability declarations so a provider without web access could refuse
research up front, and a price table spanning eleven models so the cost estimator
could compare them. It was well built and it answered a question nobody was asking.

Every one of those seams cost something real:

  * **Two tiers meant two answers to every quality question.** Sonnet drafted and
    Opus judged, so a bad chapter had two suspects, and the fix for anything was
    always "try moving the tier". Prose quality is the entire product here. There is
    no volume argument that beats it, and the split was quietly costing chapters —
    `art_direction` had already been dragged back up to the judge tier after the
    cheap one spent a run choosing moments no image model could draw, and `research`
    had been pushed down, and neither move was ever measured against the books.
  * **Provider-agnosticism was theatre.** Research needs live web access and only the
    CLI has it, so the "swappable" pipeline had one role that could never swap. Every
    prompt in `prompts/` was written against Claude's habits. The alternate backends
    were never run on a real book.
  * **The generic contract layer existed for providers that no longer exist.** An
    HTTP endpoint has no filesystem, so `base.py` carried two delivery contracts and
    every call site had to ask which one applied.

So: one model, one contract, one place the numbers live. What survives is the part
that was earning its keep — the role table, which says what each kind of work may
spend, in one column where the numbers can be compared.

## The role table still matters

Before it existed, eight stages each hand-tuned `max_turns` and `timeout` at their own
call site, and drafting sat at `max_turns=8` — the smallest budget in the fleet against
the largest artifact in it — for weeks, because nobody was looking at the numbers side
by side. That is the whole argument for `role(name)`, and it is unaffected by there
being one model now.
"""

from .. import config
from . import image_browser, text_cli

# The one text provider and the one image provider. Named rather than registered:
# adding a second would mean re-earning the argument above, and a module attribute is
# a much clearer thing to grep for than a dict lookup.
TEXT = text_cli
IMAGE = image_browser


class Role:
    """What one kind of work is allowed to spend, and how it is expected to work."""

    def __init__(self, name, spec):
        self.name = name
        self.model = spec.get("model") or config.MODEL
        self.max_turns = spec.get("max_turns", 30)
        self.timeout = spec.get("timeout", 1200)
        self.tools = tuple(spec.get("tools", ("Read", "Write")))
        # Whether this role's whole input is inlined in the prompt, so the model reads
        # nothing and writes once. On an agentic CLI that is ~10x fewer input tokens
        # for the same artifact at the same model; see `base.file_contract`.
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


def image():
    """The image provider. Gemini, through the browser session."""
    return IMAGE


def describe():
    """One line for the startup log, so a broken setup is visible in the first three
    lines of a daemon log rather than inferred from a failure much later."""
    problem = IMAGE.missing_prerequisite()
    pictures = "ready" if not problem else f"NOT READY — {problem}"
    return (f"text: {config.MODEL} via {config.CLI_BIN!r} (logged-in session, "
            f"no API key) | pictures: Gemini via the browser profile at "
            f"{config.GEMINI_PROFILE_DIR} ({pictures})")
