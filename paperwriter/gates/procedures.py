"""A named procedure whose defining parameter the paper never states.

`numbers` checks that every figure in the prose is one the analysis produced. This
checks the other direction: a figure the analysis must have produced, that the prose
never gives. Naming a procedure is not specifying it, and the missing parameter is
always the one a reader would need to reproduce the result or judge it.

**The failures this was written from.** One manuscript said "adjusted across the
entire reported set by Benjamini-Hochberg" and never once stated the false discovery
rate it controlled. It said "confidence intervals were estimated by resampling
test-set patients with replacement" and never stated how many resamples. Both numbers
existed — 5% and 1,000, sitting in the analysis code — and neither reached the paper.
A reviewer cannot check either claim, and the author cannot see the gap, because the
sentence reads as complete.

**Why this is a whole-document check.** A paper says "bootstrap" in every figure
caption and should not restate the resample count in each one. The question is not
whether *this* sentence carries the parameter, it is whether the document carries it
anywhere. So the gate collects every sentence naming a procedure and asks whether any
one of them states the number.

**What counts as stating it** differs per procedure, and that is the whole precision of
the check. A multiplicity correction is specified by a rate, so "0.05" or "5%" counts
and "240 contrasts" does not. A bootstrap is specified by a count of resamples, so
"1,000" counts and "95%" — which appears beside every interval ever reported — does
not. Getting that distinction wrong turns the gate into noise, because both procedures
are surrounded by numbers that are not their parameter.

No models, no I/O.
"""

import re
from dataclasses import dataclass, field

from . import prose


@dataclass
class ProcedureDefect:
    procedure: str            # "Benjamini-Hochberg", "bootstrap"
    parameter: str            # what is missing, in words
    sentence: str             # one place it is named, for the edit anchor
    mentions: int


@dataclass
class ProcedureReport:
    defects: list = field(default_factory=list)
    checked: dict = field(default_factory=dict)     # procedure -> mention count
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        named = ", ".join(f"{k} x{v}" for k, v in sorted(self.checked.items()))
        return f"{named or 'no named procedures'}; {len(self.defects)} unspecified"


# Each entry: the label, what names it, what its parameter is called, and what a
# statement of that parameter looks like. The last pattern is the load-bearing one.
_PROCEDURES = (
    ("Benjamini-Hochberg",
     re.compile(r"(?<![a-z])(?:benjamini[\s-]*hochberg|false\s+discovery\s+rate|"
                r"\bFDR\b|bonferroni|holm[\s-]*bonferroni|(?<![a-z])holm(?![a-z]))",
                re.IGNORECASE),
     "the error rate it controls",
     # A rate: a small decimal, or a percentage under 100. "240 contrasts" is not one.
     re.compile(r"0?\.\d+|(?<![\d.])(?:1|5|10)\s?%")),

    ("bootstrap",
     re.compile(r"(?<![a-z])bootstraps?(?:ed|ping)?(?![a-z])", re.IGNORECASE),
     "the number of resamples",
     # A count: three or more digits, not a percentage. "95% CI" sits beside every
     # bootstrap interval in every paper and is not the resample count.
     re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d%])|(?<![\d.,])\d{3,}(?![\d%])")),

    ("permutation test",
     re.compile(r"(?<![a-z])permutation\s+(?:test|scheme|null)(?![a-z])",
                re.IGNORECASE),
     "the number of permutations",
     re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d%])|(?<![\d.,])\d{3,}(?![\d%])")),

    ("cross-validation",
     re.compile(r"(?<![a-z])cross[\s-]*validat(?:ion|ed)(?![a-z])", re.IGNORECASE),
     "the number of folds",
     re.compile(r"(?<![\d.])\d{1,2}[\s-]*fold|(?<![a-z])(?:five|ten|three)[\s-]*fold",
                re.IGNORECASE)),
)


def check(*texts):
    """Gate every document of a paper together. Returns a ProcedureReport.

    Pass the manuscript and its supplement. A parameter stated in either specifies the
    procedure for both, because they are one submission."""
    sentences = []
    for text in texts:
        sentences.extend(prose.sentences(prose.strip_structure(text or "")))

    defects, checked = [], {}
    for label, names, parameter, states_it in _PROCEDURES:
        named = [s for s in sentences if names.search(s)]
        if not named:
            continue
        checked[label] = len(named)
        if any(states_it.search(s) for s in named):
            continue
        defects.append(ProcedureDefect(
            procedure=label, parameter=parameter, sentence=named[0],
            mentions=len(named)))

    reasons = []
    for defect in defects:
        reasons.append(
            f"{defect.procedure} is named {defect.mentions} time(s) and "
            f"{defect.parameter} is never given. Naming a procedure is not specifying "
            f"it, and a reader cannot check the result without that number. It first "
            f"appears in: \"{defect.sentence[:80]}...\"")

    return ProcedureReport(defects=defects, checked=checked,
                           passed=not reasons, reasons=reasons)
