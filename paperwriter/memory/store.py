"""Loading the three layers off disk, in one place.

`ledger.py` is schemas and rules; `digest.py` is pure assembly of already-loaded
state. Neither of them reads a file, deliberately — that is what makes the gatekeeper
and the writer's brief testable with fixtures and nothing else.

Which leaves the reading itself, and it was being done three times: drafting loaded
the plan, the ledger, and the evidence to build its brief; the review pass and the
ledger merge each did their own partial version, or worse, handed the model a path and
told it to go and read the file itself. Three copies of "which files are the memory"
is three chances for one of them to be reading a stale or different set.

So: one loader, returning one record. It reads, it does not interpret — every rule
about what the memory *means* stays in `ledger.py`, and every decision about what a
given model is shown stays in `digest.py`.
"""

from .. import paths
from ..infra import storage
from .ledger import new_evidence, new_project_ledger


class Memory:
    """Everything on disk about one project, loaded once.

    Attributes are the three layers plus the plan-derived writing constraints:

      * `ledger`      — the project ledger (claims, terminology, references,
                        conventions, open questions)
      * `evidence`    — {corpus: evidence document}, immutable ground truth
      * `plan`        — the project plan
      * `grounding`   — the estimand, the reader, the reporting checklist
      * `paper_ledger`— the derived working slice for one paper, when asked for one

    There is deliberately no per-section word *target* here. The budget lives in the
    outline, because it is a property of the plan rather than of the project: two
    papers in one project go to two journals with two different limits.
    """

    def __init__(self, ledger, evidence, plan, grounding, paper_ledger=None):
        self.ledger = ledger
        self.evidence = evidence
        self.plan = plan
        self.grounding = grounding
        self.paper_ledger = paper_ledger or {}

    @property
    def terminology(self):
        return self.ledger.get("terminology") or []

    @property
    def conventions(self):
        return self.ledger.get("conventions") or {}

    @property
    def references(self):
        return self.ledger.get("references") or {}

    def evidence_document(self):
        """Every corpus merged into one document, for the gates that ask "is this
        number anywhere in the evidence".

        Merged rather than searched corpus by corpus because the question is never
        "which corpus vouches for 0.7429" — it is "does anything". Ids are globally
        unique by construction: the gathering stage namespaces them per corpus."""
        items, allow = [], []
        for document in self.evidence.values():
            items.extend(document.get("items") or [])
            allow.extend(document.get("also_allow") or [])
        return {"corpus": "(all)", "frozen": True, "items": items,
                "also_allow": allow}


def load(project_rec, paper_num=None):
    """Load one project's memory. `paper_num` selects the paper for per-paper state."""
    pid = project_rec["project_id"]
    plan = storage.load_json(paths.plan_path(pid), {})
    ledger = storage.load_json(paths.ledger_path(pid), new_project_ledger(pid))
    grounding = storage.load_json(paths.grounding_path(pid), {})
    evidence = {c: storage.load_json(paths.evidence_path(c), new_evidence(c))
                for c in project_rec.get("corpora", [])}

    paper_ledger = {}
    if paper_num is not None:
        paper_ledger = storage.load_json(paths.paper_ledger_path(pid, paper_num), {})

    return Memory(ledger=ledger, evidence=evidence, plan=plan, grounding=grounding,
                  paper_ledger=paper_ledger)
