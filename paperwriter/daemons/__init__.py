"""The two long-running entry points.

    author   self-looper. The engine. Sufficient on its own for correctness.
    builder  one-shot on an interval. Builds and delivers finished papers.

Both are deliberately thin: take the lock, loop or run once, call into `engine/`.
Anything a daemon knows that the engine does not is a bug waiting for the day the two
disagree — which is why `builder` reuses `engine.paper.advance` rather than
reimplementing the build transitions.

There is no backup unit. `state/project/` is the only copy of a run's plan, outlines,
ledgers and accepted sections, and that is the intended arrangement: the manuscript on
disk *is* the artifact, and crash-resume is the journal's job rather than a snapshot's.

Run as modules from the repo root:  python3 -m paperwriter.daemons.author
"""

import time

from .. import providers


# After this many consecutive cycles failing with the SAME error, stop calling it a
# blip. Three, because two in a row is ordinary for a network wobble and three
# identical tracebacks is a bug.
_REPEAT_BEFORE_LOUD = 3


def loop(label, cycle_fn, log, idle_sec):
    """The self-looper shape: run a cycle, nap for however long it asks, and never die
    of a single bad cycle. A service manager restarts the process only if it genuinely
    exits, so swallowing a cycle error here is what keeps a transient blip from
    becoming a restart storm.

    But a swallowed error that repeats identically is not a blip, and it looks exactly
    like one. A config attribute that does not exist raises on every cycle and logs a
    single tidy `cycle error (continuing)` line every thirty seconds — a daemon doing
    nothing at all, in a log that reads like a daemon working. The whole project is
    built on the idea that a problem needs somewhere to be recorded that is not
    silence, and a line indistinguishable from noise is silence with extra steps.

    So identical consecutive failures are counted, said loudly once they stop being
    plausible as transient, and backed off so the log stops scrolling. The daemon still
    never exits: a restart would only land in the same bug."""
    log(f"{label} started.")
    # Which services this process will actually reach, said once at startup. Cheap, and
    # it means a misconfiguration — a `claude` that is not on PATH, an evidence source
    # that does not exist — is visible in the first two lines of the log rather than
    # inferred much later from a stage that keeps failing.
    log(providers.describe())
    last_err, repeats = None, 0
    while True:
        try:
            nap = cycle_fn()
            last_err, repeats = None, 0
        except KeyboardInterrupt:
            log("interrupted; exiting.")
            return
        except Exception as exc:                                      # noqa: BLE001
            signature = repr(exc)
            repeats = repeats + 1 if signature == last_err else 1
            last_err = signature
            if repeats < _REPEAT_BEFORE_LOUD:
                log(f"cycle error (continuing): {signature}")
                nap = idle_sec
            else:
                # Back off geometrically so this cannot scroll a log for hours, and
                # name it for what it is.
                nap = min(idle_sec * 2 ** (repeats - _REPEAT_BEFORE_LOUD + 1), 1800)
                log(f"STUCK: the same cycle error {repeats} times in a row — this is "
                    f"a bug, not a blip, and no work is getting done. Retrying in "
                    f"{nap}s. {signature}")
        time.sleep(nap)
