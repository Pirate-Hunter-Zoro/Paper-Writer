"""The editorial pass. One model call that finds defects *and* repairs them.

This is the feedback mechanic, and it is the largest correctness idea in the project.
The reason is arithmetic.

The obvious design is critique-then-redraft: a judge reads the section and writes a
prose complaint; a *writer* then reads that complaint, goes looking for the offending
text, and re-emits a correction. Two model calls per round, and the second one has to
re-derive from a description something the first one had already located exactly. What
it actually does is drift. Measured across a real run, blocking-issue counts per
attempt looked like

    8   15 -> 4 -> 3 -> 4 -> 2 -> 3 -> 3 -> 3 -> 2 -> 10 -> 7 -> 6 -> 6 -> 8 -> 6 -> 14
    14  13 -> 10 -> 6 -> 8 -> 5 -> 6 -> 4 -> 15 -> 8 -> 7 -> 4 -> 5 -> 6 -> 3 -> 2

Those are not convergence curves. They are random walks, and a unit that reached 2
went back to 14 because a "revision" re-emitted everything and the judge — correctly —
found the new damage.

The fix is to stop moving a conclusion between two heads. The editor holds the section
and the ground truth at once, and every issue it raises arrives with its own exact
find/replace repair, which deterministic code applies. Text nobody named is not
rewritten by anything, so it cannot drift, so the issue count falls monotonically and
two or three passes finish a section instead of ten.

What stays out of the model's hands, deliberately:

  * **The gates.** Numbers, terminology, sentences, paragraphs, citations, length and
    readability are all arithmetic. They are computed here, before the call, and
    handed to the editor as facts rather than asked for as opinions. A model asked
    "is this prose dense?" will say no about its own prose. A model handed "23% of
    your sentences run past 35 words, and here are the fifteen worst" fixes them.
  * **Application.** The editor proposes; `patching.apply_edits` disposes. An anchor
    that matches twice is refused rather than guessed at.
  * **The verdict.** This module returns a report. Whether a section is finished is
    the engine's decision, not the editor's.
"""

from .. import paths
from ..gates import (citations, length, numbers, paragraphs, readability,
                     sentences, terminology)
from ..memory import store
from ..memory.digest import build_ground_truth
from ..models import prompts, text
from . import grounding, patching

_EDIT_SHAPE = (
    '{"issues": [{"kind": "number"|"citation"|"terminology"|"claim"|"sentence"'
    '|"paragraph"|"style", '
    '"severity": "blocking"|"polish", '
    '"issue": "<one sentence: what is wrong>", '
    '"find": "<exact text copied from the section, appearing exactly once>", '
    '"replace": "<what it becomes; \\"\\" to delete>"}, ...],\n'
    '  "structural": [{"kind": "claim"|"paragraph", '
    '"severity": "blocking"|"polish", '
    '"issue": "<what is missing or mis-shaped>", '
    '"find": "<exact passage to be replaced wholesale>", '
    '"instruction": "<what the replacement passage must do>"}, ...]}')

# The defect kinds, and which of them block by default.
#
# Everything about facts blocks: a wrong number, a broken citation, a second name for
# a locked term, a claim the evidence does not support. Those are not improvable
# lines, they are the paper being wrong.
#
# `sentence` and `paragraph` block too, and that is the deliberate choice. Both are
# about the prose failing to be readable on one pass, which is what this project is
# for — and the editor is the only mechanism here that can enforce a prose rule at
# all. The draft template has said "one idea per sentence" since the beginning and
# the 60-word sentences happened anyway. An instruction is not a mechanism; the editor
# holds the pen.
#
# `style` is the only kind that defaults to polish: a better word, a smoother join.
_KINDS = ("number", "citation", "terminology", "claim", "sentence", "paragraph",
          "style")
_BLOCKING_KINDS = ("number", "citation", "terminology", "claim", "sentence",
                   "paragraph")
_BLOCKING_WORDS = {"blocking", "block", "major", "critical", "severe", "fatal"}
_POLISH_WORDS = {"polish", "advisory", "minor", "nit", "nitpick", "suggestion",
                 "optional", "note"}


def ground_truth(project_rec, paper_num, section):
    """The committed state this section must not contradict, as one inline block."""
    memory = store.load(project_rec, paper_num)
    return build_ground_truth(
        section, memory.ledger, memory.evidence_document(),
        grounding_block=grounding.block(project_rec["project_id"]))


# --- Turning arithmetic into anchored work -----------------------------------
#
# Every gate below produces the same shape of brief: what failed, why it matters, and
# — this is the part that makes it repairable — the exact sentences to anchor on. A
# statistic about a whole section cannot be find/replaced. Fifteen quoted sentences
# can.

def _sentence_brief(report, prose):
    if report.passed:
        return []
    lines = ["", "=" * 70,
             "SENTENCE GATE — FAILED (this is arithmetic, not opinion)",
             "=" * 70,
             report.brief(), ""]
    lines += [f"  - {reason}" for reason in report.reasons]
    lines += [
        "",
        "Fix this with ordinary anchored edits. Split the sentences that are carrying",
        "two claims, delete the openers that only announce another sentence, and cut",
        "the second hedge wherever there are two. Do NOT rewrite the section, do not",
        "cut a claim to lower the average, and do not chop every sentence to the same",
        "short length — uniform length fails a different check in this same gate.",
        "",
        "The worst offenders are below. Each appears exactly once, so each is usable",
        "as an edit anchor:", ""]
    for sentence in sentences.worst_offenders(report):
        lines.append(f"  ({len(sentence.split())} words) {sentence}")
    return lines


def _paragraph_brief(report):
    if report.passed:
        return []
    lines = ["", "=" * 70, "PARAGRAPH GATE — FAILED", "=" * 70, report.brief(), ""]
    lines += [f"  - {reason}" for reason in report.reasons]
    lines += ["", "Every defect below names the paragraph and quotes the sentence to "
              "anchor on:", ""]
    for defect in report.defects:
        lines.append(f"  [{defect.kind}] {defect.detail}")
        if defect.anchor:
            lines.append(f"      anchor: {defect.anchor}")
    lines += [
        "",
        "A missing topic sentence is repaired by WRITING one, not by moving a sentence",
        "up. Raise it as a `structural` entry anchored on the paragraph's first",
        "sentence and say what the new opening claim has to be. A hinge opener and a",
        "buried claim are ordinary anchored edits: rewrite the one sentence."]
    return lines


def _number_brief(report):
    if report.passed:
        return []
    lines = ["", "=" * 70,
             "NUMBER GATE — FAILED. This is the one that gets a paper retracted.",
             "=" * 70, report.brief(), ""]
    for use in report.unsupported:
        lines.append(f"  {use.raw} — not in the evidence ledger")
        if use.sentence:
            lines.append(f"      anchor: {use.sentence}")
    lines += [
        "",
        "Every one of these is `blocking`, without exception. The ground truth above",
        "lists every number this section may write. For each defect: either replace",
        "the figure with the ledger's value character-for-character, or delete the",
        "sentence that carries it. Do NOT round, do NOT approximate, and do NOT keep",
        "a number because it looks about right — a plausible wrong number is exactly",
        "the failure this gate exists for."]
    return lines


def _terminology_brief(report):
    if report.passed:
        return []
    lines = ["", "=" * 70, "TERMINOLOGY GATE — FAILED", "=" * 70, report.brief(), ""]
    for defect in report.defects:
        lines.append(f"  [{defect.kind}] {defect.detail}")
        if defect.sentence:
            lines.append(f"      anchor: {defect.sentence}")
    lines += [
        "",
        "Each of these is a one-word find/replace and each is `blocking`. A second",
        "name for one thing reads as a second thing, and a reviewer who thinks the",
        "paper has three methods will ask which one the results are about."]
    return lines


def _citation_brief(report):
    if report.passed:
        return []
    lines = ["", "=" * 70, "CITATION GATE — FAILED", "=" * 70, report.brief(), ""]
    lines += [f"  - {reason}" for reason in report.reasons]
    for defect in report.missing:
        lines.append(f"  {defect.detail}")
        if defect.anchor:
            lines.append(f"      anchor: {defect.anchor}")
    lines += [
        "",
        "An unresolved marker is repaired by pointing it at a reference that exists or",
        "by cutting it. A borrowed claim with no source is repaired by citing the",
        "source, or — if there is none in the reference list — by rewriting the",
        "sentence as something this paper's own evidence supports. Do not invent a",
        "citation."]
    return lines


def _readability_brief(report):
    if report.passed:
        return []
    return ["", "=" * 70, "READABILITY GATE — FAILED", "=" * 70,
            "; ".join(report.reasons),
            f"Measured: {report.words:,} words, {report.sentences:,} sentences, "
            f"FK grade {report.fk_grade}, reading ease {report.flesch_ease}.",
            "",
            "Only two things move these numbers: sentence length and syllables per",
            "word. The sentence gate above covers the first. For the second, prefer",
            "the plain word wherever it is just as precise, and prefer a verb to a",
            "nominalization. A long sentence made of short words is free."]


def _length_brief(report):
    if report.passed:
        return []
    return ["", "=" * 70, "LENGTH GATE — FAILED", "=" * 70, report.reason,
            "",
            "This one is NOT a find/replace fix and you should not attempt it as one.",
            "Over budget: raise a `structural` entry anchored on the least",
            "load-bearing claim's paragraph and say it must be cut. Under budget:",
            "raise a `structural` entry anchored on the claim that is asserted and",
            "never supported, and say what the replacement passage must show."]


def run_gates(prose, section, memory, references=None):
    """Every deterministic gate, run on the prose as it now stands. No model call.

    Returns (failures, brief, measurements). `failures` is the list of labelled
    strings the engine counts; `brief` is what the editor is told; `measurements` is
    what goes on the journal record.

    Free, so there is no reason not to run them again after the last pass applied its
    edits — an editor splitting long sentences to escape "too dense" can overshoot
    into "every sentence is the same length", and that damage is invisible to the pass
    that caused it."""
    heading = section.get("heading", "")
    evidence = memory.evidence_document()

    read = readability.score(prose)
    sent = sentences.score(prose)
    para = paragraphs.check(prose, section_name=heading)
    nums = numbers.check(prose, evidence)
    terms = terminology.check(prose, memory.terminology)
    cites = citations.check(prose, references if references is not None
                            else memory.references)
    words = length.check(read.words, budget=section.get("words"))

    failures = []
    if not nums.passed:
        failures.append("NUMBERS: " + "; ".join(nums.reasons))
    if not terms.passed:
        failures.append("TERMINOLOGY: " + "; ".join(terms.reasons))
    if not cites.passed:
        failures.append("CITATIONS: " + "; ".join(cites.reasons))
    if not sent.passed:
        failures.append("SENTENCES: " + "; ".join(sent.reasons))
    if not para.passed:
        failures.append("PARAGRAPHS: " + "; ".join(para.reasons))
    if not words.passed:
        failures.append("LENGTH: " + words.reason)
    if not read.passed:
        failures.append("READABILITY: " + "; ".join(read.reasons))

    # Ordered worst-first on purpose. An editor with a turn budget reads the top of
    # its brief most carefully, and a wrong number costs more than a long sentence.
    brief = "\n".join(_number_brief(nums) + _terminology_brief(terms)
                      + _citation_brief(cites) + _sentence_brief(sent, prose)
                      + _paragraph_brief(para) + _length_brief(words)
                      + _readability_brief(read))

    measurements = {
        "words": read.words,
        "fk_grade": read.fk_grade,
        "flesch_ease": read.flesch_ease,
        "sentence_mean": sent.mean,
        "sentence_stdev": sent.stdev,
        "long_share": sent.long_share,
        "paragraphs": para.total,
        "paragraph_defects": len(para.defects),
        "numbers_checked": nums.checked,
        "numbers_unsupported": len(nums.unsupported),
        "terminology_defects": len(terms.defects),
        "passed": not failures,
    }
    return failures, brief, measurements


def _severity(raw, default):
    word = str(raw or "").strip().lower()
    if word in _BLOCKING_WORDS:
        return "blocking"
    if word in _POLISH_WORDS:
        return "polish"
    return default


def _kind(raw):
    word = str(raw or "").strip().lower()
    return word if word in _KINDS else "claim"


def normalise(payload):
    """Turn whatever the editor returned into (issues, structural).

    Tolerant on purpose, and asymmetric on purpose. An issue whose severity word is
    unrecognised defaults to `blocking` when it is about facts or readability and
    `polish` when it is about style, because the expensive mistake differs by kind: a
    missed wrong number ships a wrong paper, while a missed style note costs nothing.

    An issue with no usable anchor is not discarded — it is carried as an unfixable
    blocking issue, so the engine can see that the editor found something it could not
    repair rather than silently believing the section clean."""
    issues, structural = [], []
    for raw in (payload or {}).get("issues") or []:
        if not isinstance(raw, dict):
            continue
        kind = _kind(raw.get("kind"))
        find = raw.get("find") or ""
        replace = raw.get("replace")
        default = "blocking" if kind in _BLOCKING_KINDS else "polish"
        issues.append({
            "kind": kind,
            "severity": _severity(raw.get("severity"), default),
            "issue": str(raw.get("issue") or "").strip(),
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


def model_review(project_rec, paper_num, section_num, prose, truth, gate_brief,
                 pass_num, log_fn=None):
    """Model seam: one editorial pass over the draft.

    The draft and the ground truth arrive **inline**. They used to arrive as file
    paths with the instruction to go and read them, which on a turn-based provider
    re-sends every tool result on every later turn — a single review metered at
    hundreds of thousands of input tokens against a few thousand of verdict. Quoted
    into the prompt it is one turn and roughly a tenth of that, at the same model and
    the same judgement."""
    out_path = paths.edit_path(project_rec["project_id"], paper_num, section_num,
                               pass_num)
    return text.produce_json(
        prompts.template("review"),
        [f"You are editing paper {paper_num}, section {section_num}. This is "
         f"editorial pass {pass_num}.",
         "",
         truth,
         gate_brief,
         "",
         "=" * 70,
         "THE SECTION (this is the complete text; your `find` anchors are copied "
         "from here character-for-character):",
         "=" * 70,
         prose],
        out_path,
        role="review",
        artifact="your edit list as strict JSON",
        shape=_EDIT_SHAPE,
        log_fn=log_fn)


def gate_failures(project_rec, paper_num, section, prose):
    """The deterministic gates, re-run on committed prose. No model call.

    Every editorial pass applies its edits and then either finishes or runs another
    pass — so whatever the *last* pass changed is committed without anything looking
    at it again. Most of that is unverifiable without another judgement call, which is
    exactly what the budget exists to bound. But the gates are arithmetic and cost
    nothing, so there is no reason not to look."""
    memory = store.load(project_rec, paper_num)
    failures, _, measurements = run_gates(prose, section, memory)
    return failures, measurements


def review(project_rec, paper_num, section, prose, pass_num=1, log_fn=None):
    """Run one editorial pass. Returns a report; applies nothing.

    Report keys:
      issues        — anchored find/replace repairs, each with kind and severity
      structural    — defects needing new prose, each with an anchor and an instruction
      blocking      — every blocking issue as a labelled string, for the log and the
                      outstanding-issues record
      gate_failures — which hard gates this text fails right now
      measurements  — every number the gates computed, for the journal
    """
    section_num = section["number"]
    memory = store.load(project_rec, paper_num)
    failures, gate_brief, measurements = run_gates(prose, section, memory)

    payload = model_review(project_rec, paper_num, section_num, prose,
                           ground_truth(project_rec, paper_num, section), gate_brief,
                           pass_num, log_fn=log_fn)
    issues, structural = normalise(payload)

    blocking = [f"{i['kind'].upper()}: {i['issue']}"
                for i in issues + structural if i["severity"] == "blocking"]
    polish = [f"{i['kind']} (polish): {i['issue']}"
              for i in issues + structural if i["severity"] != "blocking"]

    return {
        "issues": issues,
        "structural": structural,
        "blocking": blocking,
        "polish": polish,
        "gate_failures": failures,
        "fact_issues": [i for i in issues + structural
                        if i["kind"] in ("number", "citation", "terminology")
                        and i["severity"] == "blocking"],
        "measurements": measurements,
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
