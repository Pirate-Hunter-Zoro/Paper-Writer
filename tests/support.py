"""Shared test scaffolding. Import this FIRST from every test module.

Importing it redirects all runtime state — the journal, the evidence, the ledgers,
staging, locks, logs — and the inbox and the output folder into throwaway temp
directories, before `paperwriter.config` is ever imported. Nothing in the suite touches
a real path, so the whole deterministic half runs anywhere, on stdlib only.

That redirect is not a convenience, it is a safety interlock, and it is asserted rather
than assumed. An earlier version of this file redirected the state directory but forgot
the inbox, so `config.INBOX_DIR` stayed pointed at the real drop folder — and a cleanup
in one test deleted a real parked job prompt. `_assert_redirected` makes that class of
mistake impossible instead of merely unlikely.

It also owns the model-seam stubs. Every test that drives the engine uses the same
`stub_model_seams()`, so a stub signature drifting from the real seam breaks loudly in
one place instead of silently in five.
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Must happen before the first `paperwriter.config` import.
os.environ.setdefault("PAPER_STATE_DIR",
                      tempfile.mkdtemp(prefix="paperwriter-test-state-"))
os.environ.setdefault("PAPER_INBOX_DIR",
                      tempfile.mkdtemp(prefix="paperwriter-test-inbox-"))
os.environ.setdefault("PAPER_OUT_DIR",
                      tempfile.mkdtemp(prefix="paperwriter-test-out-"))

# The suite must not depend on what time of day it runs.
#
# `run_engine` drives REAL cycles, and a real cycle consults the real clock: inside a
# quiet window the engine correctly refuses to start work, so every end-to-end test
# would hang until its cycle budget ran out and then fail. A suite that passes at 03:00
# and fails at 11:00 on the same commit sends you hunting through the change you just
# made rather than the clock. Quiet hours are tested directly in `test_clock.py`, with
# an injected `now`.
os.environ.setdefault("PAPER_QUIET_HOURS", "0")

from paperwriter import config, paths, states                       # noqa: E402
from paperwriter.engine import cycle                                # noqa: E402
from paperwriter.infra import journal, storage                      # noqa: E402
from paperwriter.stages import (argument, drafting, evidence,       # noqa: E402
                                grounding, ledger_update, outlining,
                                planning, review)


def _assert_redirected():
    """Refuse to run against a real path. Loud, at import, before any test does I/O."""
    temp = Path(tempfile.gettempdir()).resolve()
    for name, path in (("STATE_DIR", config.STATE_DIR),
                       ("INBOX_DIR", config.INBOX_DIR),
                       ("OUT_DIR", config.OUT_DIR)):
        resolved = Path(path).resolve()
        if temp not in resolved.parents and resolved != temp:
            raise RuntimeError(
                f"the test suite would write to a real path: {name}={resolved}. "
                f"Set PAPER_{name} to a temp directory before importing anything.")


_assert_redirected()


# --- The fixture job ---------------------------------------------------------

PROMPT = """# Does narrative text beat structured features

## Evidence

fixture analysis

## Claims

- The embedded representation discriminates better than the feature representation on
  the held-out split.
- Performance is stable across the two largest demographic subgroups.
- The label counts treatment trials and is not adequacy-verified, so it is a proxy.

## Venue

Journal of Fixtures. 4000 word limit for an Original Paper.

## Reporting checklist

TRIPOD+AI

## Scope

1 paper.

## Anything the harness cannot work out

There are exactly two representations, the FEATURE representation and the EMBEDDED
representation. "Rule-based" is not an alias for either.
"""

# Evidence the stub freezes, and the numbers every stubbed section is allowed to use.
FIXTURE_VALUES = [0.7429, 0.6810, 8516, 42579]


_REAL_SEAMS = {}


def _stub(module, name, replacement):
    _REAL_SEAMS.setdefault((module.__name__, name), getattr(module, name))
    setattr(module, name, replacement)


def real_seam(module, name):
    """The unstubbed implementation of one seam. For a test that means to call it."""
    return _REAL_SEAMS.get((module.__name__, name), getattr(module, name))


SECTIONS = [
    ("Abstract", 200), ("Introduction", 400), ("Methods", 700),
    ("Results", 600), ("Discussion", 500),
]


def _paragraph(topic, closes):
    return {"topic": topic, "supports": [], "evidence": ["e.1"], "closes": closes}


# Prose that passes every gate: numbers from the ledger, locked terms only, paragraphs
# that open on a claim and close on what it means, sentences of varying length.
CLEAN_PROSE = (
    "The embedded representation separated the two outcome groups more sharply than "
    "the feature representation did. Area under the curve reached 0.7429 on the "
    "held-out split of 8516 patients, against 0.6810 for the feature representation "
    "on exactly the same patients. The gap held. It survived a second draw of the "
    "split, which is the weakest form of evidence that it is not an artefact of one "
    "partition.\n\n"
    "Cohort size constrains what any of these numbers can settle. The source extract "
    "held 42579 patients before the eligibility filters ran, and most of the loss "
    "that followed came from the diagnosis window rather than from missing data. A "
    "smaller cohort would not have supported the subgroup comparison at all. That "
    "constraint is worth stating before the estimates are read.\n\n"
    "Neither result licenses a claim about clinical benefit. Discrimination measures "
    "how well the model ranks patients, and a ranking is not a decision rule until "
    "somebody fixes a threshold on it. Nobody has. Until that choice is made and "
    "defended, no reader can say which patients would be treated differently, and "
    "that choice sits outside what this analysis was designed to settle.\n")


def stub_model_seams():
    """Replace every model seam with a fixture writer.

    Everything else — the journal, every gate, the ledger merge, atomic staging, the
    manuscript assembly, delivery — runs for real, which is the point: this proves the
    harness wiring independent of the models."""

    def evidence_proposal(prompt_text, corpus, out_path, log_fn=None, focus=(),
                          sources=()):
        storage.save_json({
            "items": [
                {"id": "e.1", "statement": "held-out AUC for the embedded "
                                           "representation was 0.7429",
                 "values": [0.7429], "source": "results/metrics.json",
                 "category": "performance"},
                {"id": "e.2", "statement": "held-out AUC for the feature "
                                           "representation was 0.6810",
                 "values": [0.6810], "source": "results/metrics.json",
                 "category": "performance"},
                {"id": "e.3", "statement": "the held-out split held 8516 patients",
                 "values": [8516], "source": "results/cohort.json",
                 "category": "cohort"},
                {"id": "e.4", "statement": "the source extract held 42579 patients",
                 "values": [42579], "source": "results/cohort.json",
                 "category": "cohort"},
                {"id": "e.5", "statement": "performance was stable across the two "
                                           "largest demographic subgroups",
                 "values": [0.7429], "source": "results/subgroups.json",
                 "category": "performance"},
                {"id": "e.6", "statement": "the label counts antidepressant treatment "
                                           "trials and is not adequacy-verified, so it "
                                           "is a proxy for the consensus definition",
                 "values": [], "source": "Methods/outcome.md",
                 "category": "definition"},
            ],
            "also_allow": [],
        }, out_path)
        return "stub evidence"
    _stub(evidence, "propose_evidence", evidence_proposal)

    def grounding_proposal(project_rec, out_path, log_fn=None, feedback=""):
        storage.save_json({
            "estimand": "Discrimination of a twelve-month treatment-resistance label "
                        "on a held-out split, measured by area under the ROC curve.",
            "venue": "Journal of Fixtures",
            "reader": "Clinical informatics researchers.",
            "checklist": {"name": "TRIPOD+AI", "items": ["model specification"]},
            "conventions": {"person": "we", "tense": "past"},
            "out_of_scope": ["clinical benefit"],
            "terminology": [
                {"term": "embedded representation",
                 "aliases": ["embedding approach"],
                 "definition": "The narrative text encoded by a pretrained model."},
                {"term": "feature representation",
                 "aliases": ["rule-based approach", "rule-based"],
                 "definition": "The typed feature vector."},
            ],
        }, out_path)
        return "stub grounding"
    _stub(grounding, "propose_grounding", grounding_proposal)

    def plan_proposal(project_rec, out_path, log_fn=None, feedback=""):
        storage.save_json({
            "title": "Fixture Project",
            "papers": [{"number": 1, "title": "Fixture Paper",
                        "venue": "Journal of Fixtures", "word_limit": 4000,
                        "one_line": "Text beats features for this label."}],
            "claims": [
                {"id": "c.1", "paper": 1, "headline": True, "kind": "comparative",
                 "claim": "The embedded representation discriminates better than the "
                          "feature representation.",
                 "evidence": ["e.1", "e.2"]},
                {"id": "c.2", "paper": 1, "kind": "descriptive",
                 "claim": "The held-out split is large enough to estimate that gap.",
                 "evidence": ["e.3", "e.4"]},
                {"id": "c.3", "paper": 1, "kind": "limitation",
                 "claim": "Discrimination does not establish clinical benefit.",
                 "evidence": ["e.1"]},
                {"id": "c.4", "paper": 1, "kind": "implication",
                 "claim": "A threshold has to be chosen before anyone is treated "
                          "differently.",
                 "evidence": ["e.1"]},
            ],
            "references": {"1": {"title": "A prior study", "year": 2024,
                                 "authors": "Smith J", "venue": "Journal"}},
        }, out_path)
        return "stub plan"
    _stub(planning, "propose_plan", plan_proposal)

    def argument_chunk(project_rec, paper_num, plan, mapped, wanted, out_path,
                       log_fn=None, feedback=""):
        placement = {"c.1": "Results", "c.2": "Methods", "c.3": "Discussion",
                     "c.4": "Discussion"}
        storage.save_json({
            "sections": [h for h, _w in SECTIONS],
            "claims": [dict(c, section=placement[c["id"]], depends_on=[])
                       for c in wanted],
        }, out_path)
        return "stub argument"
    _stub(argument, "propose_chunk", argument_chunk)

    def outline_proposal(project_rec, paper_num, out_path, log_fn=None, feedback=""):
        storage.save_json({"sections": [
            {"number": i, "heading": heading, "words": words,
             "evidence": ["e.1", "e.2", "e.3", "e.4"],
             "exit_state": f"the reader has read {heading}",
             "paragraphs": [
                 _paragraph(f"{heading} makes its first point about the embedded "
                            f"representation.", "what that point means"),
                 _paragraph(f"{heading} makes its second point about the cohort.",
                            "what that point means"),
             ]}
            for i, (heading, words) in enumerate(SECTIONS, start=1)]}, out_path)
        return "stub outline"
    _stub(outlining, "propose_outline", outline_proposal)

    def generate(prompt, out_path, log_fn=None, role="drafting"):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(CLEAN_PROSE, encoding="utf-8")
        return "stub prose"
    _stub(drafting, "generate", generate)

    def model_review(project_rec, paper_num, section_num, prose, truth, gate_brief,
                     pass_num, log_fn=None):
        return {"issues": [], "structural": []}
    _stub(review, "model_review", model_review)

    def ledger_proposal(project_rec, paper_num, section_num, prose, ledger_block,
                        log_fn=None):
        return {"support": [], "new_facts": [], "new_claims": []}
    _stub(ledger_update, "propose_updates", ledger_proposal)


# --- Driving the engine ------------------------------------------------------

def wipe_state():
    """Reset the journal, the decisions log, the project tree, the evidence and the
    inbox, so a test class starts from nothing without touching another class's temp
    directories."""
    for path in (paths.journal_file(), paths.decisions_log(), paths.usage_log()):
        if path.exists():
            path.unlink()
    # Evidence belongs here as much as the journal does. It is keyed on the corpus
    # rather than the project, so every fixture in the suite shares one file — which
    # would be harmless if it were written once, and is a leak now that a job tops it
    # up. One test's top-up would otherwise satisfy the next test's coverage gate, and
    # the case proving the first dig happens at all would pass or fail depending on
    # what ran before it.
    for directory in (config.STATE_DIR / "project", config.STATE_DIR / "evidence",
                      config.STATE_DIR / "tmp", config.INBOX_DIR):
        if directory.exists():
            shutil.rmtree(directory)


def drop(project_id, prompt=PROMPT, settled=True):
    """Drop a job into the inbox — the only way work enters the system.

    Backdates the mtime by default, because admission deliberately ignores a file that
    has not settled for `INBOX_SETTLE_SEC`: a prompt can be observed mid-write or
    mid-sync. In production that wait just happens; in a test it would mean every drop
    needed a real sleep. Pass `settled=False` to exercise the wait itself."""
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INBOX_DIR / f"{project_id}.md"
    path.write_text(prompt, encoding="utf-8")
    if settled:
        stamp = time.time() - (config.INBOX_SETTLE_SEC + 5)
        os.utime(path, (stamp, stamp))
    return path


def run_engine(project_id, limit=80, log_fn=lambda _msg: None):
    """Drive real engine cycles until this project terminates or the bound is hit.

    Bounded so a regression that spins forever fails the test instead of hanging."""
    key = journal.project_key(project_id)
    for _ in range(limit):
        cycle.run(log_fn=log_fn)
        status = journal.load_records().get(key, {}).get("status")
        if status in (states.PROJECT_COMPLETE, states.STALLED):
            return status
    return journal.load_records().get(key, {}).get("status")
