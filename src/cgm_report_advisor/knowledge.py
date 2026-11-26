"""Load a local knowledge-base *index*, not guideline full text.

Unread sources must not be treated as mastered. This module never ships or
reads copyrighted guideline bodies from the repository templates. Users point
the loader at their own index file after they have obtained and read the
documents they are entitled to use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import KnowledgeEntry, KnowledgeSource


ALLOWED_READ_STATUS = {"full_text_read", "selected_sections_read", "unread"}
ALLOWED_ENTRY_KINDS = {"diet", "activity", "monitoring", "referral", "target", "other"}
ALLOWED_REVIEW_STATUS = {"accepted", "pending_review", "rejected"}


class KnowledgeBase:
    def __init__(self, sources: list[KnowledgeSource], *, origin: Optional[Path] = None):
        self.sources = sources
        self.origin = origin

    @classmethod
    def from_json_path(cls, path: Path) -> "KnowledgeBase":
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources = [_source_from_dict(item) for item in raw.get("sources") or []]
        return cls(sources, origin=path)

    def usable_sources(self) -> list[KnowledgeSource]:
        return [source for source in self.sources if source.is_usable()]

    def required_intake_fields(self) -> dict[str, list[str]]:
        """Map an intake field name to the usable sources that asked for it.

        Fields listed only on unread sources are ignored, because those
        sources must not drive analysis or questionnaires.
        """
        requested: dict[str, list[str]] = {}
        for source in self.usable_sources():
            for field_name in source.required_intake_fields:
                requested.setdefault(field_name, []).append(source.id)
        return requested

    def usable_entries(self, kinds: Optional[Iterable[str]] = None) -> list[tuple[KnowledgeSource, KnowledgeEntry]]:
        allowed = set(kinds) if kinds is not None else None
        collected: list[tuple[KnowledgeSource, KnowledgeEntry]] = []
        for source in self.usable_sources():
            for entry in source.entries:
                if not _entry_is_usable(entry):
                    continue
                if allowed is None or entry.kind in allowed:
                    collected.append((source, entry))
        return collected

    def unused_because_unread(self) -> list[KnowledgeSource]:
        """Sources that were not read. Superseded sources are reported separately."""
        return [
            source
            for source in self.sources
            if not source.superseded and source.read_status == "unread"
        ]

    def superseded_sources(self) -> list[KnowledgeSource]:
        return [source for source in self.sources if source.superseded]


def _source_from_dict(data: dict[str, Any]) -> KnowledgeSource:
    status = data.get("read_status") or "unread"
    if status not in ALLOWED_READ_STATUS:
        raise ValueError(f"Unknown read_status {status!r}; expected one of {sorted(ALLOWED_READ_STATUS)}")
    entries_raw = data.get("demo_entries") or data.get("entries") or []
    entries = tuple(_entry_from_dict(item) for item in entries_raw)
    year = data.get("year")
    return KnowledgeSource(
        id=str(data["id"]),
        title=str(data["title"]),
        version=_optional(data.get("version")),
        year=int(year) if year is not None and year != "" else None,
        publisher_or_society=_optional(data.get("publisher_or_society")),
        scope=_optional(data.get("scope")),
        read_status=status,
        path=_optional(data.get("path")),
        applies_to=_optional(data.get("applies_to")),
        notes=_optional(data.get("notes")),
        required_intake_fields=tuple(str(item) for item in data.get("required_intake_fields") or []),
        entries=entries,
        series_id=_optional(data.get("series_id")),
        superseded=data.get("superseded") is True,
        superseded_by=_optional(data.get("superseded_by")),
    )


def _entry_from_dict(data: dict[str, Any]) -> KnowledgeEntry:
    kind = str(data.get("kind") or "other")
    if kind not in ALLOWED_ENTRY_KINDS:
        raise ValueError(f"Unknown knowledge entry kind {kind!r}")
    text = str(data.get("text") or "").strip()
    if not text:
        raise ValueError("Knowledge entries must include the source sentence in 'text'")
    review_raw = data.get("review_status")
    if review_raw is None or review_raw == "":
        # Hand-written index rows predate draft review and were accepted by
        # the person who put them in the index.
        review_status = "accepted"
    else:
        review_status = str(review_raw)
        if review_status not in ALLOWED_REVIEW_STATUS:
            raise ValueError(
                f"Unknown review_status {review_status!r}; expected one of {sorted(ALLOWED_REVIEW_STATUS)}"
            )
    return KnowledgeEntry(
        entry_id=str(data.get("entry_id") or data.get("id") or "unnamed"),
        kind=kind,  # type: ignore[arg-type]
        locator=_optional(data.get("locator")),
        text=text,
        portion_or_action=_optional(data.get("portion_or_action")),
        applies_to=_optional(data.get("applies_to")),
        level2_hypoglycemia_threshold=_optional(data.get("level2_hypoglycemia_threshold")),
        source_quote=_optional(data.get("source_quote")),
        review_status=review_status,  # type: ignore[arg-type]
        superseded=data.get("superseded") is True,
    )


def _entry_is_usable(entry: KnowledgeEntry) -> bool:
    """Pending and rejected drafts are never advice, even on a read source."""
    if entry.superseded:
        return False
    return entry.review_status == "accepted"


def _optional(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)
