"""Watchlist and constrained-ingest rules.

Drafts stay out of diet, activity, and monitoring advice until a person
accepts them. Portion text must be verbatim. The bibliographic checker must
not write a guideline PDF into the repository.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgm_report_advisor.analyze import analyze, has_lifestyle_prescriptions  # noqa: E402
from cgm_report_advisor.ingest import accept_draft, draft_from_file, draft_from_text  # noqa: E402
from cgm_report_advisor.knowledge import KnowledgeBase  # noqa: E402
from cgm_report_advisor.models import (  # noqa: E402
    ExtractedReport,
    IntakeRecord,
    KnowledgeEntry,
    KnowledgeSource,
)
from cgm_report_advisor.pipeline import run_pipeline  # noqa: E402
from cgm_report_advisor.render_report import render_markdown  # noqa: E402
from cgm_report_advisor.watch import run_watch  # noqa: E402

EXAMPLES = ROOT / "examples"
WATCHLIST = ROOT / "knowledge-base" / "watchlist.json"

FICTIONAL_TEXT = """第1节 虚构加餐

每日可食半个虚构的青玻璃苹果。

第2节 没有份量

注意饮食多样化。

第3节 表格不要抽数

食物 | 克 | 次数
青玻璃苹果 | 300 | 2
"""

PORTION = "每日可食半个虚构的青玻璃苹果。"


def _metrics() -> ExtractedReport:
    data = json.loads((EXAMPLES / "fictional-report-metrics.json").read_text(encoding="utf-8"))
    return ExtractedReport.from_dict(data)


def _intake() -> IntakeRecord:
    data = json.loads((EXAMPLES / "fictional-intake.json").read_text(encoding="utf-8"))
    return IntakeRecord.from_dict(data)


def _pending_entry(kind: str, text: str, entry_id: str) -> KnowledgeEntry:
    return KnowledgeEntry(
        entry_id=entry_id,
        kind=kind,  # type: ignore[arg-type]
        locator="虚构草稿",
        text=text,
        portion_or_action=text,
        source_quote=text,
        review_status="pending_review",
    )


class PendingDraftAdviceTests(unittest.TestCase):
    def test_pending_drafts_stay_out_of_diet_and_activity_advice(self) -> None:
        source = KnowledgeSource(
            id="pending-read-source",
            title="已标成读过、但条目仍待审的虚构来源",
            year=2026,
            read_status="full_text_read",
            entries=(
                _pending_entry("diet", "每日可食一整筐虚构星果。", "pending-diet"),
                _pending_entry("activity", "每日步行虚构的 40 分钟。", "pending-activity"),
                _pending_entry("monitoring", "每餐后监测虚构的 1 次。", "pending-monitoring"),
            ),
        )
        knowledge = KnowledgeBase([source])
        result = analyze([_metrics()], _intake(), knowledge)
        self.assertTrue(result.lifestyle_advice_allowed)
        self.assertFalse(has_lifestyle_prescriptions(result))
        self.assertFalse(knowledge.usable_entries())
        markdown = render_markdown(result, [_metrics()], _intake())
        self.assertNotIn("虚构星果", markdown)
        self.assertNotIn("40 分钟", markdown)
        self.assertNotIn("每餐后监测", markdown)
        self.assertFalse(any(item.category == "monitoring" for item in result.advice))

    def test_unread_source_stays_unusable_when_drafts_exist(self) -> None:
        source = KnowledgeSource(
            id="unread-with-drafts",
            title="未读但夹带草稿的虚构来源",
            year=2024,
            read_status="unread",
            entries=(
                KnowledgeEntry(
                    entry_id="unread-accepted-looking",
                    kind="activity",
                    locator="虚构",
                    text="每日步行虚构的 99 分钟。",
                    portion_or_action="每日步行虚构的 99 分钟。",
                    source_quote="每日步行虚构的 99 分钟。",
                    review_status="accepted",
                ),
            ),
        )
        knowledge = KnowledgeBase([source])
        self.assertEqual(knowledge.usable_entries(), [])
        self.assertEqual(knowledge.usable_sources(), [])
        result = analyze([_metrics()], _intake(), knowledge)
        markdown = render_markdown(result, [_metrics()], _intake())
        self.assertNotIn("99 分钟", markdown)
        self.assertFalse(has_lifestyle_prescriptions(result))

    def test_pipeline_does_not_read_a_draft_file_beside_the_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            source_file = root / "fiction.txt"
            source_file.write_text(FICTIONAL_TEXT, encoding="utf-8")
            draft_from_file(
                source_file,
                source_id="fiction-glass-apple",
                title="虚构青玻璃苹果说明",
                drafts_dir=drafts,
                extracted_dir=root / "extracted",
            )
            result = run_pipeline(
                metrics_paths=[EXAMPLES / "fictional-report-metrics.json"],
                knowledge_path=ROOT / "knowledge-base" / "sources.example.json",
                intake_path=EXAMPLES / "fictional-intake.json",
            )
        self.assertNotIn("青玻璃苹果", result.markdown)
        self.assertIn("每日可食半个中等大小的苹果", result.markdown)


class IngestPortionTests(unittest.TestCase):
    def test_explicit_portion_is_verbatim_and_plain_text_invents_nothing(self) -> None:
        draft = draft_from_text(
            FICTIONAL_TEXT,
            source_id="fiction-glass-apple",
            title="虚构青玻璃苹果说明",
            year=2026,
            series_id="demo-series",
        )
        self.assertEqual(draft["review_status"], "pending_review")
        self.assertEqual(draft["source"]["read_status"], "unread")
        self.assertEqual(len(draft["entries"]), 1)
        entry = draft["entries"][0]
        self.assertEqual(entry["portion_or_action"], PORTION)
        self.assertEqual(entry["source_quote"], PORTION)
        self.assertIn(entry["portion_or_action"], FICTIONAL_TEXT)
        self.assertEqual(entry["review_status"], "pending_review")
        self.assertEqual(entry["kind"], "diet")
        self.assertTrue(entry["locator"])
        for skipped in draft["not_drafted"]:
            self.assertIsNone(skipped.get("portion_or_action"))
        self.assertTrue(any("注意饮食多样化" in item["text"] for item in draft["not_drafted"]))
        self.assertNotIn("300", json.dumps(draft["entries"], ensure_ascii=False))

        empty = draft_from_text(
            "注意饮食多样化。",
            source_id="no-portion",
            title="没有份量的虚构段落",
        )
        self.assertEqual(empty["entries"], [])
        self.assertTrue(empty["not_drafted"])

    def test_accept_is_required_before_entries_are_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_file = root / "fiction.txt"
            source_file.write_text(PORTION + "\n", encoding="utf-8")
            draft_path = draft_from_file(
                source_file,
                source_id="fiction-glass-apple",
                title="虚构青玻璃苹果说明",
                drafts_dir=root / "drafts",
                extracted_dir=root / "extracted",
                year=2026,
                series_id="demo-series",
            )
            index_path = root / "sources.json"
            index_path.write_text('{"sources": []}\n', encoding="utf-8")
            before = KnowledgeBase.from_json_path(index_path)
            self.assertEqual(before.usable_entries(), [])
            blocked = analyze([_metrics()], _intake(), before)
            self.assertNotIn("青玻璃", render_markdown(blocked, [_metrics()], _intake()))

            loaded = json.loads(draft_path.read_text(encoding="utf-8"))
            pending_source = KnowledgeSource(
                id="fiction-glass-apple",
                title="虚构青玻璃苹果说明",
                year=2026,
                read_status="full_text_read",
                series_id="demo-series",
                entries=tuple(
                    KnowledgeEntry(
                        entry_id=item["entry_id"],
                        kind=item["kind"],
                        locator=item["locator"],
                        text=item["text"],
                        portion_or_action=item["portion_or_action"],
                        source_quote=item["source_quote"],
                        review_status=item["review_status"],
                    )
                    for item in loaded["entries"]
                ),
            )
            still_pending = analyze([_metrics()], _intake(), KnowledgeBase([pending_source]))
            self.assertFalse(has_lifestyle_prescriptions(still_pending))

            accept_draft(
                draft_path,
                index_path,
                read_status="selected_sections_read",
                entry_ids=["fiction-glass-apple-001"],
            )
            accepted = KnowledgeBase.from_json_path(index_path)
            usable = accepted.usable_entries(("diet",))
            self.assertEqual(len(usable), 1)
            self.assertEqual(usable[0][1].portion_or_action, PORTION)
            self.assertEqual(usable[0][1].review_status, "accepted")
            self.assertEqual(usable[0][0].read_status, "selected_sections_read")
            allowed = analyze([_metrics()], _intake(), accepted)
            self.assertIn(PORTION, render_markdown(allowed, [_metrics()], _intake()))

    def test_accepting_a_newer_version_supersedes_the_older_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "sources.json"
            index_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "id": "demo-2024",
                                "title": "虚构系列旧版",
                                "year": 2024,
                                "series_id": "demo-series",
                                "read_status": "full_text_read",
                                "entries": [
                                    {
                                        "entry_id": "old-fruit",
                                        "kind": "diet",
                                        "locator": "旧版",
                                        "text": "每日可食一颗虚构红珠果。",
                                        "portion_or_action": "每日可食一颗虚构红珠果。",
                                        "review_status": "accepted",
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source_file = root / "newer.txt"
            source_file.write_text(PORTION + "\n", encoding="utf-8")
            draft_path = draft_from_file(
                source_file,
                source_id="demo-2026",
                title="虚构系列新版",
                drafts_dir=root / "drafts",
                extracted_dir=None,
                year=2026,
                series_id="demo-series",
            )
            result = accept_draft(
                draft_path,
                index_path,
                read_status="full_text_read",
                accept_all=True,
            )
            self.assertIn("demo-2024", result["superseded_source_ids"])
            knowledge = KnowledgeBase.from_json_path(index_path)
            usable_text = " ".join(entry.text for _source, entry in knowledge.usable_entries())
            self.assertIn(PORTION, usable_text)
            self.assertNotIn("红珠果", usable_text)
            self.assertTrue(any(source.superseded for source in knowledge.sources))
            rendered = render_markdown(analyze([_metrics()], _intake(), knowledge), [_metrics()], _intake())
            self.assertNotIn("红珠果", rendered)
            self.assertIn("青玻璃苹果", rendered)

    def test_pdf_bytes_are_not_written_into_the_repo(self) -> None:
        before = {path.relative_to(ROOT) for path in ROOT.rglob("*.pdf")}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "not-a-guideline.pdf"
            pdf_path.write_bytes(b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
            drafts = root / "drafts"
            try:
                draft_from_file(
                    pdf_path,
                    source_id="not-a-guideline",
                    title="不是指南的空文件",
                    drafts_dir=drafts,
                    extracted_dir=root / "extracted",
                )
            except Exception:
                pass
            written = [path for path in drafts.rglob("*") if path.suffix.lower() == ".pdf"] if drafts.exists() else []
            self.assertEqual(written, [])
            extracted_pdfs = list((root / "extracted").rglob("*.pdf")) if (root / "extracted").exists() else []
            self.assertEqual(extracted_pdfs, [])
        after = {path.relative_to(ROOT) for path in ROOT.rglob("*.pdf")}
        self.assertEqual(before, after)


class WatchFixtureTests(unittest.TestCase):
    def _write_watch_inputs(self, root: Path, check_year: int) -> tuple[Path, Path, Path]:
        watchlist = root / "watchlist.json"
        watchlist.write_text(
            json.dumps(
                {
                    "series": [
                        {
                            "series_id": "demo-series",
                            "title": "虚构系列指南",
                            "publisher_or_society": "虚构学会",
                            "suggested_query": "虚构系列指南",
                            "last_seen": {"year": 2024, "version_label": "2024"},
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        index = root / "sources.json"
        index.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "local-2024",
                            "title": "虚构系列指南",
                            "year": 2024,
                            "series_id": "demo-series",
                            "read_status": "unread",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fixture = root / "fixture.json"
        fixture.write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "series_id": "demo-series",
                            "year": check_year,
                            "version_label": str(check_year),
                            "obtain_from": "https://example.invalid/official-notice",
                            "source_label": "fixture",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return watchlist, index, fixture

    def test_fixture_reports_a_newer_year_and_writes_no_pdf(self) -> None:
        before = {path.relative_to(ROOT) for path in ROOT.rglob("*.pdf")}
        with tempfile.TemporaryDirectory() as tmp:
            watchlist, index, fixture = self._write_watch_inputs(Path(tmp), 2026)
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
                report = run_watch(watchlist, index_path=index, fixture_path=fixture)
        self.assertIn("可能有更新", report)
        self.assertIn("2024", report)
        self.assertIn("2026", report)
        self.assertIn("https://example.invalid/official-notice", report)
        self.assertNotIn(".pdf", report.lower())
        after = {path.relative_to(ROOT) for path in ROOT.rglob("*.pdf")}
        self.assertEqual(before, after)

    def test_same_year_says_nothing_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            watchlist, index, fixture = self._write_watch_inputs(Path(tmp), 2024)
            report = run_watch(watchlist, index_path=index, fixture_path=fixture)
        self.assertIn("未发现比本地索引更新的版本", report)
        self.assertNotIn("可能有更新", report)

    def test_failed_live_lookup_does_not_invent_an_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            watchlist, index, _fixture = self._write_watch_inputs(Path(tmp), 2026)

            def unavailable(_series):
                raise OSError("offline")

            report = run_watch(watchlist, index_path=index, live=True, lookup=unavailable)
        self.assertIn("未臆造", report)
        self.assertIn("未发现比本地索引更新的版本", report)
        self.assertNotIn("2026", report)
        self.assertNotIn("可能有更新", report)

    def test_public_watchlist_is_bibliographic_metadata_only(self) -> None:
        raw = WATCHLIST.read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(data["as_of"], "2026-11-26")
        titles = {item["title"] for item in data["series"]}
        for expected in (
            "中国2型糖尿病防治指南",
            "中国持续葡萄糖监测临床应用指南",
            "持续葡萄糖监测基层临床应用专家共识",
            "集成式持续葡萄糖监测（iCGM）临床应用专家共识",
            "中国2型糖尿病运动治疗指南",
            "国家基层糖尿病防治管理指南",
            "中国老年2型糖尿病防治临床指南",
            "中国1型糖尿病诊治指南",
            "中国居民膳食指南",
            "Standards of Care in Diabetes",
            "International Consensus on Time in Range",
        ):
            self.assertIn(expected, titles)
        lowered = raw.lower()
        self.assertNotIn(".pdf", lowered)
        self.assertNotIn("weixin", lowered)
        self.assertNotIn("sciconf", lowered)
        self.assertNotIn("摘要", raw)

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)

        for text in strings(data):
            self.assertLess(len(text), 500)
        loaded = run_watch(WATCHLIST)
        self.assertIn("未发现比本地索引更新的版本", loaded)
        self.assertIn("未进行在线或夹具核对", loaded)


if __name__ == "__main__":
    unittest.main()
