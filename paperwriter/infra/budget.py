"""The allowance ceiling, and the usage meter.

The engine checks the remaining allowance before starting a unit of work; exhausted,
it idles rather than failing, so a runaway can never silently drain a shared seat. The
ceiling is a JSON file: absent means unlimited, which is the right default for local
testing. The daemons never write spend back — this is a hand-managed ceiling, not an
accountant.
"""

import json

from .. import config, paths


def record_usage(usd, label=""):
    """Append one call's usage, valued at list price, to `state/usage.jsonl`.

    **This is a usage meter, not a bill.** The `claude` CLI reports `total_cost_usd` in
    its envelope whether it authenticates by API key or by logged-in session; this
    project has no API key, so the figure is what the tokens would cost at API list
    rates rather than money anyone was charged. Recorded because it is the only signal
    available for how much allowance a run consumes — a run reached "you've hit your
    org's monthly spend limit" with nobody able to say how heavy it had been, and the
    README listed that as a known gap.

    Returns the running total. Reporting only: this never gates anything, `remaining()`
    is still the hand-managed ceiling, and every error is swallowed because metering
    must never be the thing that fails a section."""
    try:
        amount = float(usd)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    path = paths.usage_log()
    total = amount
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    total += float(json.loads(line).get("list_price_usd") or 0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue                       # a torn line is not worth failing on
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"list_price_usd": round(amount, 6), "label": label,
                 "running_total_list_price_usd": round(total, 4)}) + "\n")
    except OSError:
        return None
    return total


def record_tokens(tokens, label=""):
    """Append a token count to `state/usage.jsonl` and return the running token total.

    The companion to `record_usage`, for providers that report **tokens** rather than a
    list-price valuation — which is most of them. Kept as a separate field so the two
    are never summed into a meaningless number: `list_price_usd` and `tokens` measure
    different things, and this project has already been bitten once by a metric whose
    name overstated what it held."""
    try:
        count = int(tokens)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    path = paths.usage_log()
    total = count
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    total += int(json.loads(line).get("tokens") or 0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"tokens": count, "label": label,
                 "running_total_tokens": total}) + "\n")
    except OSError:
        return None
    return total


def tokens_used():
    """Total recorded tokens, 0 if none recorded."""
    path = paths.usage_log()
    total = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                total += int(json.loads(line).get("tokens") or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    except OSError:
        return 0
    return total


def usage_valued():
    """Total recorded usage at list-price valuation in USD, 0.0 if nothing recorded.
    Again: a meter reading, not an amount owed."""
    path = paths.usage_log()
    total = 0.0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                total += float(json.loads(line).get("list_price_usd") or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    except OSError:
        return 0.0
    return round(total, 4)


def remaining():
    """Remaining budget in USD. Infinity when no budget file is configured."""
    try:
        data = json.loads(config.BUDGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return float("inf")
    val = data.get("remaining_usd")
    return float(val) if isinstance(val, (int, float)) else float("inf")


def can_start_unit():
    """Whether there is budget to start another unit of work this cycle."""
    return remaining() > 0
