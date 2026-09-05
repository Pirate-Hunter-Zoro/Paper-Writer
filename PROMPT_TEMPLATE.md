# <working title of the paper>

Copy this file into the drop folder, fill it in, and the harness picks it up on its next
cycle. Everything below is read by deterministic code before any model runs, so the
shapes matter: keep the headings, keep the lists as lists.

Delete the guidance lines as you go. What you leave behind is the job.

---

## Evidence

<!-- The corpus name(s) this paper draws on. ONE line. Split a genuinely separate
     second body of evidence with a `+`. This becomes a directory under state/evidence/
     and is shared by every job naming it, so a programme of three papers off one
     analysis gathers once. Everything after this first line is description and is
     ignored by the parser. -->

TRD-EHR primary analysis

<!-- Point PAPER_SOURCE_DIRS at the directories the gathering stage may read. Set it in
     the environment or in the service file, colon-separated:

       PAPER_SOURCE_DIRS=~/TRD-EHR/results:~/Research-Journey/paper1/references

     Those trees are read-only ground truth. Nothing here ever writes into them. -->

---

## Claims

<!-- What this paper argues, one bullet each. These are the denominator of the evidence
     coverage gate: if the frozen evidence cannot support 85% of them, the job parks and
     gathers more rather than drafting on numbers nobody has.

     Write them as claims, not topics. "Model comparison" is a heading. "The embedded
     representation discriminates better than the feature representation on the
     held-out split" is a claim.

     Include the limitation you already know a reviewer will raise. A limitation planned
     now is one the paper can answer. -->

- The embedded representation discriminates treatment resistance better than the typed
  feature vector on a held-out split.
- Performance is stable across the six largest demographic subgroups.
- The signal in the embedded representation is sparse rather than diffuse: six narrative
  concepts carry nearly all of it.
- The outcome label counts antidepressant trials and is not adequacy-verified, so it is
  a proxy for the consensus definition rather than the definition itself.

---

## Venue

<!-- The target journal, and its word limit. The limit is parsed out of this section —
     the first number followed by "word" wins — and it becomes a hard ceiling the
     outline gate enforces. Omit it if you genuinely do not know; a wrong number plans
     the manuscript to the wrong length. -->

JMIR Mental Health. 4,000 word limit for an Original Paper, excluding abstract,
references and tables.

<!-- Optional: a reference .docx supplying the journal's styles, for the pandoc build.
     Any path ending in .docx in this section is picked up. -->

formats/JMIR_template.docx

---

## Reporting checklist

<!-- Named, never inferred. Inferring it from the study design produces an outline that
     places the wrong obligations, and asking costs one line. `none` is a valid answer
     if you say why. -->

TRIPOD+AI

---

## Scope

<!-- How many papers this job is. One unless you say otherwise, and one is the normal
     case — a single paper is the degenerate case of the same machinery, not a special
     path. Say "2 papers" here only if the evidence genuinely supports two separable
     arguments, because two papers arguing one finding is a duplicate submission. -->

1 paper.

---

## Anything the harness cannot work out

<!-- Free prose. Read by the grounding and planning stages, ignored by the parsers.
     Useful things to put here:

       - Terminology you already know must be locked, and the synonyms that must never
         appear. The grounding stage will propose a lock; telling it what you already
         know saves a round.
       - Author list, affiliations, funding, ethics statement.
       - What the paper explicitly does NOT claim.
       - Anything a coauthor has already ruled on. -->

There are exactly two patient representations and they are called the FEATURE
representation and the EMBEDDED representation. "Rule-based" is not an alias for either
and must not appear anywhere. Where the point is that no generative model participates,
the word is "deterministic".

This is secondary analysis of de-identified data and is not human-subjects research, so
there is no protocol number and no consent waiver to name.
