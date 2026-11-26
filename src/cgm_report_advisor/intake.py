"""Build a missing-intake checklist from the knowledge base, not a fixed form.

Ask only for fields that usable (already read) knowledge-base sources need
in order to analyse this kind of patient or to give diet or activity advice.
Do not re-ask fields that the intake record already contains. Do not invent
doses or administration times when the user omitted them.
"""

from __future__ import annotations

from typing import Optional

from .knowledge import KnowledgeBase
from .models import INTAKE_FIELD_LABELS, IntakeRecord, MissingIntakeItem


def missing_intake_items(
    knowledge: KnowledgeBase,
    intake: Optional[IntakeRecord],
) -> list[MissingIntakeItem]:
    required = knowledge.required_intake_fields()
    missing: list[MissingIntakeItem] = []
    for field_name, source_ids in required.items():
        if intake is not None and intake.is_filled(field_name):
            continue
        label = INTAKE_FIELD_LABELS.get(field_name, field_name)
        missing.append(
            MissingIntakeItem(
                field_name=field_name,
                label=label,
                requested_by=tuple(source_ids),
            )
        )
    return missing


def format_intake_questions(missing: list[MissingIntakeItem]) -> str:
    if not missing:
        return "对照当前知识库，没有发现仍需补充的资料项目。"
    lines = [
        "对照当前已阅读的知识库来源，分析饮食或运动建议还缺少下列资料。",
        "已经提供的项目没有再列出。知道多少写多少即可，没有或不确定请标明。",
        "",
    ]
    for index, item in enumerate(missing, start=1):
        sources = "、".join(item.requested_by)
        lines.append(f"{index}. {item.label}（依据来源：{sources}）")
    return "\n".join(lines) + "\n"
