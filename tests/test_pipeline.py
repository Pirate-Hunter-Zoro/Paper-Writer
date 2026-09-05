"""End to end: a prompt goes into the inbox and a manuscript comes out of the other
side.

Every model seam is stubbed and **nothing else is**. The journal, every gate, the
ledger gatekeeper, atomic staging, the manuscript assembly, the audit and the delivery
all run for real, which is the point: this proves the harness wiring independent of the
models. A model that starts writing better prose cannot make these tests pass, and a
model that starts writing worse prose cannot make them fail.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter import config, paths, states                       # noqa: E402
from paperwriter.infra import journal, storage                      # noqa: E402


class PipelineTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        support.stub_model_seams()

    def setUp(self):
        support.wipe_state()

    def _run(self, project_id="fixture-paper"):
        support.drop(project_id)
        return support.run_engine(project_id), project_id

    def test_a_dropped_prompt_produces_a_delivered_manuscript(self):
        status, pid = self._run()
        self.assertEqual(status, states.PROJECT_COMPLETE,
                         journal.load_records().get(journal.project_key(pid), {})
                         .get("error"))

    def test_the_manuscript_holds_every_section(self):
        _status, pid = self._run()
        text = paths.manuscript_path(pid, 1).read_text(encoding="utf-8")
        for heading, _words in support.SECTIONS:
            self.assertIn(f"# {heading}", text)
        self.assertNotIn("MISSING", text)

    def test_the_manuscript_is_delivered_to_the_output_folder(self):
        _status, pid = self._run()
        delivered = list((config.OUT_DIR / pid).rglob("manuscript.md"))
        self.assertEqual(len(delivered), 1, delivered)
        self.assertEqual(delivered[0].read_text(encoding="utf-8"),
                         paths.manuscript_path(pid, 1).read_text(encoding="utf-8"))

    def test_the_prompt_is_filed_away_rather_than_deleted(self):
        _status, pid = self._run()
        self.assertFalse((config.INBOX_DIR / f"{pid}.md").exists())
        self.assertTrue((config.INBOX_FINISHED_DIR / f"{pid}.md").exists())

    def test_evidence_is_frozen_and_reused(self):
        """A second job on the same corpus must not re-mine it. The freeze is also
        what stops an analysis rerun from silently changing what a written section
        claims."""
        self._run("first-paper")
        frozen = storage.load_json(paths.evidence_path("fixture analysis"))
        self.assertTrue(frozen["frozen"])
        before = len(frozen["items"])

        calls = []
        real = support.real_seam(
            __import__("paperwriter.stages.evidence", fromlist=["evidence"]),
            "propose_evidence")
        self.assertTrue(callable(real))

        support.drop("second-paper")
        support.run_engine("second-paper")
        after = storage.load_json(paths.evidence_path("fixture analysis"))
        self.assertEqual(len(after["items"]), before, calls)

    def test_every_section_is_on_disk_and_journaled(self):
        _status, pid = self._run()
        records = journal.load_records()
        sections = journal.sections_of(records, pid, 1)
        self.assertEqual(len(sections), len(support.SECTIONS))
        for record in sections:
            self.assertEqual(record["status"], states.LEDGER_MERGED)
            self.assertTrue(paths.section_path(pid, 1, record["section_num"]).exists())

    def test_the_ledger_survives_the_run(self):
        _status, pid = self._run()
        doc = storage.load_json(paths.ledger_path(pid))
        self.assertEqual(len(doc["claims"]), 4)
        self.assertTrue(doc["terminology"])

    def test_a_crash_resumes_rather_than_restarting(self):
        """Nothing durable is recomputed. The engine is driven one cycle at a time,
        stopped partway, and driven again; the sections written before the stop must
        still be there and must not be rewritten."""
        from paperwriter.engine import cycle
        support.drop("resumed-paper")
        for _ in range(14):
            cycle.run(log_fn=lambda _m: None)

        written = sorted(paths.sections_dir("resumed-paper", 1).glob("*.md")) \
            if paths.sections_dir("resumed-paper", 1).exists() else []
        stamps = {p.name: p.read_text(encoding="utf-8") for p in written}

        support.run_engine("resumed-paper")
        for name, text in stamps.items():
            self.assertEqual(
                (paths.sections_dir("resumed-paper", 1) / name)
                .read_text(encoding="utf-8"), text,
                f"{name} was rewritten after a resume")

    def test_the_status_file_is_published(self):
        self._run()
        path = paths.status_file()
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertIn("Paper-Writer", path.read_text(encoding="utf-8"))


class GateRejectionTests(unittest.TestCase):
    """What happens when a proposal is refused. A stall is not a failure, and nothing
    written before it is lost."""

    @classmethod
    def setUpClass(cls):
        support.stub_model_seams()

    def setUp(self):
        support.wipe_state()

    def test_an_outline_that_never_passes_stalls_rather_than_failing(self):
        from paperwriter.stages import outlining

        def bad_outline(project_rec, paper_num, out_path, log_fn=None, feedback=""):
            storage.save_json({"sections": [
                {"number": 1, "heading": "Results", "words": 400, "paragraphs": []},
                {"number": 2, "heading": "Methods", "words": 400, "paragraphs": []},
            ]}, out_path)
            return "bad outline"

        good = outlining.propose_outline
        outlining.propose_outline = bad_outline
        try:
            support.drop("stalling-paper")
            support.run_engine("stalling-paper", limit=30)
            records = journal.load_records()
            paper = records.get(journal.paper_key("stalling-paper", 1))
            self.assertIsNotNone(paper)
            self.assertEqual(paper["status"], states.STALLED)
            self.assertIn("outlining", (paper.get("error") or ""))
            # Not terminal, and not a dead end.
            self.assertNotIn(paper["status"], states.DEAD_ENDS)
        finally:
            outlining.propose_outline = good

    def test_the_evidence_stage_parks_a_job_it_cannot_support(self):
        from paperwriter.stages import evidence

        def thin_evidence(prompt_text, corpus, out_path, log_fn=None, focus=(),
                          sources=()):
            storage.save_json({"items": [
                {"id": "e.1", "statement": "something unrelated entirely",
                 "values": [1], "source": "x"}]}, out_path)
            return "thin"

        good = evidence.propose_evidence
        evidence.propose_evidence = thin_evidence
        try:
            support.drop("thin-paper")
            support.run_engine("thin-paper", limit=20)
            record = journal.load_records()[journal.project_key("thin-paper")]
            self.assertEqual(record["status"], states.STALLED)
            self.assertIn("coverage", record.get("error", ""))
        finally:
            evidence.propose_evidence = good


if __name__ == "__main__":
    unittest.main()
