"""Placeholder tests for the core safety rules of the first-version pipeline."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cgm_report_advisor.analyze import analyze, has_lifestyle_prescriptions  # noqa: E402
from cgm_report_advisor.illustrate import request_illustration, validate_custom_prompt  # noqa: E402
from cgm_report_advisor.knowledge import KnowledgeBase  # noqa: E402
from cgm_report_advisor.models import AdviceItem, ExtractedReport, IntakeRecord, InterpretationSection  # noqa: E402
from cgm_report_advisor.pipeline import run_pipeline  # noqa: E402
from cgm_report_advisor.render_report import render_markdown  # noqa: E402

EXAMPLES = ROOT / "examples"
KB = ROOT / "knowledge-base" / "sources.example.json"


def _load_metrics() -> ExtractedReport:
    data = json.loads((EXAMPLES / "fictional-report-metrics.json").read_text(encoding="utf-8"))
    return ExtractedReport.from_dict(data)


def _load_intake(name: str) -> IntakeRecord:
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return IntakeRecord.from_dict(data)


def _knowledge() -> KnowledgeBase:
    return KnowledgeBase.from_json_path(KB)


class MissingIntakeTests(unittest.TestCase):
    def test_incomplete_intake_does_not_emit_diet_or_activity_advice(self) -> None:
        result = analyze(
            [_load_metrics()],
            _load_intake("fictional-intake-incomplete.json"),
            _knowledge(),
            metrics_only=False,
        )
        self.assertTrue(result.missing_intake)
        field_names = {item.field_name for item in result.missing_intake}
        self.assertIn("meal_pattern", field_names)
        self.assertIn("activity_habit", field_names)
        self.assertFalse(result.lifestyle_advice_allowed)
        self.assertFalse(has_lifestyle_prescriptions(result))
        markdown = render_markdown(result, [_load_metrics()], _load_intake("fictional-intake-incomplete.json"))
        self.assertIn("不输出饮食或运动处方", markdown)
        self.assertNotIn("每日可食半个中等大小的苹果", markdown)
        self.assertNotIn("餐后进行约 20 分钟中等强度步行", markdown)

    def test_pipeline_stops_for_intake_questions(self) -> None:
        result = run_pipeline(
            metrics_paths=[EXAMPLES / "fictional-report-metrics.json"],
            knowledge_path=KB,
            intake_path=EXAMPLES / "fictional-intake-incomplete.json",
        )
        self.assertTrue(result.stopped_for_intake)
        self.assertIsNotNone(result.intake_questions)
        self.assertIn("用餐时间与大致内容", result.intake_questions or "")
        self.assertFalse(has_lifestyle_prescriptions(result.analysis))


class CompleteIntakeTests(unittest.TestCase):
    def test_complete_intake_can_quote_knowledge_base_entries(self) -> None:
        result = run_pipeline(
            metrics_paths=[EXAMPLES / "fictional-report-metrics.json"],
            knowledge_path=KB,
            intake_path=EXAMPLES / "fictional-intake.json",
        )
        self.assertFalse(result.stopped_for_intake)
        self.assertTrue(has_lifestyle_prescriptions(result.analysis))
        self.assertIn("每日可食半个中等大小的苹果", result.markdown)
        self.assertIn("示例饮食份量说明（虚构）", result.markdown)
        self.assertIn("示意图说明", result.markdown)
        self.assertIn("本报告仅供测试参考", result.markdown)
        self.assertIn("不是正式诊疗意见", result.markdown)
        self.assertIn("不是医疗器械", result.markdown)

    def test_metrics_only_skips_lifestyle_even_when_intake_is_complete(self) -> None:
        result = run_pipeline(
            metrics_paths=[EXAMPLES / "fictional-report-metrics.json"],
            knowledge_path=KB,
            intake_path=EXAMPLES / "fictional-intake.json",
            metrics_only=True,
        )
        self.assertFalse(result.stopped_for_intake)
        self.assertFalse(has_lifestyle_prescriptions(result.analysis))
        self.assertIn("仅做指标解读", result.markdown)


class NoInventedPortionTests(unittest.TestCase):
    def test_advice_without_portion_cannot_be_illustrated(self) -> None:
        item = AdviceItem(
            category="diet",
            text="增加蔬菜摄入。",
            source_id="ex-2020-diet",
            source_title="示例饮食份量说明（虚构）",
            source_version="第 1 版",
            source_year=2020,
            locator="未写份量的原则句",
            portion_or_action=None,
        )
        request = request_illustration(item)
        self.assertFalse(request.allowed)
        self.assertIn("不能为了配图而编造", request.refusal_reason or "")

    def test_custom_prompt_cannot_add_extra_food(self) -> None:
        request = validate_custom_prompt(
            "每日半个中等大小的苹果",
            "画每日半个中等大小的苹果，再摆两颗草莓让构图更丰满，最好配上一整盘水果。",
        )
        self.assertFalse(request.allowed)
        self.assertIn("知识库未写明的元素", request.refusal_reason or "")

    def test_good_versus_bad_fruit_chart_is_rejected(self) -> None:
        request = validate_custom_prompt(
            "每日半个中等大小的苹果",
            "围绕每日半个中等大小的苹果画一张好水果和坏水果分类图。",
        )
        self.assertFalse(request.allowed)


class KnowledgeAndSafetyTests(unittest.TestCase):
    def test_unread_sources_are_not_usable(self) -> None:
        knowledge = _knowledge()
        unread_ids = {source.id for source in knowledge.unused_because_unread()}
        self.assertIn("ex-unread-placeholder", unread_ids)
        usable_ids = {source.id for source in knowledge.usable_sources()}
        self.assertNotIn("ex-unread-placeholder", usable_ids)

    def test_software_gauge_is_not_treated_as_high_risk(self) -> None:
        result = analyze([_load_metrics()], _load_intake("fictional-intake.json"), _knowledge())
        hypo = next(section for section in result.sections if section.title == "低血糖")
        joined = "\n".join(hypo.paragraphs)
        self.assertIn("低血糖风险", joined)
        self.assertIn("不把它说成低血糖风险高", joined)
        self.assertNotIn("因此低血糖风险高", joined)

    def test_wearer_mismatch_is_not_merged(self) -> None:
        intake = _load_intake("fictional-intake.json")
        intake.wearer_key = "fictional-wearer-B"
        result = analyze([_load_metrics()], intake, _knowledge())
        self.assertIsNotNone(result.wearer_conflict)
        self.assertFalse(has_lifestyle_prescriptions(result))
        markdown = render_markdown(result, [_load_metrics()], intake)
        self.assertIn("不可混套", markdown)

    def test_pdf_extractor_is_not_pretend_complete(self) -> None:
        from cgm_report_advisor.extract_report import load_report

        with self.assertRaises(NotImplementedError):
            load_report(Path("/tmp/fictional-demo-report.pdf"))

    def test_masked_phone_is_rejected_in_patient_facing_text(self) -> None:
        result = analyze([_load_metrics()], _load_intake("fictional-intake.json"), _knowledge())
        result.sections.append(InterpretationSection("测试", ["请勿在文稿中写掩码电话 138****1234。"]))
        with self.assertRaises(ValueError):
            render_markdown(result, [_load_metrics()], _load_intake("fictional-intake.json"))


if __name__ == "__main__":
    unittest.main()
