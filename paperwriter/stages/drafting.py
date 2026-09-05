"""Drafting. Hand the writer a focused brief; get one section.

The writer receives only the brief — the evidence this section's claims rest on, the
locked vocabulary, the conventions the earlier sections established, the paragraph
plan it has to follow, where the previous section actually ended, and the prose
contract — never the whole memory. The draft lands at `paths.draft_path`, which is a
proposal and nothing more.

**A section is drafted exactly once.** Everything after that is repair: anchored
find/replace edits from `stages/review`, or an anchored passage replacement from
`stages/surgery`. There is no rewrite path here and there must never be one.

That is not a stylistic preference. A revision that re-emits a whole section changes
words it was told to leave alone — not out of disobedience, but because regenerating
prose is a different operation from preserving it. Measured, sections whose defects
were repaired by rewriting random-walk (2 -> 10 -> 6 -> 14) and cost twenty attempts;
the same defects repaired by anchored edits fall monotonically and cost two or three.
The instruction "change nothing else" was in the prompt the whole time. An instruction
is not a mechanism.

The one thing that legitimately produces more prose is a *continuation*: a first draft
that stopped short of its budget is handed back and asked for what comes next. That is
additive and touches nothing already written, which is why it is safe and why it is
here. It fires only when the draft is genuinely below its floor, and it is told
exactly which planned paragraphs are still missing — because a writer asked simply for
more words will hedge, restate, and add a sentence about what the section will go on
to show, which is the padding this project spends its editorial budget deleting.
"""

from .. import config, paths
from ..gates import prose as prose_gate
from ..memory import store
from ..memory.digest import build_section_brief
from ..models import prompts, text
from . import grounding


def generate(prompt, out_path, log_fn=None, role="drafting"):
    """Model seam: write section prose to out_path.

    ONE seam for the first draft, any continuation pass, and passage surgery — `role`
    selects which budget the call is charged to. Splitting them into separate
    functions immediately breaks the test suite: every test stubs this one name, so a
    second entry point goes straight to the live provider and the suite starts making
    real API calls. A stage's model calls have to funnel through a single replaceable
    function or the seam is not a seam."""
    return text.run(prompt, out_path, role=role, log_fn=log_fn)


def _words(text_):
    return prose_gate.word_count(prose_gate.strip_structure(text_))


def _missing_paragraphs(section, drafted):
    """Which planned paragraphs the draft has not written yet.

    Matched on the topic sentence's identifying words rather than on the sentence
    itself: the writer is expected to phrase the topic sentence better than the plan
    did, so an exact-match check would report every paragraph as missing."""
    have = drafted.lower()
    out = []
    for i, para in enumerate((section.get("paragraphs") or []), start=1):
        topic = str(para.get("topic") or "")
        tokens = [w.lower() for w in prose_gate.words(topic) if len(w) >= 5]
        if not tokens:
            continue
        hit = sum(1 for t in tokens if t in have)
        if hit < max(1, len(tokens) // 2):
            out.append(f"  Paragraph {i}: {topic}")
    return out


def _continue_prompt(drafted, section, floor, have, missing, ground_truth):
    """Ask for the REST of a section that stopped short — not a rewrite of it.

    The harness concatenates, so the model is asked only for the new text. Asking it
    to reproduce everything so far plus more would pay for the same prose twice and
    invite it to quietly revise what was already written.

    What it is told to add matters as much as that it is additive. Asked simply for
    more words, a model that has finished its argument writes a paragraph about what
    the section has just shown — which is how a word budget manufactures the exact
    padding the length gate exists to catch. So the instruction names what "more" is
    allowed to be: the planned paragraphs that are not there yet."""
    return "\n".join([
        "You are continuing a section of an academic paper that is not finished yet.",
        "",
        "Below is the section SO FAR. It stops short of its plan. Write what comes "
        "next — and ONLY what comes next.",
        "",
        f"It currently runs {have:,} words. The floor is {floor:,}, so it is about "
        f"{max(floor - have, 0):,} words short.",
        "",
        "THE PLANNED PARAGRAPHS IT HAS NOT WRITTEN YET. Write these, in this order, "
        "each opening on the claim given:",
        "\n".join(missing) or "  (none identified — finish the argument the plan sets "
                              "out)",
        "",
        ground_truth,
        "",
        "=" * 70,
        "THE SECTION SO FAR",
        "=" * 70,
        drafted,
        "=" * 70,
        "",
        "Rules:",
        "- Do NOT repeat, summarise, or rewrite any of the text above. It is already "
        "written and it is staying exactly as it is.",
        "- Begin at the precise moment it stops. Your first sentence should read as "
        "the next sentence of the paper.",
        "- Match the tense, person and register exactly. A reader must not be able to "
        "find the join.",
        "- **Every number you write must be in the evidence above, character for "
        "character.** No rounding, no approximation, no figure you remember.",
        "- Every paragraph opens on its own claim and closes on what it means.",
        "- One idea per sentence. Mean under 22 words, lengths varied, nothing past "
        "55, and rationing semicolons and em-dashes to about two per thousand words.",
        "- **The extra words are for support, not for emphasis.** Do NOT add a "
        "paragraph restating what the section has shown, do not add hedges, and do "
        "not add a sentence introducing the next sentence. If you need more section, "
        "the plan above says what is missing.",
    ])


def _extend_to_length(drafted, out_path, project_rec, section, memory, ground_truth,
                      log_fn=None):
    """Grow a draft that came in under its floor, by continuation rather than padding.

    A single completion reliably lands short of a long section, because a section is
    several paragraphs and gets written the way a person writes it. Without a path
    from "too short" to "long enough" the length gate would simply reject and there
    would be nothing to send anywhere.

    It fires only when the draft is genuinely below the floor — not merely under its
    target — and stops the moment it is above. A section that makes its claims in 400
    words against a 500-word budget is finished, and asking it for a hundred more is
    asking for filler."""
    budget = int(section.get("words") or 0)
    floor = max(config.SECTION_MIN_WORDS,
                int(budget * config.SECTION_UNDER_BUDGET_RATIO)) if budget \
        else config.SECTION_MIN_WORDS
    if floor <= 0:
        return drafted

    for pass_num in range(1, config.DRAFT_MAX_CONTINUATIONS + 1):
        have = _words(drafted)
        if have >= floor:
            break
        cont_path = paths.continuation_path(
            project_rec["project_id"], section.get("number", 0), pass_num)
        if log_fn:
            log_fn(f"draft is {have:,} words, under the {floor:,} floor; continuation "
                   f"pass {pass_num}/{config.DRAFT_MAX_CONTINUATIONS}")
        prompt = text.compose(
            "", _continue_prompt(drafted, section, floor, have,
                                 _missing_paragraphs(section, drafted), ground_truth),
            cont_path, artifact="ONLY the continuation prose (Markdown)",
            role_name="continuation")
        generate(prompt, cont_path, log_fn=log_fn, role="continuation")
        addition = cont_path.read_text(encoding="utf-8").strip()
        if not addition:
            break
        grown = drafted.rstrip() + "\n\n" + addition + "\n"
        # A continuation that adds nothing is a loop that will not terminate; stop
        # rather than spend the remaining passes discovering that again.
        if _words(grown) <= have:
            break
        drafted = grown
        out_path.write_text(drafted, encoding="utf-8")
    return drafted


def draft_section(project_rec, paper_num, section, prev_exit, prev_tail="",
                  log_fn=None):
    """Draft one section into staging, extending it to length. Returns (text, path)."""
    memory = store.load(project_rec, paper_num)
    pid = project_rec["project_id"]
    ground = grounding.block(pid)

    brief = build_section_brief(
        section, prev_exit, memory.ledger, memory.evidence_document(),
        conventions=memory.conventions, prev_section_tail=prev_tail,
        grounding_block=ground,
        sentence_max=config.SENTENCE_MEAN_WORDS_MAX,
        long_words=config.SENTENCE_LONG_WORDS,
        long_share=config.SENTENCE_LONG_SHARE_MAX)

    n = section["number"]
    out_path = paths.draft_path(pid, paper_num, n)

    prompt = text.compose(
        prompts.template("draft"), brief, out_path,
        artifact="ONLY the section prose (Markdown, no heading)",
        role_name="drafting")
    generate(prompt, out_path, log_fn=log_fn)
    drafted = out_path.read_text(encoding="utf-8")

    from ..memory.digest import build_ground_truth
    truth = build_ground_truth(section, memory.ledger, memory.evidence_document(),
                               grounding_block=ground)
    drafted = _extend_to_length(drafted, out_path, project_rec, section, memory,
                                truth, log_fn=log_fn)
    return drafted, out_path
