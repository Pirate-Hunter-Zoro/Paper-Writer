"""The single seam every stage uses to get text written. One call, one contract.

    text.produce(base, facts, out_path, role="drafting", artifact="the chapter prose")

That replaces the old two-step (assemble a prompt with `prompts.build`, then call a
vendor-specific `run_to_file` with hand-tuned turns, timeout, and tool grant). Three
things moved out of the stages and into here or the role table:

  * **What it may spend** — `providers.role()`, from one config table.
  * **How the artifact is delivered** — the closing instruction in
    `providers.base.file_contract`, which tells Claude to write EXACTLY one file at
    EXACTLY one path, and (for a one-shot role) to read nothing on the way there.
    That is the kind of detail a stage should never carry.

Every call goes to the same place: Claude, at `config.MODEL`, through the logged-in
CLI. The propose/dispose spine is unchanged and non-negotiable — after `produce`
returns, the artifact is a file at `out_path` that deterministic code reads,
validates, and disposes of.
"""

import json

from .. import providers
from . import prompts


def compose(base, facts, out_path, artifact="your result", shape=None, tail="",
            role_name=None):
    """Assemble the prompt, including the delivery contract.

    Most stages want `produce`, which composes and runs in one call. This is split out
    for the one stage whose model seam is stubbed on the *composed prompt* — drafting
    appends the revision brief to the digest and hands the finished prompt to its
    seam, so the two halves have to be callable separately.

    `role_name` is optional so `compose` stays usable on its own, but it decides
    whether the one-shot discipline is applied, and that is the single largest lever
    on what a call costs."""
    the_role = providers.role(role_name) if role_name else None
    contract = providers.text().contract(
        out_path, artifact, shape=shape,
        oneshot=bool(the_role and the_role.oneshot))
    return prompts.build(base, facts, contract=contract, tail=tail)


def run(prompt, out_path, role, log_fn=None):
    """Hand an already-composed prompt to Claude."""
    return providers.text().produce(prompt, out_path, providers.role(role),
                                    log_fn=log_fn)


def produce(base, facts, out_path, role, artifact="your result", shape=None, tail="",
            log_fn=None):
    """Have Claude produce an artifact at `out_path`.

    * base     — the committed base prompt (from `prompts.template`), or "".
    * facts    — the THIS JOB block: a list of "Label: value" lines, or a string.
    * out_path — where the artifact must end up.
    * role     — which kind of work this is; see `config.TEXT_ROLES`.
    * artifact — what is being produced, e.g. "ONLY the chapter prose (Markdown)".
    * shape    — optional literal schema shown to the model.
    * tail     — optional closing instruction specific to this call.

    Returns a short diagnostic string. Raises `QuotaExceeded` on an allowance ceiling
    (the engine defers; never a failure) or `RuntimeError` on a terminal failure."""
    prompt = compose(base, facts, out_path, artifact=artifact, shape=shape, tail=tail,
                     role_name=role)
    return run(prompt, out_path, role, log_fn=log_fn)


def produce_json(base, facts, out_path, role, artifact="your result as strict JSON",
                 shape=None, tail="", log_fn=None):
    """`produce` for the common case where the artifact is JSON we parse immediately.

    Raises `RuntimeError` — not a bare `JSONDecodeError` — when the artifact lands but
    is filled with something that is not JSON, so a caller can treat "the model
    produced garbage" the same way as any other proposal failure."""
    produce(base, facts, out_path, role, artifact=artifact, shape=shape, tail=tail,
            log_fn=log_fn)
    text = out_path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"the model wrote invalid JSON to {out_path}: {exc}") from exc
