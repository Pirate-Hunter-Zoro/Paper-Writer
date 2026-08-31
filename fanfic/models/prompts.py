"""Assemble a runtime prompt: committed template + this job's facts + the delivery
contract.

Every stage used to hand-roll the same three-part string — read its template,
append a "THIS JOB" block, append "write your artifact to EXACTLY this path" — with
slightly different wording each time. Slightly different wording is exactly the
kind of drift that makes one stage mysteriously less reliable than another, so the
shape lives here once and the stages supply only the facts.

The third part is now passed in rather than hardcoded, because *how* an artifact is
delivered depends on the provider: an agentic CLI writes the file, an HTTP endpoint
replies with text. `models/text.py` asks the provider for its contract and hands it
here; nothing in `stages/` has to know the difference.
"""

from .. import config


def template(name):
    """Read one committed base prompt, e.g. `template("draft")`. These are the
    load-bearing non-code artifacts of the project; they live in prompts/ at the
    repo root so they are easy to find and hand-edit."""
    return (config.PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def build(base, facts, contract, tail=""):
    """Compose the full prompt sent to a model.

    * base     — the committed template text (from `template`), or "" for an
                 ad-hoc call that has no template.
    * facts    — the THIS JOB block: a list of "Label: value" lines, or a plain
                 string to inline verbatim.
    * contract — the **delivery instruction**, supplied by the provider. An agentic
                 provider that holds tools gets "write your artifact to EXACTLY this
                 path"; an HTTP completion endpoint gets "reply with only the
                 artifact". This used to be hardcoded here as the path form, which
                 silently made every non-agentic provider impossible: told to write a
                 file it has no filesystem for, such a model reports success and the
                 stage then fails on a missing artifact. See `providers/base.py`.
    * tail     — optional closing instruction, e.g. what to say in its reply.
    """
    body = facts if isinstance(facts, str) else "\n".join(facts)
    parts = []
    if base:
        parts += [base.rstrip(), ""]
    parts += [
        "=" * 70,
        "THIS JOB",
        "=" * 70,
        body.strip(),
        "",
        contract.strip(),
    ]
    if tail:
        parts += ["", tail.strip()]
    return "\n".join(parts) + "\n"
