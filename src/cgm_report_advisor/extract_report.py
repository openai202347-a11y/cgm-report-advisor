"""Report extraction interfaces.

This project does not ship a complete parser for every vendor's CGM PDF.
Values must be copied from the report text or from a structured file that a
person (or a separately written extractor) has already checked. Missing
values stay missing. Do not invent, interpolate, or unit-convert over the
original figures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import ExtractedReport


class ReportExtractor(Protocol):
    def extract(self, path: Path) -> ExtractedReport:
        """Return only figures that appear in the source at *path*."""


class StructuredMetricsLoader:
    """Load metrics already transcribed into the schema in docs/report-schema.md."""

    def extract(self, path: Path) -> ExtractedReport:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a JSON object")
        return ExtractedReport.from_dict(data)


class PdfReportExtractor:
    """Placeholder for a future, vendor-specific PDF extractor.

    Implementing this class (or a subclass) still requires the same rule:
    if a number, unit, event, or disclaimer is not printed on the report,
    the corresponding field must be left empty. Do not fill gaps with
    typical cut-points or values from another report.
    """

    def extract(self, path: Path) -> ExtractedReport:
        raise NotImplementedError(
            "本骨架不提供各厂商 CGM PDF 的完整解析器。"
            f" 请把报告中已经写出的指标按 docs/report-schema.md 整理成 JSON，"
            f" 再使用 StructuredMetricsLoader 读取。当前文件：{path}"
        )


def load_report(path: Path) -> ExtractedReport:
    """Dispatch on file suffix. PDFs are rejected until a vendor extractor exists."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return StructuredMetricsLoader().extract(path)
    if suffix == ".pdf":
        return PdfReportExtractor().extract(path)
    raise ValueError(
        f"不支持的报告文件类型：{path.suffix}。第一版请提供符合 report-schema 的 JSON。"
    )
