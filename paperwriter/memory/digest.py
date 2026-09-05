"""Build the focused brief handed to the writer for one section.

The writer is NEVER handed the whole three-layer memory. It neither fits a context
window nor stays coherent when it does. It is handed a tight, relevant slice: the
evidence items this section's claims rest on, the terminology it must use, the
conventions the earlier sections established, the paragraph plan it has to follow,
where the previous section actually ended, and the prose contract every section is
written under.

Two things this module is deliberately strict about, and both are corrections of what
a writer does when left to its own judgement.

**The evidence slice is exhaustive and quoted.** Every number the section may use is
listed with its source, verbatim, and the brief says outright that a number not on the
list is a defect. A writer given "the AUC was around 0.74" writes 0.74; a writer given
"E12: test-set AUC 0.7429 (results/metrics.json)" writes 0.7429. The difference is
one line of a brief and it is the difference between a manuscript that survives review
and one that does not.

**The paragraph plan is the section's shape and is not negotiable.** Each paragraph
arrives with the topic sentence it must open on, decided at outline time. The writer
expands each into a paragraph; it does not merge two, split one, or add a seventh.
That was the outline's decision, made when the whole paper was in view.

Pure function of already-loaded state, so it is deterministic and testable: same
inputs, same brief, no model call.
"""

from .ledger import one_line


def _evidence_slice(evidence, wanted_ids):
    """The evidence items a section is allowed to draw numbers from, verbatim.

    Ordered by the id order the outline gave, not by the order the evidence happens to
    be stored in, so the brief reads in the order the section will use them."""
    by_id = {str(i.get("id")): i for i in (evidence or {}).get("items", [])
             if i.get("id")}
    out = []
    for eid in wanted_ids:
        item = by_id.get(str(eid))
        if not item:
            out.append(f"  [{eid}] MISSING — this evidence id is not in the frozen "
                       f"reference. Do not invent a number for it.")
            continue
        values = ", ".join(str(v) for v in (item.get("values") or []))
        line = f"  [{eid}] {item.get('statement', '')}"
        if values:
            line += f"\n        exact values you may write: {values}"
        line += f"\n        source: {item.get('source', '(unstated)')}"
        out.append(line)
    return out


def _terminology_block(lock):
    """The vocabulary, and what is forbidden. Both halves, because a list of approved
    words does not stop a writer reaching for a synonym — naming the synonym does."""
    if not lock:
        return []
    parts = ["THE VOCABULARY. One name per thing. These are locked and every one of",
             "them is checked by a gate that counts, not by a reader who might not "
             "notice:"]
    for entry in lock:
        term = entry.get("term")
        line = f"  {term}"
        if entry.get("first_use"):
            line += f"  (write it out as \"{entry['first_use']}\" at its first "
            line += "appearance in this section, then use the short form)"
        if entry.get("definition"):
            line += f"\n      {one_line(entry['definition'])}"
        aliases = [a for a in entry.get("aliases") or []]
        if aliases:
            line += ("\n      NEVER write: "
                     + ", ".join(f"\"{a}\"" for a in aliases[:8]))
        parts.append(line)
    return parts


def _conventions_block(conventions):
    if not conventions:
        return []
    parts = ["THE CONVENTIONS the earlier sections established. Follow them; do not",
             "improve on them:"]
    parts += [f"  {name}: {value}" for name, value in sorted(conventions.items())]
    return parts


def _paragraph_plan(section):
    """The section's shape, paragraph by paragraph."""
    plans = section.get("paragraphs") or []
    if not plans:
        return ["  (no paragraph plan — write the section as the claims require)"]
    out = []
    for i, para in enumerate(plans, start=1):
        out.append(f"  Paragraph {i} — opens on this claim:")
        out.append(f"      {para.get('topic', '')}")
        if para.get("supports"):
            out.append(f"      supported by: {', '.join(str(s) for s in para['supports'])}")
        if para.get("evidence"):
            out.append(f"      evidence to cite: "
                       f"{', '.join(str(e) for e in para['evidence'])}")
        if para.get("closes"):
            out.append(f"      closes on: {para['closes']}")
    return out


# The prose contract, in the brief itself rather than only in the template. It is
# repeated here on purpose: the template is a committed file a person edits, and this
# is the specific arithmetic the gates will apply to THIS section, with THIS section's
# numbers in it. An instruction the writer can check itself against is worth several
# it cannot.
def _prose_contract(budget, sentence_max, long_words, long_share):
    return [
        "HOW IT HAS TO READ. Every sentence is read once. If a reader has to go back",
        "over one, that sentence failed however correct it is. This is measured after",
        "you write it, by arithmetic, and a section that fails comes straight back:",
        "",
        f"  * Sentences average under {sentence_max:.0f} words. Vary them — put a",
        "    six-word sentence next to a twenty-five-word one. Uniform length is the",
        "    loudest tell that nobody thought about the rhythm.",
        f"  * At most {long_share:.0%} of sentences run past {long_words} words, and",
        "    none runs past 55. A long sentence is two claims welded together.",
        "  * A semicolon or an em-dash is almost always a full stop that lost its",
        "    nerve. You have a budget of about two per thousand words. Spend them on",
        "    the one place where the pause is genuinely the point.",
        "  * Every paragraph opens on its own claim. Not on a citation, not on a",
        "    number, not on \"However\" or \"Furthermore\", not on a subordinate clause",
        "    that delays the claim past a comma. The claim goes first.",
        "  * Every paragraph closes on what it means. Not on one more citation.",
        "  * One idea per sentence. A trailing \"which\" clause is a second sentence.",
        "  * Verbs, not nominalizations. \"The model did worse when the chart said",
        "    unspecified\", never \"discrimination decreased for patients coded",
        "    unspecified\".",
        "  * Names and numbers, not adjectives. \"Three of the four intervals cross",
        "    zero\", never \"the results were largely null\".",
        "  * One hedge per claim, in its own sentence, and only when the hedge changes",
        "    what a reader would do.",
        "  * Delete every sentence whose only job is to introduce another one. \"It is",
        "    worth noting\", \"Importantly\", \"Taken together\" — say the thing instead.",
        "",
        f"  This section is budgeted at {budget:,} words. That is a ceiling as much as",
        "  a target: the journal's limit is fixed and the sections share it. If you",
        "  are running long, cut a claim. Do not compress sentences — compression is",
        "  exactly what produces prose that has to be read twice.",
    ]


def build_section_brief(section, prev_section_exit, ledger, evidence,
                        conventions=None, prev_section_tail="", grounding_block="",
                        sentence_max=22.0, long_words=35, long_share=0.08):
    """Assemble the writer's brief for one section as a single text block.

    * section             — the outline section dict (heading, words, claims,
                            evidence, paragraphs)
    * prev_section_exit   — what the previous section established, in one line, or ""
    * prev_section_tail   — the closing prose of the previous ACCEPTED section. The
                            outline's summary says what became true; this says how the
                            manuscript is actually reading at the join. They are not
                            the same thing, and a section written against only the
                            first repeats the sentence the last one ended on.
    * ledger              — the project ledger (claims, terminology, references)
    * evidence            — the frozen evidence document
    * grounding_block     — the estimand, the reader, and the reporting checklist, as
                            fixed by the grounding stage
    """
    n = section.get("number")
    heading = section.get("heading", "")
    budget = int(section.get("words") or 0)
    claim_ids = [str(c) for c in (section.get("claims") or [])]
    claims = ledger.get("claims", {}) if ledger else {}

    parts = [f"SECTION {n} — {heading}", "", "WRITING BRIEF", ""]

    parts.append("WHERE THE MANUSCRIPT IS (established by the sections before this "
                 "one — do not restate and do not contradict):")
    parts.append(f"  {prev_section_exit or '(this is the first section)'}")
    parts.append("")

    if prev_section_tail:
        parts += [
            "HOW THE PREVIOUS SECTION ACTUALLY ENDED (its last words, verbatim). Your",
            "first sentence follows this one. Do not repeat its final claim:",
            f"  ...{prev_section_tail}",
            ""]

    if grounding_block:
        parts += [grounding_block, ""]

    parts.append("WHAT THIS SECTION CLAIMS. These claims and no others — the argument "
                 "map was fixed before drafting and a claim invented here has no "
                 "evidence behind it:")
    if claim_ids:
        for cid in claim_ids:
            claim = claims.get(cid) or {}
            statement = claim.get("claim") or f"(claim {cid} is not in the ledger)"
            kind = claim.get("kind", "")
            marker = " [HEADLINE — this is what the paper is about]" \
                if claim.get("headline") else ""
            parts.append(f"  {cid} ({kind}){marker}: {statement}")
    else:
        parts.append("  (none declared — this section is structural)")
    parts.append("")

    wanted = list(dict.fromkeys(
        [e for cid in claim_ids for e in (claims.get(cid, {}).get("evidence") or [])]
        + [str(e) for e in (section.get("evidence") or [])]))
    if wanted:
        parts.append("THE EVIDENCE. Every number you write must be one of these, "
                     "character for character. A figure that is not on this list is a "
                     "blocking defect and the gate that finds it does not negotiate:")
        parts += _evidence_slice(evidence, wanted)
        parts.append("")

    parts += _terminology_block((ledger or {}).get("terminology"))
    if (ledger or {}).get("terminology"):
        parts.append("")

    parts += _conventions_block(conventions or (ledger or {}).get("conventions"))
    if conventions or (ledger or {}).get("conventions"):
        parts.append("")

    references = (ledger or {}).get("references") or {}
    if references:
        parts.append("THE REFERENCE LIST. Cite by these keys and no others. A marker "
                     "with no entry behind it is a source the reader cannot check:")
        for key in sorted(references)[:60]:
            entry = references[key]
            parts.append(f"  [{key}] {one_line(entry.get('title', ''), 90)} "
                         f"({entry.get('year', '')})")
        parts.append("")

    parts.append("THE SHAPE. One paragraph per entry, in this order, each opening on "
                 "the claim given. Do not merge two, do not split one, do not add a "
                 "paragraph the plan does not have:")
    parts += _paragraph_plan(section)
    parts.append("")

    parts += _prose_contract(budget or 500, sentence_max, long_words, long_share)
    parts.append("")

    if section.get("exit_state"):
        parts.append("THIS SECTION MUST LEAVE THE MANUSCRIPT HERE:")
        parts.append(f"  {section['exit_state']}")
        parts.append("")

    return "\n".join(parts)


def build_ground_truth(section, ledger, evidence, grounding_block=""):
    """Everything one section must not contradict, as one inline block.

    Handed to the editorial pass rather than to the writer, so it is broader than a
    brief: the editor is checking a finished section against the whole committed
    state, not writing against a slice of it. It still is not the whole memory —
    every reference in the library and every evidence item in the corpus would be
    most of a context window and none of it is what the editor is judging."""
    parts = ["=" * 70, "GROUND TRUTH — the section below must not contradict any of "
             "this", "=" * 70]

    if grounding_block:
        parts += ["", grounding_block]

    claim_ids = [str(c) for c in (section.get("claims") or [])]
    claims = (ledger or {}).get("claims", {})
    if claim_ids:
        parts += ["", "THE CLAIMS THIS SECTION IS FOR:"]
        for cid in claim_ids:
            claim = claims.get(cid) or {}
            parts.append(f"  {cid}: {claim.get('claim', '(not in the ledger)')}")

    wanted = list(dict.fromkeys(
        [e for cid in claim_ids for e in (claims.get(cid, {}).get("evidence") or [])]
        + [str(e) for e in (section.get("evidence") or [])]))
    if wanted:
        parts += ["", "THE EVIDENCE, verbatim. Any number in the section that is not "
                  "one of these is wrong, however plausible it looks:"]
        parts += _evidence_slice(evidence, wanted)

    lock = (ledger or {}).get("terminology")
    if lock:
        parts += [""] + _terminology_block(lock)

    conventions = (ledger or {}).get("conventions")
    if conventions:
        parts += [""] + _conventions_block(conventions)

    questions = [q for q in (ledger or {}).get("questions", [])
                 if q.get("status") == "open"]
    if questions:
        parts += ["", "QUESTIONS THIS PAPER HAS RAISED AND NOT YET ANSWERED. The "
                  "section may not assert an answer to one of these:"]
        parts += [f"  {q.get('id')}: {one_line(q.get('question'))}" for q in questions]

    return "\n".join(parts)
