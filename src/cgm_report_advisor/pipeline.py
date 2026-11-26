"""Run the end-to-end pipeline and stop at the intake checklist when required.

Typical order: load extracted metrics, refuse to merge unconfirmed wearers,
build the missing-intake list from the knowledge base, interpret metrics,
attach diet or activity advice only when intake is complete and the caller
did not request a metrics-only reading, then attach illustration requests
and render Markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from .analyze import analyze
from .extract_report import load_report
from .illustrate import attach_illustrations
from .intake import format_intake_questions
from .knowledge import KnowledgeBase
from .models import AnalysisResult, ExtractedReport, IntakeRecord
from .render_report import render_markdown

PathLike = Union[str, Path]


@dataclass
class PipelineResult:
    reports: list[ExtractedReport]
    intake: Optional[IntakeRecord]
    analysis: AnalysisResult
    markdown: str
    stopped_for_intake: bool
    intake_questions: Optional[str]


def run_pipeline(
    *,
    metrics_paths: Sequence[PathLike],
    knowledge_path: PathLike,
    intake_path: Optional[PathLike] = None,
    metrics_only: bool = False,
) -> PipelineResult:
    reports = [load_report(Path(path)) for path in metrics_paths]
    if not reports:
        raise ValueError("至少需要一份已整理的报告指标文件。")
    knowledge = KnowledgeBase.from_json_path(Path(knowledge_path))
    intake = None
    if intake_path is not None:
        intake = _load_intake(Path(intake_path))

    analysis = analyze(reports, intake, knowledge, metrics_only=metrics_only)
    stopped = bool(analysis.missing_intake) and not metrics_only and not analysis.wearer_conflict
    questions = format_intake_questions(analysis.missing_intake) if analysis.missing_intake else None

    if analysis.lifestyle_advice_allowed:
        attach_illustrations(analysis.advice)

    markdown = render_markdown(analysis, reports, intake)
    return PipelineResult(
        reports=reports,
        intake=intake,
        analysis=analysis,
        markdown=markdown,
        stopped_for_intake=stopped,
        intake_questions=questions,
    )


def _load_intake(path: Path) -> IntakeRecord:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return IntakeRecord.from_dict(data)
