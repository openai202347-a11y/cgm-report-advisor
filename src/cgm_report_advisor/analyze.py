"""Interpret extracted metrics and attach only knowledge-base-backed advice.

Interpretation order is fixed:

1. Data quality, using whatever the report actually stated. Comparison with
   a completeness target is allowed only when a read knowledge-base source
   supplies that target.
2. Hypoglycaemia, including time below range and any level-2 events defined
   by the knowledge base. A single level-2 event should prompt contacting a
   clinician promptly. Vendor "hypoglycaemia risk" gauges are not treated as
   high risk when the knowledge base does not support them.
3. Time in, above, and below range, plus coefficient of variation, with
   targets taken only from read sources and with the applicable population
   stated. Conflicting frameworks are listed side by side.

Diet and activity prescriptions are omitted when required intake is missing,
or when the caller asked for a metrics-only reading.
"""

from __future__ import annotations

from typing import Optional

from .intake import missing_intake_items
from .knowledge import KnowledgeBase
from .models import (
    AdviceItem,
    AnalysisResult,
    ExtractedReport,
    IntakeRecord,
    InterpretationSection,
    KnowledgeEntry,
    KnowledgeSource,
    Metric,
    MissingIntakeItem,
)


def analyze(
    reports: list[ExtractedReport],
    intake: Optional[IntakeRecord],
    knowledge: KnowledgeBase,
    *,
    metrics_only: bool = False,
) -> AnalysisResult:
    conflict = wearer_conflict_message(reports, intake)
    if conflict:
        return AnalysisResult(
            metrics_only=metrics_only,
            lifestyle_advice_allowed=False,
            missing_intake=[],
            sections=[],
            advice=[],
            stop_reason=conflict,
            wearer_conflict=conflict,
        )

    missing = missing_intake_items(knowledge, intake)
    lifestyle_allowed = (not metrics_only) and (not missing)
    sections = _build_sections(reports, knowledge)
    advice: list[AdviceItem] = []
    if lifestyle_allowed:
        advice.extend(_advice_from_knowledge(knowledge, kinds=("diet", "activity")))
    if not metrics_only:
        advice.extend(_advice_from_knowledge(knowledge, kinds=("monitoring", "referral")))
        advice.extend(_level2_referral(reports, knowledge))

    stop_reason = None
    if metrics_only:
        stop_reason = "本次仅做指标解读，不输出饮食或运动处方。"
    elif missing:
        stop_reason = "仍缺知识库要求的临床资料，因此不输出饮食或运动处方。"

    return AnalysisResult(
        metrics_only=metrics_only,
        lifestyle_advice_allowed=lifestyle_allowed,
        missing_intake=missing,
        sections=sections,
        advice=advice,
        stop_reason=stop_reason,
    )


def wearer_conflict_message(
    reports: list[ExtractedReport],
    intake: Optional[IntakeRecord],
) -> Optional[str]:
    """Refuse to merge reports or intake when wearers are not confirmed identical."""
    keys = [report.wearer_key for report in reports if report.wearer_key]
    unique = set(keys)
    if len(unique) > 1:
        confirmed = all(report.same_wearer_confirmed for report in reports)
        if not confirmed:
            return (
                "同一批报告带有不同的佩戴者区分号，且尚未确认属于同一人。"
                "请分开分析，不要把用药和病史混套。"
            )
    if intake and intake.wearer_key and unique:
        if intake.wearer_key not in unique:
            return (
                "提供的用药或病史资料与报告中的佩戴者区分号不一致，"
                "不能默认属于同一人，用药和病史不可混套。"
            )
    return None


def _build_sections(reports: list[ExtractedReport], knowledge: KnowledgeBase) -> list[InterpretationSection]:
    sections = [
        InterpretationSection("数据质量", _quality_paragraphs(reports, knowledge)),
        InterpretationSection("低血糖", _hypo_paragraphs(reports, knowledge)),
        InterpretationSection("目标范围内时间、高于目标时间和变异系数", _tir_paragraphs(reports, knowledge)),
        InterpretationSection("其他报告指标与分时说明", _other_paragraphs(reports)),
    ]
    unread = knowledge.unused_because_unread()
    if unread:
        names = "、".join(source.title for source in unread)
        sections.append(
            InterpretationSection(
                "未使用的知识库来源",
                [f"下列来源的阅读状态为未读，本次没有当作已掌握，也没有用来确定目标或建议：{names}。"],
            )
        )
    return sections


def _quality_paragraphs(reports: list[ExtractedReport], knowledge: KnowledgeBase) -> list[str]:
    paragraphs: list[str] = []
    for index, report in enumerate(reports, start=1):
        prefix = f"报告 {index}：" if len(reports) > 1 else ""
        period = _period(report)
        coverage = report.coverage.display() if report.coverage else "（报告未写出覆盖率）"
        days = report.wear_days_stated or "（报告未写出有效天数）"
        paragraphs.append(
            f"{prefix}监测时段为 {period}。报告写明的有效天数为 {days}，"
            f"覆盖率或完整程度为 {coverage}。"
        )
        if report.data_quality_note:
            paragraphs.append(f"{prefix}报告对数据质量的说明：{report.data_quality_note}")
        if report.reference_only or report.disclaimer_text:
            text = report.disclaimer_text or "报告标明仅供测试或参考。"
            paragraphs.append(f"{prefix}须如实说明：{text}")
    targets = _target_sentences(knowledge, kind="target", topic_hints=("质量", "覆盖", "有效数据", "14", "70"))
    if targets:
        paragraphs.extend(targets)
        if len(targets) > 1:
            paragraphs.append("以上质量标准来自不同来源时已并列写出，没有折中成一条新的标准。")
    else:
        paragraphs.append(
            "当前已阅读的知识库条目中，没有可供引用的数据质量标准（例如建议监测天数或有效数据比例）。"
            "因此这里只转述报告原文，不另行判断“是否足够”，也不套用未写入知识库的常用数字。"
        )
    return paragraphs


def _hypo_paragraphs(reports: list[ExtractedReport], knowledge: KnowledgeBase) -> list[str]:
    paragraphs: list[str] = []
    for index, report in enumerate(reports, start=1):
        prefix = f"报告 {index}：" if len(reports) > 1 else ""
        tbr = [band for band in report.bands if (band.label or "").upper() == "TBR" or _looks_below_range(band.label)]
        if tbr:
            for band in tbr:
                paragraphs.append(f"{prefix}低于目标范围的时间（按报告分层 { _band_text(band) }）。")
        else:
            paragraphs.append(f"{prefix}报告未单独写出低于目标范围的时间占比。")
        if report.glucose_min:
            paragraphs.append(f"{prefix}报告写出的最低葡萄糖为 {report.glucose_min.display()}。")
        else:
            paragraphs.append(f"{prefix}报告未写出最低葡萄糖。")
        if report.very_low_stated:
            paragraphs.append(f"{prefix}报告对更低切点的数值或次数为 {report.very_low_stated.display()}。")
        else:
            paragraphs.append(
                f"{prefix}报告未写出更低切点（例如部分共识中的 2 级低血糖阈值）的数值或次数；"
                "该字段保持为空，不记成 0，也不写成未发生。"
            )
        if report.hypoglycemia_events:
            paragraphs.append(f"{prefix}报告列出的低血糖相关片段共 {len(report.hypoglycemia_events)} 条，仅按原文理解，不补充未写出的时刻。")
        for gauge in report.software_gauges:
            name = gauge.name or "未命名仪表"
            reading = gauge.reading or "（未写出读数）"
            paragraphs.append(
                f"{prefix}报告软件另有“{name}”读数：{reading}。"
                "这不是知识库中的分层指标。若已阅读的来源并未支持把该读数当作风险等级，"
                "或该读数与低于目标时间明显不符，则不把它说成低血糖风险高。"
            )
    if not _knowledge_supports_software_gauges(knowledge):
        paragraphs.append("本次已阅读的知识库条目未对软件自带的低血糖风险仪表给出解释规则，因此不根据该仪表下结论。")
    targets = _target_sentences(knowledge, kind="target", topic_hints=("低血糖", "低于", "TBR", "3.0", "54"))
    if targets:
        paragraphs.extend(targets)
    return paragraphs


def _tir_paragraphs(reports: list[ExtractedReport], knowledge: KnowledgeBase) -> list[str]:
    paragraphs: list[str] = []
    for index, report in enumerate(reports, start=1):
        prefix = f"报告 {index}：" if len(reports) > 1 else ""
        if report.bands:
            lines = "；".join(_band_text(band) for band in report.bands)
            paragraphs.append(f"{prefix}报告中的时间占比分层为：{lines}。分层切点保留报告原文，没有改写成其他共识中的区间。")
        else:
            paragraphs.append(f"{prefix}报告未写出 TIR / TAR / TBR 分层。")
        if report.cv:
            paragraphs.append(f"{prefix}变异系数为 {report.cv.display()}。")
        else:
            paragraphs.append(f"{prefix}报告未写出变异系数。")
    targets = _target_sentences(knowledge, kind="target", topic_hints=("TIR", "TAR", "CV", "目标范围内", "变异"))
    if targets:
        paragraphs.extend(targets)
        if len([item for item in targets]) > 1:
            paragraphs.append("同一指标若有不同来源的目标，已并列写出来源和适用人群，没有自行合并。")
    else:
        paragraphs.append(
            "当前已阅读的知识库条目中没有可引用的 TIR / TAR / CV 目标值，因此不把报告数字说成达标或未达标。"
        )
    return paragraphs


def _other_paragraphs(reports: list[ExtractedReport]) -> list[str]:
    paragraphs: list[str] = []
    for index, report in enumerate(reports, start=1):
        prefix = f"报告 {index}：" if len(reports) > 1 else ""
        extras: list[str] = []
        if report.mean_glucose:
            extras.append(f"平均葡萄糖 {report.mean_glucose.display()}")
        if report.sd:
            extras.append(f"标准差 {report.sd.display()}")
        if report.e_hba1c_or_gmi:
            extras.append(report.e_hba1c_or_gmi.display())
        if report.glucose_max:
            extras.append(f"最高葡萄糖 {report.glucose_max.display()}")
        if extras:
            paragraphs.append(f"{prefix}报告还写出了：{'；'.join(extras)}。其中估算糖化血红蛋白或 GMI 不能当成化验室测定结果。")
        if report.time_of_day_patterns:
            joined = "；".join(report.time_of_day_patterns)
            paragraphs.append(
                f"{prefix}分时说明按原文转述如下：{joined}。"
                "在没有用餐或运动记录时，不把某一时段的波动写成某一种具体食物或某一次运动引起。"
            )
        elif not extras:
            paragraphs.append(f"{prefix}报告未额外写出平均值、极值或分时说明。")
    return paragraphs


def _advice_from_knowledge(
    knowledge: KnowledgeBase,
    kinds: tuple[str, ...],
) -> list[AdviceItem]:
    items: list[AdviceItem] = []
    for source, entry in knowledge.usable_entries(kinds):
        items.append(_item_from_entry(source, entry))
    return items


def _level2_referral(reports: list[ExtractedReport], knowledge: KnowledgeBase) -> list[AdviceItem]:
    """If a read source defines a level-2 threshold and a report meets it, ask to contact a clinician."""
    definitions = [
        (source, entry)
        for source, entry in knowledge.usable_entries()
        if entry.level2_hypoglycemia_threshold
    ]
    if not definitions:
        return []
    triggered: list[AdviceItem] = []
    for report in reports:
        printed = _joined_low_values(report)
        for source, entry in definitions:
            # The skeleton does not parse or convert units itself. It only
            # flags the situation when the report printed the same threshold
            # string, or when very_low_stated is present alongside a definition.
            threshold = entry.level2_hypoglycemia_threshold or ""
            if report.very_low_stated or (threshold and threshold in printed):
                text = (
                    f"已阅读的来源将 2 级低血糖相关切点写作“{threshold}”。"
                    "即便只出现一次，也应尽快联系医生，不要自行调整处方药物剂量。"
                )
                triggered.append(_item_from_entry(source, entry, text_override=text, category="referral"))
    # Deduplicate by source + locator
    unique: list[AdviceItem] = []
    seen: set[tuple[str, Optional[str]]] = set()
    for item in triggered:
        key = (item.source_id, item.locator)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _item_from_entry(
    source: KnowledgeSource,
    entry: KnowledgeEntry,
    *,
    text_override: Optional[str] = None,
    category: Optional[str] = None,
) -> AdviceItem:
    return AdviceItem(
        category=category or entry.kind,
        text=text_override or entry.text,
        source_id=source.id,
        source_title=source.title,
        source_version=source.version,
        source_year=source.year,
        locator=entry.locator,
        portion_or_action=entry.portion_or_action if text_override is None else None,
    )


def _target_sentences(knowledge: KnowledgeBase, *, kind: str, topic_hints: tuple[str, ...]) -> list[str]:
    sentences: list[str] = []
    for source, entry in knowledge.usable_entries((kind,)):
        haystack = f"{entry.text} {entry.locator or ''} {entry.applies_to or ''}"
        if topic_hints and not any(hint.lower() in haystack.lower() for hint in topic_hints):
            # Still include generic target entries that do not mention a topic?
            # Safer to include only entries that appear related, so we do not
            # paste unrelated curated sentences into the wrong section.
            continue
        population = entry.applies_to or source.applies_to or "（来源未在条目中写明适用人群）"
        sentences.append(
            f"来源《{source.title}》{source.year or ''} {entry.locator or ''}："
            f"{entry.text} 适用人群：{population}。"
        )
    return sentences


def _knowledge_supports_software_gauges(knowledge: KnowledgeBase) -> bool:
    needles = ("软件仪表", "风险仪表", "低血糖风险仪表")
    for _source, entry in knowledge.usable_entries():
        text = f"{entry.text} {entry.locator or ''}"
        if any(needle in text for needle in needles):
            return True
    return False


def _period(report: ExtractedReport) -> str:
    if report.wear_start and report.wear_end:
        return f"{report.wear_start} 至 {report.wear_end}"
    if report.wear_start or report.wear_end:
        return report.wear_start or report.wear_end or "（报告未写出）"
    return "（报告未写出起止日期）"


def _band_text(band) -> str:
    span = "–".join(part for part in (band.range_low, band.range_high) if part)
    unit = f" {band.unit}" if band.unit else ""
    percent = f"{band.percent}%" if band.percent and not str(band.percent).endswith("%") else (band.percent or "（未写出占比）")
    label = band.label or "未命名分层"
    duration = f"，时长 {band.duration}" if band.duration else ""
    return f"{label}（{span}{unit}）占 {percent}{duration}"


def _looks_below_range(label: Optional[str]) -> bool:
    if not label:
        return False
    return "低于" in label or "低值" in label


def _joined_low_values(report: ExtractedReport) -> str:
    parts: list[str] = []
    for metric in (report.glucose_min, report.very_low_stated):
        if metric:
            parts.append(metric.display())
    return " ".join(parts)


def has_lifestyle_prescriptions(result: AnalysisResult) -> bool:
    return any(item.category in {"diet", "activity"} for item in result.advice)


def has_missing_intake(missing: list[MissingIntakeItem]) -> bool:
    return bool(missing)
