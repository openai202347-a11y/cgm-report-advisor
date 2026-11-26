"""Shared data structures for extracted reports, intake, and advice.

Values that did not appear in the source report or in the user-supplied
intake must remain empty. Do not back-fill typical units, cut-points, doses,
or times. Identity fields such as names or telephone numbers are not part of
this schema and must not be added.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal, Optional


def _metric_from_dict(data: Optional[dict[str, Any]]) -> Optional["Metric"]:
    if not data:
        return None
    return Metric(
        value=_optional_str(data.get("value")),
        unit=_optional_str(data.get("unit")),
        label_in_report=_optional_str(data.get("label_in_report")),
        as_printed=_optional_str(data.get("as_printed")),
    )


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


@dataclass(frozen=True)
class Metric:
    """A single quantity copied from a report, with the original unit retained."""

    value: Optional[str] = None
    unit: Optional[str] = None
    label_in_report: Optional[str] = None
    as_printed: Optional[str] = None

    def display(self) -> str:
        if self.as_printed:
            return self.as_printed
        parts = [part for part in (self.value, self.unit) if part]
        return " ".join(parts) if parts else "（报告未写出）"


@dataclass(frozen=True)
class TimeBand:
    label: Optional[str] = None
    range_low: Optional[str] = None
    range_high: Optional[str] = None
    unit: Optional[str] = None
    percent: Optional[str] = None
    duration: Optional[str] = None


@dataclass(frozen=True)
class SoftwareGauge:
    """A vendor dashboard reading that is not a TIR/TAR/TBR band.

    Do not treat this as a guideline risk grade unless a read knowledge-base
    source actually supports that reading.
    """

    name: Optional[str] = None
    reading: Optional[str] = None
    note: Optional[str] = None


@dataclass
class ExtractedReport:
    """Structured metrics taken from one CGM graphic report."""

    fictional: bool = False
    wearer_key: Optional[str] = None
    same_wearer_confirmed: Optional[bool] = None
    wear_start: Optional[str] = None
    wear_end: Optional[str] = None
    wear_days_stated: Optional[str] = None
    coverage: Optional[Metric] = None
    data_quality_note: Optional[str] = None
    reference_only: bool = False
    disclaimer_text: Optional[str] = None
    identity_fields_ignored: bool = False
    mean_glucose: Optional[Metric] = None
    sd: Optional[Metric] = None
    cv: Optional[Metric] = None
    e_hba1c_or_gmi: Optional[Metric] = None
    glucose_min: Optional[Metric] = None
    glucose_max: Optional[Metric] = None
    very_low_stated: Optional[Metric] = None
    bands: list[TimeBand] = field(default_factory=list)
    software_gauges: list[SoftwareGauge] = field(default_factory=list)
    time_of_day_patterns: list[str] = field(default_factory=list)
    hypoglycemia_events: list[dict[str, Any]] = field(default_factory=list)
    hyperglycemia_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractedReport":
        bands = [
            TimeBand(
                label=_optional_str(item.get("label")),
                range_low=_optional_str(item.get("range_low")),
                range_high=_optional_str(item.get("range_high")),
                unit=_optional_str(item.get("unit")),
                percent=_optional_str(item.get("percent")),
                duration=_optional_str(item.get("duration")),
            )
            for item in data.get("bands") or []
        ]
        gauges = [
            SoftwareGauge(
                name=_optional_str(item.get("name")),
                reading=_optional_str(item.get("reading")),
                note=_optional_str(item.get("note")),
            )
            for item in data.get("software_gauges") or []
        ]
        return cls(
            fictional=bool(data.get("fictional", False)),
            wearer_key=_optional_str(data.get("wearer_key")),
            same_wearer_confirmed=data.get("same_wearer_confirmed"),
            wear_start=_optional_str(data.get("wear_start")),
            wear_end=_optional_str(data.get("wear_end")),
            wear_days_stated=_optional_str(data.get("wear_days_stated")),
            coverage=_metric_from_dict(data.get("coverage") if isinstance(data.get("coverage"), dict) else None),
            data_quality_note=_optional_str(data.get("data_quality_note")),
            reference_only=bool(data.get("reference_only", False)),
            disclaimer_text=_optional_str(data.get("disclaimer_text")),
            identity_fields_ignored=bool(data.get("identity_fields_ignored", False)),
            mean_glucose=_metric_from_dict(data.get("mean_glucose")),
            sd=_metric_from_dict(data.get("sd")),
            cv=_metric_from_dict(data.get("cv")),
            e_hba1c_or_gmi=_metric_from_dict(data.get("e_hba1c_or_gmi")),
            glucose_min=_metric_from_dict(data.get("glucose_min")),
            glucose_max=_metric_from_dict(data.get("glucose_max")),
            very_low_stated=_metric_from_dict(data.get("very_low_stated")),
            bands=bands,
            software_gauges=gauges,
            time_of_day_patterns=[str(item) for item in data.get("time_of_day_patterns") or []],
            hypoglycemia_events=list(data.get("hypoglycemia_events") or []),
            hyperglycemia_events=list(data.get("hyperglycemia_events") or []),
        )


@dataclass
class Medication:
    """A medicine record that preserves the names and figures the user supplied."""

    name_as_provided: Optional[str] = None
    dose_as_provided: Optional[str] = None
    schedule_as_provided: Optional[str] = None
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Medication":
        return cls(
            name_as_provided=_optional_str(data.get("name_as_provided") or data.get("name")),
            dose_as_provided=_optional_str(data.get("dose_as_provided") or data.get("dose")),
            schedule_as_provided=_optional_str(data.get("schedule_as_provided") or data.get("schedule")),
            notes=_optional_str(data.get("notes")),
        )


# Fields that a knowledge-base source may declare as required for advice.
INTAKE_FIELD_LABELS: dict[str, str] = {
    "diabetes_type": "糖尿病类型",
    "diabetes_duration": "糖尿病病程或诊断年份",
    "medications": "用药名称、剂量和服药或注射时间",
    "height_cm": "身高",
    "weight_kg": "目前体重",
    "recent_weight_change": "近期体重变化",
    "comorbidities": "合并症与并发症（如心血管疾病、眼底病变、肾脏病、周围神经或足部问题）",
    "meal_pattern": "用餐时间与大致内容",
    "activity_habit": "运动习惯（类型、时间、强度，以及和吃饭、用药的关系）",
    "sleep_schedule": "大致睡眠时段",
    "lab_hba1c": "近期化验室测定的糖化血红蛋白",
    "hypoglycemia_awareness": "低血糖时有无症状、如何处理，有无不易察觉的情况",
    "monitoring_period_events": "这段监测期间是否生病、饮酒、住院或刚出院",
}


@dataclass
class IntakeRecord:
    """Clinical intake supplied by the user. Empty means unknown, not zero."""

    fictional: bool = False
    wearer_key: Optional[str] = None
    display_label: Optional[str] = None
    age_years: Optional[str] = None
    sex: Optional[str] = None
    diabetes_type: Optional[str] = None
    diabetes_duration: Optional[str] = None
    height_cm: Optional[str] = None
    weight_kg: Optional[str] = None
    recent_weight_change: Optional[str] = None
    medications: list[Medication] = field(default_factory=list)
    comorbidities: Optional[str] = None
    meal_pattern: Optional[str] = None
    activity_habit: Optional[str] = None
    sleep_schedule: Optional[str] = None
    lab_hba1c: Optional[str] = None
    hypoglycemia_awareness: Optional[str] = None
    monitoring_period_events: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeRecord":
        meds = [Medication.from_dict(item) for item in data.get("medications") or []]
        known = {item.name for item in fields(cls)}
        payload = {key: value for key, value in data.items() if key in known and key != "medications"}
        payload["medications"] = meds
        payload["fictional"] = bool(data.get("fictional", False))
        return cls(**payload)

    def is_filled(self, field_name: str) -> bool:
        if field_name == "medications":
            return any(item.name_as_provided for item in self.medications)
        value = getattr(self, field_name, None)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        return True


ReadStatus = Literal["full_text_read", "selected_sections_read", "unread"]


@dataclass(frozen=True)
class KnowledgeEntry:
    """A short, already-curated sentence taken from a source the user has read.

    The first version of this project does not parse guideline PDFs. Only
    entries present in the user's index may be turned into advice.
    """

    entry_id: str
    kind: Literal["diet", "activity", "monitoring", "referral", "target", "other"]
    locator: Optional[str]
    text: str
    portion_or_action: Optional[str] = None
    applies_to: Optional[str] = None
    level2_hypoglycemia_threshold: Optional[str] = None


@dataclass(frozen=True)
class KnowledgeSource:
    id: str
    title: str
    version: Optional[str] = None
    year: Optional[int] = None
    publisher_or_society: Optional[str] = None
    scope: Optional[str] = None
    read_status: ReadStatus = "unread"
    path: Optional[str] = None
    applies_to: Optional[str] = None
    notes: Optional[str] = None
    required_intake_fields: tuple[str, ...] = ()
    entries: tuple[KnowledgeEntry, ...] = ()

    def is_usable(self) -> bool:
        return self.read_status in {"full_text_read", "selected_sections_read"}


@dataclass(frozen=True)
class MissingIntakeItem:
    field_name: str
    label: str
    requested_by: tuple[str, ...]


@dataclass
class AdviceItem:
    category: str
    text: str
    source_id: str
    source_title: str
    source_version: Optional[str]
    source_year: Optional[int]
    locator: Optional[str]
    portion_or_action: Optional[str] = None
    illustration: Optional["IllustrationRequest"] = None

    def source_line(self) -> str:
        bits = [self.source_title]
        if self.source_version:
            bits.append(self.source_version)
        if self.source_year:
            bits.append(str(self.source_year))
        if self.locator:
            bits.append(self.locator)
        return "，".join(bits) + f"（来源标识：{self.source_id}）"


@dataclass
class IllustrationRequest:
    """A request to draw only the portion or action already stated in the knowledge base."""

    advice_entry_id: Optional[str]
    portion_or_action: str
    caption: str
    prompt: str
    allowed: bool
    refusal_reason: Optional[str] = None


@dataclass
class InterpretationSection:
    title: str
    paragraphs: list[str]


@dataclass
class AnalysisResult:
    metrics_only: bool
    lifestyle_advice_allowed: bool
    missing_intake: list[MissingIntakeItem]
    sections: list[InterpretationSection]
    advice: list[AdviceItem]
    stop_reason: Optional[str] = None
    wearer_conflict: Optional[str] = None
