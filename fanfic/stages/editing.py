"""Stage 5b — the editorial pass. One model call that finds defects *and* repairs them.

This module replaces the old critique-then-redraft round trip, and it is the largest
correctness change the project has made. The reason is arithmetic.

The old loop was: a judge read the chapter and wrote a prose complaint; a *writer* then
read that complaint, went looking for the offending text, and re-emitted a correction.
Two model calls per round, and the second one had to re-derive from a description
something the first one had already located exactly. What it actually did was drift:
across 21 chapters the blocking-issue count per attempt looked like

    ch 8  15 -> 4 -> 3 -> 4 -> 2 -> 3 -> 3 -> 3 -> 2 -> 10 -> 7 -> 6 -> 6 -> 8 -> 6 -> 14 -> ...
    ch 14 13 -> 10 -> 6 -> 8 -> 5 -> 6 -> 4 -> 15 -> 8 -> 7 -> 4 -> 5 -> 6 -> 3 -> 2 -> ...

Those are not convergence curves. They are random walks, and a chapter that reached 2
went back to 14 because a "revision" re-emitted five thousand words and the judge —
correctly — found the new damage. Twenty-four attempts on one chapter, roughly $18 of
allowance each, and the twenty-fourth was worse than the fifth.

The fix is to stop moving a conclusion between two heads. The editor holds the chapter
and the ground truth at once, and every issue it raises arrives with its own exact
find/replace repair, which deterministic code applies. Text nobody named is not
rewritten by anything, so it cannot drift, so the issue count falls monotonically and
two or three passes finish a chapter instead of ten.

What stays out of the model's hands, deliberately:

  * **The gates.** Readability and length are arithmetic and are computed here, before
    the call, and handed to the editor as facts rather than asked for as opinions.
  * **Application.** The editor proposes; `patching.apply_edits` disposes. An anchor
    that matches twice is refused rather than guessed at.
  * **The verdict.** This module returns a report. Whether a chapter is finished is the
    engine's decision, not the editor's.
"""

import re

from .. import config, paths
from ..gates import length, readability, segments
from ..memory import store
from ..memory.digest import build_ground_truth
from ..models import prompts, text
from . import anchoring, patching

_EDIT_SHAPE = (
    '{"issues": [{"kind": "canon"|"continuity"|"voice"|"interiority"|"presence"'
    '|"craft", '
    '"severity": "blocking"|"polish", '
    '"issue": "<one sentence: what is wrong>", '
    '"find": "<exact text copied from the chapter, appearing exactly once>", '
    '"replace": "<what it becomes; \\"\\" to delete>"}, ...],\n'
    '  "structural": [{"kind": "continuity"|"craft", '
    '"severity": "blocking"|"polish", '
    '"issue": "<what is missing or mis-shaped>", '
    '"find": "<exact passage to be replaced wholesale>", '
    '"instruction": "<what the replacement passage must do>"}, ...]}')

# `interiority` and `presence` are new, and they are the two the operator read the book
# and asked for. Both default to BLOCKING rather than polish, because both are about
# the book failing to be the thing that was asked for rather than about a line being
# improvable — and because the editor is the only mechanism in this pipeline that can
# enforce a prose rule at all. `prompts/draft.md` has said "'She felt a wave of grief'
# is worth nothing" in bold since the beginning and the interiority happened anyway. An
# instruction is not a mechanism; the editor holds the pen.
_KINDS = ("canon", "continuity", "voice", "craft", "interiority", "presence")

# Kinds whose default severity is blocking even though they are about prose rather than
# about facts. `craft` remains the only kind that defaults to polish.
_FACTUAL_KINDS = ("canon", "continuity", "voice", "interiority", "presence")
_BLOCKING_WORDS = {"blocking", "block", "major", "critical", "severe", "fatal"}
_POLISH_WORDS = {"polish", "advisory", "minor", "nit", "nitpick", "suggestion",
                 "optional", "note"}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def ground_truth(series_rec, chapter_outline):
    """The series memory this chapter must not contradict, as one inline block."""
    memory = store.load(series_rec)
    return build_ground_truth(chapter_outline, memory.bible, memory.canon,
                              anchor_block=anchoring.block(series_rec["series_id"]))


def longest_sentences(prose, count):
    """The `count` longest sentences in the prose, longest first.

    Readability is the one gate whose failure is not located anywhere: Flesch-Kincaid
    is a function of every sentence in the chapter, so "too dense" cannot be anchored
    to a span the way a contradiction can. It used to be handled by ordering a full
    rewrite, which is exactly the mechanism this module exists to delete.

    But the score is driven by only two quantities, and one of them — words per
    sentence — is a property of *specific sentences* we can compute and quote. Handing
    the editor the fifteen worst offenders verbatim turns an un-anchorable gate into
    fifteen ordinary anchored edits."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(prose) if s.strip()]
    # Only sentences that appear exactly once are usable as anchors; a repeated one
    # would be refused at apply time anyway, so do not waste a slot on it.
    unique = [s for s in sentences if prose.count(s) == 1]
    unique.sort(key=lambda s: len(s.split()), reverse=True)
    return unique[:count]


def _readability_brief(report, prose):
    """What the editor is told about a chapter outside the readability band."""
    if report.passed:
        return []
    lines = ["", "=" * 70,
             "READABILITY GATE — FAILED (this is arithmetic, not opinion)",
             "=" * 70,
             "; ".join(report.reasons),
             f"Measured: {report.words:,} words, {report.sentences:,} sentences, "
             f"{report.words / report.sentences:.1f} words per sentence, "
             f"FK grade {report.fk_grade}, reading ease {report.flesch_ease}.",
             f"The band is FK {config.READABILITY_FK_GRADE_MIN}-"
             f"{config.READABILITY_FK_GRADE_MAX} and reading ease at or above "
             f"{config.READABILITY_FLESCH_EASE_MIN}."]

    too_dense = (report.fk_grade > config.READABILITY_FK_GRADE_MAX
                 or report.flesch_ease < config.READABILITY_FLESCH_EASE_MIN)
    if too_dense:
        lines += [
            "",
            "The score depends on exactly two things: average sentence length, and "
            "syllables per word. Nothing else moves it. So fix it with edits, not by "
            "cutting scenes or detail — split the longest sentences into two or three, "
            "and swap a Latinate word for the plain one where the plain one is just as "
            "precise. A long sentence made of short words is free.",
            "",
            "The longest sentences in this chapter are listed below. Each appears "
            "exactly once, so each is usable as an edit anchor. Split the ones that "
            "are genuinely doing too much; leave any that earn their length.", ""]
        for sentence in longest_sentences(prose, config.EDIT_LONG_SENTENCES):
            lines.append(f"  ({len(sentence.split())} words) {sentence}")
    else:
        lines += [
            "",
            "The prose is too uniformly simple. Vary sentence length — let some run "
            "long — and let the precise word stand where a plainer one is doing worse "
            "work. Do not add filler to raise the number."]
    return lines


def _length_brief(report):
    """What the editor is told about a chapter's word count."""
    if report.passed:
        return []
    return ["", "=" * 70, "LENGTH GATE — FAILED", "=" * 70, report.reason,
            "This one is NOT a find/replace fix and you should not attempt it as one. "
            "The chapter is missing material, not carrying bad material. Raise it as a "
            "`structural` entry anchored on the passage that most deserves to be played "
            "out as a scene rather than reported, and say what the replacement must "
            "dramatise. Do not pad sentences, and do not ask for more interiority — "
            "the missing material is other characters doing things."]


def _segment_brief(report):
    """What the editor is told about a chapter that never marked its scene changes.

    Unlike readability and length, this one IS an ordinary anchored fix, and a cheap
    one: the repair is to append the break line to the last sentence before each shift
    of place or time. Saying so matters, because the editor's instinct for a gate
    failure is to reach for `structural`, and rewriting scenes to add a typographic
    mark would be the most expensive possible answer to the cheapest possible defect."""
    if report.passed:
        return []
    return ["", "=" * 70, "SCENE BREAK GATE — FAILED", "=" * 70, report.reason,
            "",
            "Fix this with ordinary anchored edits, one per missing break: `find` the "
            "last sentence before the chapter moves somewhere else or later, and "
            f"`replace` it with that same sentence followed by a blank line, "
            f"`{segments.MARKER}`, and a blank line. Change nothing else. Do not raise "
            "this as `structural` and do not rewrite a scene to accommodate a mark."]


def _severity(raw, default):
    word = str(raw or "").strip().lower()
    if word in _BLOCKING_WORDS:
        return "blocking"
    if word in _POLISH_WORDS:
        return "polish"
    return default


def _kind(raw):
    word = str(raw or "").strip().lower()
    return word if word in _KINDS else "continuity"


def normalise(payload):
    """Turn whatever the editor returned into (issues, structural).

    Tolerant on purpose, and asymmetric on purpose. An issue whose severity word is
    unrecognised defaults to `blocking` when it is about facts and `polish` when it is
    about craft, because the expensive mistake differs by kind: a missed canon breach
    ships a wrong book, while a missed polish note costs nothing at all.

    An issue with no usable anchor is not discarded — it is carried as an unfixable
    blocking issue, so the engine can see that the editor found something it could not
    repair rather than silently believing the chapter clean."""
    issues, structural = [], []
    for raw in (payload or {}).get("issues") or []:
        if not isinstance(raw, dict):
            continue
        kind = _kind(raw.get("kind"))
        text_ = str(raw.get("issue") or "").strip()
        find = raw.get("find") or ""
        replace = raw.get("replace")
        default = "blocking" if kind in _FACTUAL_KINDS else "polish"
        issues.append({
            "kind": kind,
            "severity": _severity(raw.get("severity"), default),
            "issue": text_,
            "find": find,
            "replace": "" if replace is None else str(replace),
            "anchored": bool(find) and replace is not None,
        })
    for raw in (payload or {}).get("structural") or []:
        if not isinstance(raw, dict):
            continue
        structural.append({
            "kind": _kind(raw.get("kind")),
            "severity": _severity(raw.get("severity"), "blocking"),
            "issue": str(raw.get("issue") or "").strip(),
            "find": raw.get("find") or "",
            "instruction": str(raw.get("instruction") or "").strip(),
        })
    return issues, structural


def model_review(series_rec, book_num, chapter_num, prose, truth, gate_brief,
                 pass_num, log_fn=None):
    """Model seam: one editorial pass over the draft.

    The draft and the whole series memory arrive **inline**. They used to arrive as
    file paths with the instruction to go and read them, which on a turn-based provider
    re-sends every tool result on every later turn — a single critique metered at
    ~363,000 input tokens against ~4,000 of verdict. Quoted into the prompt it is one
    turn and roughly a tenth of that, at the same model and the same judgement."""
    out_path = paths.edit_path(series_rec["series_id"], book_num, chapter_num,
                               pass_num)
    return text.produce_json(
        prompts.template("edit"),
        [f"You are editing book {book_num}, chapter {chapter_num}. This is editorial "
         f"pass {pass_num}.",
         "",
         truth,
         gate_brief,
         "",
         "=" * 70,
         "THE CHAPTER (this is the complete text; your `find` anchors are copied "
         "from here character-for-character):",
         "=" * 70,
         prose],
        out_path,
        role="editing",
        artifact="your edit list as strict JSON",
        shape=_EDIT_SHAPE,
        log_fn=log_fn)


def gate_failures(series_rec, book_num, prose):
    """The deterministic gates, re-run on the prose as it now stands. No model call.

    Every editorial pass applies its edits and then either finishes or runs another
    pass — so whatever the *last* pass changed is committed without anything looking at
    it again. Most of that is unverifiable without another judgement call, which is
    exactly what the budget exists to bound. But the two gates are arithmetic and cost
    nothing, and one of them is genuinely at risk: an editor splitting long sentences to
    escape "too dense" can overshoot into "too simple", and that damage is invisible to
    the pass that caused it. Free, so there is no reason not to look."""
    report = readability.score(prose)
    length_report = length.check(report.words)
    segment_report = segments.check(prose)
    failures = []
    if not report.passed:
        failures.append("READABILITY: " + "; ".join(report.reasons))
    if not length_report.passed:
        failures.append("LENGTH: " + length_report.reason)
    if not segment_report.passed:
        failures.append("SCENE BREAKS: " + segment_report.reason)
    return failures, {"fk_grade": report.fk_grade,
                      "flesch_ease": report.flesch_ease,
                      "passed": report.passed, "words": report.words}


def review(series_rec, book_num, chapter_outline, prose, pass_num=1, log_fn=None):
    """Run one editorial pass. Returns a report; applies nothing.

    Report keys:
      issues      — anchored find/replace repairs, each with kind and severity
      structural  — defects needing new prose, each with an anchor and an instruction
      readability — the deterministic report for this text
      length      — the deterministic report for this text
      blocking    — every blocking issue as a labelled string, for the log and the
                    outstanding-issues record
      gate_failures — which hard gates this text fails right now
    """
    chapter_num = chapter_outline["number"]
    read_report = readability.score(prose)
    length_report = length.check(read_report.words)
    segment_report = segments.check(prose)

    gate_brief = "\n".join(_readability_brief(read_report, prose)
                           + _length_brief(length_report)
                           + _segment_brief(segment_report))

    payload = model_review(series_rec, book_num, chapter_num, prose,
                           ground_truth(series_rec, chapter_outline), gate_brief,
                           pass_num, log_fn=log_fn)
    issues, structural = normalise(payload)

    blocking = [f"{i['kind'].upper()}: {i['issue']}"
                for i in issues + structural if i["severity"] == "blocking"]
    polish = [f"{i['kind']} (polish): {i['issue']}"
              for i in issues + structural if i["severity"] != "blocking"]

    gate_failures = []
    if not read_report.passed:
        gate_failures.append("READABILITY: " + "; ".join(read_report.reasons))
    if not length_report.passed:
        gate_failures.append("LENGTH: " + length_report.reason)
    if not segment_report.passed:
        gate_failures.append("SCENE BREAKS: " + segment_report.reason)

    return {
        "issues": issues,
        "structural": structural,
        "blocking": blocking,
        "polish": polish,
        "gate_failures": gate_failures,
        "canon_issues": [i for i in issues + structural
                         if i["kind"] == "canon" and i["severity"] == "blocking"],
        "readability": {"fk_grade": read_report.fk_grade,
                        "flesch_ease": read_report.flesch_ease,
                        "passed": read_report.passed,
                        "words": read_report.words},
        "length": {"words": length_report.words, "floor": length_report.floor,
                   "passed": length_report.passed},
        "segments": {"count": segment_report.segments,
                     "passed": segment_report.passed},
    }


def apply_report(prose, report):
    """Apply an editorial report's anchored edits. Returns (prose, applied, rejected).

    Ordered longest-anchor-first, which is the cheap fix for the one way a well-formed
    edit list can still fight itself: two edits where one anchor contains the other.
    Applying the containing edit first destroys the nested anchor and the nested edit
    is then correctly — but pointlessly — refused. Longest first means the specific
    edit lands and only the redundant broad one is dropped."""
    edits = sorted((i for i in report["issues"] if i["anchored"]),
                   key=lambda i: len(i["find"]), reverse=True)
    return patching.apply_edits(prose, edits)


def unrepaired(report, applied):
    """Blocking issues that are still in the text after this pass's edits landed.

    An issue counts as repaired only if its own edit was one of the ones applied. An
    unanchored issue, or one whose anchor did not match, is unrepaired by definition —
    which is the signal the engine escalates on."""
    landed = {id(edit) for edit in applied}
    return [i for i in report["issues"]
            if i["severity"] == "blocking" and id(i) not in landed]
