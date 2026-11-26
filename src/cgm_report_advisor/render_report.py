"""Render a patient-facing Markdown draft from an analysis result.

The draft is auxiliary advice, not a formal clinical opinion and not a
medical device. It must restated a report's "for reference only" notice when
present, must not include telephone numbers or other identity fields, and
must not recommend changing prescription drug doses.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import AnalysisResult, ExtractedReport, IntakeRecord, MissingIntakeItem

DISCLAIMER = (
    "本文是辅助建议，不是正式诊疗意见，也不是医疗器械，不能替代执业医师的面对面判断。"
    "不建议根据本文自行调整处方药物剂量；如需改剂量、停药或加药，请咨询医生。"
)

# Identity patterns that must not appear in patient-facing text.
# Keep this narrow: dates such as 2024-01-03 and glucose ranges must not be flagged.
MASKED_PHONE = re.compile(r"\d{2,4}\*{2,}\d{2,}")
LABELED_PHONE = re.compile(r"(?:电话|手机|联系方式|Tel(?:ephone)?|Phone|Mobile)\s*[:：]?\s*\+?\d", re.IGNORECASE)
CN_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def render_markdown(
    result: AnalysisResult,
    reports: list[ExtractedReport],
    intake: Optional[IntakeRecord],
) -> str:
    parts: list[str] = ["# 动态血糖报告的饮食与运动建议草稿", ""]
    if any(report.fictional for report in reports) or (intake is not None and intake.fictional):
        parts.extend(["**本组输入标明为虚构示例，不对应任何真实患者或真实监测报告。**", ""])

    label = intake.display_label if intake and intake.display_label else None
    if label:
        parts.append(f"阅读对象：{label}")
        parts.append("")

    parts.extend(["## 声明", "", DISCLAIMER, ""])
    for report in reports:
        if report.reference_only or report.disclaimer_text:
            text = report.disclaimer_text or "原报告标明仅供测试或参考。"
            parts.append(f"原报告声明：{text}")
            parts.append("")

    if result.wearer_conflict:
        parts.extend(["## 无法继续合并分析", "", result.wearer_conflict, ""])
        return _sanitize("\n".join(parts).rstrip() + "\n")

    for section in result.sections:
        parts.extend([f"## {section.title}", ""])
        parts.extend(section.paragraphs)
        parts.append("")

    if result.missing_intake:
        parts.extend(["## 仍缺的资料", "", _missing_block(result.missing_intake), ""])

    if result.stop_reason:
        parts.extend(["## 本次输出范围", "", result.stop_reason, ""])

    lifestyle = [item for item in result.advice if item.category in {"diet", "activity"}]
    other = [item for item in result.advice if item.category not in {"diet", "activity"}]

    if lifestyle:
        parts.extend(["## 饮食与运动建议", ""])
        parts.extend(_advice_blocks(lifestyle))
    elif not result.lifestyle_advice_allowed:
        parts.extend(
            [
                "## 饮食与运动建议",
                "",
                "本次不输出饮食或运动处方。原因见上文的输出范围或资料缺口。",
                "",
            ]
        )

    if other:
        parts.extend(["## 监测与就医提醒", ""])
        parts.extend(_advice_blocks(other))

    if intake and intake.medications:
        parts.extend(["## 用药记录（按使用者提供的原名，未补充未给出的剂量或时点）", ""])
        for med in intake.medications:
            dose = med.dose_as_provided or "（未提供剂量，不猜测）"
            schedule = med.schedule_as_provided or "（未提供服药或注射时间，不猜测）"
            parts.append(f"- {med.name_as_provided or '（未提供名称）'}，{dose}，{schedule}")
        parts.append("")
        parts.append("以上只是使用者提供的记录，不是要求患者改药的建议。")
        parts.append("")

    parts.extend(["## 再次说明", "", DISCLAIMER, ""])
    return _sanitize("\n".join(parts).rstrip() + "\n")


def _advice_blocks(items) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.append(f"- {item.text}")
        lines.append(f"  来源：{item.source_line()}")
        if item.illustration and item.illustration.allowed:
            lines.append(f"  示意图说明（仅图解知识库原文）：{item.illustration.caption}")
        elif item.illustration and item.illustration.refusal_reason:
            lines.append(f"  本条不配图：{item.illustration.refusal_reason}")
        lines.append("")
    return lines


def _missing_block(missing: list[MissingIntakeItem]) -> str:
    lines = ["对照已阅读的知识库来源，下列项目仍空着。已经提供的没有再列出。", ""]
    for index, item in enumerate(missing, start=1):
        sources = "、".join(item.requested_by)
        lines.append(f"{index}. {item.label}（依据来源：{sources}）")
    return "\n".join(lines)


def _sanitize(text: str) -> str:
    if MASKED_PHONE.search(text) or LABELED_PHONE.search(text) or CN_MOBILE.search(text):
        raise ValueError(
            "渲染结果中出现了类似电话号码的内容。对外文稿不得写出报告里的掩码电话等身份信息，已中止输出。"
        )
    return text
