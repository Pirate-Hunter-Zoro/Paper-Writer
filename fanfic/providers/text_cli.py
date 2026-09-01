"""Text provider: an agentic CLI, driven as a subprocess. The default.

Invoked headless, told to write its artifact to a path we name, and read from that
path — this provider has `writes_own_file=True`, so it is handed the file contract and
granted tools. Its stdout is used only for a short rationale in the decisions log.

Three outcomes, and the middle one was missing until it cost a novel: the artifact,
a `QuotaExceeded` when the backend reports a spend or allowance ceiling (never a
failure — the engine defers the unit and resumes when the limit lifts), or a
`RuntimeError`.

Retry policy, mirroring Torrent-Ingest's identify: a TRANSIENT mid-stream failure —
a dropped connection, a rate limit, a cut stream that left no file — retries with
backoff up to the cap. A DETERMINISTIC failure — a bad request, a missing binary, a
timeout that already burned the full budget — raises immediately, because retrying a
confidently wrong proposal only burns budget.

Getting that classification wrong is expensive in exactly one direction, and we have
the receipt: on 2026-08-04 a research call died with "API Error: Connection closed
mid-response", which the transient list did not match, and a ten-minute blip parked
a whole novel as FAILED. Add signatures to config.TRANSIENT_SIGNATURES freely.

Which binary and which model ids this drives are config: `CLI_BIN`, and the per-role
model tiers. Nothing here is specific to one vendor beyond the flag names, which is
why this module is a *provider* rather than the only way to write text.
"""

import json
import os
import subprocess
import time

from .. import config
from ..errors import QuotaExceeded
from ..infra import budget
from .base import Capability, file_contract, is_quota, is_transient  # noqa: F401

# The default tool grant for a stage that does not ask for something narrower.
# Stages that only need to write a file should say so — a smaller grant is a
# smaller blast radius for an unattended daemon running with permissions skipped.
DEFAULT_TOOLS = ["Bash", "Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"]


NAME = "cli"

# Agentic: it holds the tools, so it writes the artifact and can reach the web.
CAPABILITY = Capability(writes_own_file=True, supports_tools=True, supports_web=True)

# The closing instruction this provider needs. See `base.file_contract`.
contract = file_contract


def _env():
    env = os.environ.copy()
    env["PATH"] = ":".join(config.EXTRA_PATH) + ":" + env.get("PATH", "")
    return env


def _rationale(stdout):
    """The final assistant text out of `--output-format json`, falling back to raw
    stdout. Diagnostics only — never a source of truth.

    When the CLI fails it exits non-zero and leaves `result` empty, putting the actual
    reason in `subtype` / `terminal_reason` / `api_error_status` instead. Reading only
    `result` therefore turned every such failure into the message `claude exited 1:`
    with nothing after the colon — which is what a hitting-max-turns draft looked like
    for a whole run on 2026-08-04, undiagnosable. If `result` is empty, say what the
    envelope actually reported."""
    stdout = (stdout or "").strip()
    if not stdout:
        return ""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout[:2000]
    if not isinstance(envelope, dict):
        return stdout[:2000]

    result = (envelope.get("result") or "").strip()
    if result:
        return result

    # No result text: reconstruct the reason from the envelope's own diagnostics.
    parts = [f"{field}={envelope[field]}"
             for field in ("subtype", "terminal_reason", "api_error_status",
                           "stop_reason", "num_turns")
             if envelope.get(field) not in (None, "")]
    return ("no result text; " + ", ".join(parts)) if parts else ""


def _cost(stdout):
    """The call's `total_cost_usd` from the result envelope, or None.

    Named for the field, not for what it means: see `_account` and
    `infra.budget.record_usage` — on a session-authenticated CLI this is a list-price
    valuation of token usage, not money charged."""
    try:
        envelope = json.loads((stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("total_cost_usd")
    return value if isinstance(value, (int, float)) else None


def _exhausted_turns(stdout):
    """Whether a non-zero exit was the CLI running out of agent turns.

    That failure mode is special: it means the model was cut off *after* its tool
    calls, not that its work was wrong. Every stage grants only `Read`, `Write`, and
    `Grep`, and `Write` overwrites whole documents — so if the artifact is on disk, the
    last write was a complete one and the overrun happened in the epilogue."""
    try:
        envelope = json.loads((stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return False
    if not isinstance(envelope, dict):
        return False
    return ("max_turns" in str(envelope.get("terminal_reason") or "")
            or "max_turns" in str(envelope.get("subtype") or ""))


def _account(stdout, model, out_path, note):
    """Meter this call's usage. Reporting only, and never allowed to raise.

    The envelope's `total_cost_usd` is a list-price valuation of the tokens, not a
    charge — this project has no API key and the CLI authenticates by session. The log
    line says "usage" rather than "cost" for exactly that reason."""
    usd = _cost(stdout)
    if usd is None:
        return
    total = budget.record_usage(usd, label=f"{model or 'default'}:{out_path.name}")
    if total is not None:
        note(f"usage ~${usd:.2f} at list price; run total ~${total:.2f} "
             f"(a meter, not a bill — no API key is in use)")


def produce(prompt, out_path, role, log_fn=None):
    """Run the CLI headless, requiring it to write its artifact to `out_path`.

    `role` carries the model tier, turn budget, timeout, and tool grant — see
    `providers.role`. Returns the short rationale text. Raises `QuotaExceeded` on an
    allowance ceiling (deferred, never a failure) and `RuntimeError` on a terminal
    failure or once transient retries are exhausted."""
    model, allowed_tools = role.model, role.tools
    max_turns, timeout = role.max_turns, role.timeout

    def note(msg):
        if log_fn:
            log_fn(msg)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.CLI_BIN, "-p",
        "--output-format", "json",
        "--dangerously-skip-permissions",         # unattended daemon: no prompts
        "--allowedTools", ",".join(allowed_tools or DEFAULT_TOOLS),
        "--max-turns", str(max_turns),
    ]
    if model:
        cmd += ["--model", model]

    attempts = max(1, config.TRANSIENT_MAX_ATTEMPTS)
    last_err = f"{NAME} call failed"
    for attempt in range(1, attempts + 1):
        if out_path.exists():
            out_path.unlink()                     # so "file present" means "this run"
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=timeout, env=_env(),
                                  cwd=str(config.PROJECT_ROOT))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{NAME} timed out after {timeout}s")
        except FileNotFoundError:
            raise RuntimeError(f"CLI binary not found: {config.CLI_BIN}")

        rationale = _rationale(proc.stdout)
        if proc.returncode != 0 and out_path.exists() and _exhausted_turns(proc.stdout):
            # THE ARTIFACT IS THE CONTRACT, NOT THE EXIT CODE. This whole module exists
            # because stdout is unreliable and a file at a known path is not; checking
            # the exit code first quietly reinstated the thing we were avoiding. A
            # critic that wrote a complete, valid verdict and then overran its turn
            # budget had its verdict deleted and the stage counted as a failure — nine
            # minutes of judgment thrown away over an epilogue. The file was unlinked
            # before this run, so its presence means this run wrote it.
            note(f"{NAME} overran its {max_turns}-turn budget but the artifact landed; "
                 f"taking the file: {out_path.name}")
            _account(proc.stdout, model, out_path, note)
            return rationale
        if proc.returncode != 0:
            detail = rationale or (proc.stderr or "")[:500]
            if is_quota(detail):
                # Not a failure and not retryable here: the engine defers the whole
                # unit and comes back. Raised on the FIRST sight of it, because
                # hammering a billing ceiling four times in nine seconds is what
                # parked chapter 6 of the first real novel.
                note(f"model spend/quota ceiling reached: {detail[:200]}")
                raise QuotaExceeded(f"{NAME} allowance ceiling: {detail[:300]}",
                                    source="model")
            last_err = f"{config.CLI_BIN} exited {proc.returncode}: {detail}"
            # An unexplained failure is retried. The classification is only expensive
            # in one direction — a retried deterministic failure costs one call, a
            # non-retried blip costs the job — and a failure that says nothing at all
            # gives no grounds for the confident reading.
            retryable = is_transient(detail) if detail.strip() else True
        elif not out_path.exists():
            last_err = f"{NAME} produced no file at {out_path}"
            retryable = True                      # a cut stream before the Write
        else:
            _account(proc.stdout, model, out_path, note)
            return rationale

        if attempt < attempts and retryable:
            backoff = config.TRANSIENT_RETRY_BACKOFF_SEC * attempt
            note(f"{NAME} transient failure (attempt {attempt}/{attempts}), "
                 f"retrying in {backoff}s: {last_err[:160]}")
            time.sleep(backoff)
            continue
        raise RuntimeError(last_err)
    raise RuntimeError(last_err)
