"""Constrained local ingest: draft knowledge entries, do not invent portions.

The user places a file they are allowed to use under a sources directory.
This module reads plain text (PDF text extraction is optional), splits it
into sections, and writes *drafts* with ``review_status: pending_review``.
A portion is stored only when that same sentence states a quantity, duration,
or frequency. Tables are not turned into portions. Nothing here consults
general medical knowledge to fill a gap.

Drafts stay unusable until ``accept`` copies the entries a person selected
into the local sources index and sets ``read_status``. Accepting a newer
year of the same ``series_id`` marks older index rows superseded.

This module never downloads a guideline and never writes a PDF into the
repository.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional


class IngestError(ValueError):
    """The ingest input cannot be drafted or accepted safely."""


_PAGE_RE = re.compile(
    r"^(?:【第\s*(\d+)\s*页】|---\s*page\s+(\d+)\s*---)\s*$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+\S.*|第[0-9０-９一二三四五六七八九十百]+[节章节部分篇]\s*\S.*)$"
)
_QUANTITY_RE = re.compile(
    r"半个|一半|\d+(?:\.\d+)?\s*(?:分钟|小时|天|周|次|克|毫克|毫升|个|份|千卡|大卡|kcal|g|ml|min)",
    re.IGNORECASE,
)
_FREQUENCY_RE = re.compile(r"每[日天周餐]|每天|每周|每日|每次")
_ACTION_RE = re.compile(r"步行|散步|跑步|运动|食用|可食|摄入|饮用|监测|复测|扫描")
_APPLIES_RE = re.compile(r"适用于([^。；\n]{1,40})")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])")

_MAX_SENTENCE = 180

_NO_PORTION_REASON = "原文没有写出明确的数量、时长或频率，程序不补写份量。"
_TABLE_REASON = "疑似表格，其中的数字容易抽错，程序不从表格生成份量。"
_LONG_REASON = "句子过长，留待人工切分，程序不整段抄入条目。"


def draft_from_text(
    text: str,
    *,
    source_id: str,
    title: str,
    year: Optional[int] = None,
    version: Optional[str] = None,
    publisher_or_society: Optional[str] = None,
    series_id: Optional[str] = None,
    applies_to: Optional[str] = None,
    path: Optional[str] = None,
) -> dict[str, Any]:
    """Build a draft document. Does not write a file and does not invent portions."""
    if not source_id.strip():
        raise IngestError("需要来源标识 source_id。")
    if not title.strip():
        raise IngestError("需要文献名称 title。")
    entries: list[dict[str, Any]] = []
    not_drafted: list[dict[str, str]] = []
    counter = 0
    normalized = _squash(text)
    for locator, sentence, skip_reason in _iter_candidate_sentences(text):
        if skip_reason:
            not_drafted.append({"locator": locator, "text": sentence, "reason": skip_reason})
            continue
        if not _has_explicit_portion(sentence):
            not_drafted.append({"locator": locator, "text": sentence, "reason": _NO_PORTION_REASON})
            continue
        if _squash(sentence) not in normalized:
            raise IngestError("拒绝写入不在原文中的句子。")
        counter += 1
        entry_applies = _applies_from_sentence(sentence)
        entries.append(
            {
                "entry_id": f"{source_id}-{counter:03d}",
                "kind": _kind_from_sentence(sentence),
                "locator": locator,
                "text": sentence,
                "portion_or_action": sentence,
                "source_quote": sentence,
                "applies_to": entry_applies,
                "review_status": "pending_review",
                "superseded": False,
            }
        )
    return {
        "record_type": "ingest_draft",
        "review_status": "pending_review",
        "warning": "草稿未经人工接受，不得用于饮食、运动或监测建议。",
        "source": {
            "id": source_id,
            "title": title,
            "version": version,
            "year": year,
            "publisher_or_society": publisher_or_society,
            "series_id": series_id,
            "scope": None,
            "read_status": "unread",
            "path": path,
            "applies_to": applies_to,
            "notes": "由受约束导入生成的草稿。applies_to 仅在使用者传入时保留，程序不据医学通识补写。阅读范围须在接受时确认。",
            "required_intake_fields": [],
            "superseded": False,
        },
        "entries": entries,
        "not_drafted": not_drafted,
    }


def draft_from_file(
    source_file: Path,
    *,
    source_id: str,
    title: str,
    drafts_dir: Path,
    extracted_dir: Optional[Path] = None,
    year: Optional[int] = None,
    version: Optional[str] = None,
    publisher_or_society: Optional[str] = None,
    series_id: Optional[str] = None,
    applies_to: Optional[str] = None,
) -> Path:
    """Read a local .txt (or optional PDF) and write a pending draft JSON."""
    text = read_local_text(source_file)
    if extracted_dir is not None:
        extracted_dir.mkdir(parents=True, exist_ok=True)
        extracted_path = extracted_dir / f"{source_id}.txt"
        if extracted_path.suffix.lower() == ".pdf":
            raise IngestError("提取文本不会写成 PDF。")
        extracted_path.write_text(text, encoding="utf-8")
    document = draft_from_text(
        text,
        source_id=source_id,
        title=title,
        year=year,
        version=version,
        publisher_or_society=publisher_or_society,
        series_id=series_id,
        applies_to=applies_to,
        path=str(source_file),
    )
    drafts_dir.mkdir(parents=True, exist_ok=True)
    destination = drafts_dir / f"{source_id}.json"
    _write_json(destination, document)
    return destination


def read_local_text(path: Path) -> str:
    """Read text the user already has. PDF support is an optional import."""
    if not path.is_file():
        raise IngestError(f"找不到本地文件：{path}")
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return _read_pdf_optional(path)
    raise IngestError(
        f"不支持的文件类型 {suffix or '(无后缀)'}。请提供 .txt。"
        "PDF 需要另行安装可选库 pypdf，且本程序不会把 PDF 复制进仓库。"
    )


def _read_pdf_optional(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestError(
            "未安装可选的 PDF 文本提取库 pypdf，因此不能读取该 PDF。"
            "请改用 .txt，或自行安装 pypdf 后再试。本程序不会下载指南，也不会把 PDF 写入仓库。"
        ) from exc
    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            pages.append(f"【第 {index} 页】\n{extracted}")
    except Exception as exc:  # pypdf raises a variety of parse errors
        raise IngestError(f"未能从该 PDF 抽出文本：{exc}") from exc
    return "\n\n".join(pages)


def accept_draft(
    draft_path: Path,
    index_path: Path,
    *,
    read_status: str,
    entry_ids: Optional[list[str]] = None,
    accept_all: bool = False,
) -> dict[str, Any]:
    """Copy selected draft entries into the local index.

    ``read_status`` must be the scope the user confirms. Pending drafts are
    not usable until this runs. Older rows with the same ``series_id`` and an
    earlier year are marked superseded and are not merged into the new text.
    """
    if read_status not in {"full_text_read", "selected_sections_read"}:
        raise IngestError("接受时必须写明 full_text_read 或 selected_sections_read。")
    if accept_all and entry_ids:
        raise IngestError("请只选择 --accept-all，或只列出要接受的条目，不要两者同时使用。")
    if not accept_all and not entry_ids:
        raise IngestError("请用条目标识指出要接受的草稿，或显式加上 --accept-all。")

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if draft.get("record_type") != "ingest_draft":
        raise IngestError("该文件不是导入草稿。")
    source = dict(draft.get("source") or {})
    if not source.get("id") or not source.get("title"):
        raise IngestError("草稿缺少来源标识或名称。")
    available = {str(item.get("entry_id")): item for item in draft.get("entries") or []}
    chosen_ids = list(available) if accept_all else list(entry_ids or [])
    missing = [item for item in chosen_ids if item not in available]
    if missing:
        raise IngestError("草稿中没有这些条目：" + "、".join(missing))
    if not chosen_ids:
        raise IngestError("没有可接受的条目。")

    accepted_entries = []
    for entry_id in chosen_ids:
        entry = dict(available[entry_id])
        if entry.get("review_status") not in {None, "", "pending_review", "accepted"}:
            raise IngestError(f"条目 {entry_id} 不是待审草稿。")
        portion = entry.get("portion_or_action")
        quote = entry.get("source_quote") or entry.get("text") or ""
        if portion and str(portion) not in str(quote):
            raise IngestError(f"条目 {entry_id} 的份量不是出处引文的原文，拒绝接受。")
        entry["review_status"] = "accepted"
        entry["superseded"] = False
        accepted_entries.append(entry)

    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(index, dict):
            raise IngestError("知识库索引必须是 JSON 对象。")
    else:
        index = {"sources": []}
    sources = index.get("sources")
    if sources is None:
        sources = []
        index["sources"] = sources
    if not isinstance(sources, list):
        raise IngestError("知识库索引的 sources 必须是数组。")

    new_source = {
        "id": source.get("id"),
        "title": source.get("title"),
        "version": source.get("version"),
        "year": source.get("year"),
        "publisher_or_society": source.get("publisher_or_society"),
        "series_id": source.get("series_id"),
        "scope": "全文" if read_status == "full_text_read" else "已接受的条目",
        "read_status": read_status,
        "path": source.get("path"),
        "applies_to": source.get("applies_to"),
        "notes": "由导入草稿经人工接受后写入。未接受的句子没有抄入。",
        "required_intake_fields": list(source.get("required_intake_fields") or []),
        "superseded": False,
        "superseded_by": None,
        "entries": accepted_entries,
    }
    replaced = False
    for index_position, existing in enumerate(sources):
        if isinstance(existing, dict) and existing.get("id") == new_source["id"]:
            sources[index_position] = new_source
            replaced = True
            break
    if not replaced:
        sources.append(new_source)

    superseded_ids = _mark_older_series_superseded(sources, new_source)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(index_path, index)
    return {
        "index_path": str(index_path),
        "source_id": new_source["id"],
        "read_status": read_status,
        "accepted_entry_ids": chosen_ids,
        "superseded_source_ids": superseded_ids,
    }


def _mark_older_series_superseded(sources: list[Any], new_source: dict[str, Any]) -> list[str]:
    series_id = new_source.get("series_id")
    new_year = _as_int(new_source.get("year"))
    if not series_id or new_year is None:
        return []
    marked: list[str] = []
    for existing in sources:
        if not isinstance(existing, dict):
            continue
        if existing.get("id") == new_source.get("id"):
            continue
        if existing.get("series_id") != series_id:
            continue
        old_year = _as_int(existing.get("year"))
        if old_year is None or old_year >= new_year:
            continue
        existing["superseded"] = True
        existing["superseded_by"] = new_source.get("id")
        for key in ("entries", "demo_entries"):
            rows = existing.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        row["superseded"] = True
        marked.append(str(existing.get("id")))
    return marked


def _iter_candidate_sentences(text: str):
    page: Optional[str] = None
    heading: Optional[str] = None
    paragraph_index = 0
    buffer: list[str] = []

    def flush():
        nonlocal paragraph_index, buffer
        paragraph = " ".join(buffer).strip()
        buffer = []
        if not paragraph:
            return
        paragraph_index += 1
        locator = _locator(page, heading, paragraph_index)
        if _looks_like_table(paragraph):
            yield locator, paragraph, _TABLE_REASON
            return
        for sentence in _sentences(paragraph):
            if len(sentence) > _MAX_SENTENCE:
                yield locator, sentence[:_MAX_SENTENCE] + "…", _LONG_REASON
                continue
            yield locator, sentence, None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            yield from flush()
            continue
        page_match = _PAGE_RE.match(line)
        if page_match:
            yield from flush()
            page = next(group for group in page_match.groups() if group)
            continue
        if _HEADING_RE.match(line):
            yield from flush()
            heading = line.lstrip("#").strip()
            continue
        buffer.append(line)
    yield from flush()


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _sentences(paragraph: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(paragraph) if part.strip()]
    return parts or [paragraph.strip()]


def _locator(page: Optional[str], heading: Optional[str], paragraph_index: int) -> str:
    bits: list[str] = []
    if page:
        bits.append(f"第{page}页")
    if heading:
        bits.append(heading)
    if not bits:
        bits.append(f"第{paragraph_index}段")
    return " ".join(bits)


def _looks_like_table(text: str) -> bool:
    if text.count("|") >= 2:
        return True
    if text.count("\t") >= 2:
        return True
    return False


def _has_explicit_portion(sentence: str) -> bool:
    if _QUANTITY_RE.search(sentence):
        return True
    return bool(_FREQUENCY_RE.search(sentence) and _ACTION_RE.search(sentence))


def _applies_from_sentence(sentence: str) -> Optional[str]:
    match = _APPLIES_RE.search(sentence)
    if not match:
        return None
    return match.group(1).strip() or None


def _kind_from_sentence(sentence: str) -> str:
    """Label a sentence from words that actually appear in it.

    Two categories at once stay ``other`` so diet and activity are not blended
    into one recommendation. A human can relabel the draft before accepting.
    """
    diet = bool(re.search(r"可食|食用|摄入|饮食|水果|蔬菜", sentence))
    activity = bool(re.search(r"步行|散步|跑步|运动", sentence))
    monitoring = bool(re.search(r"监测|复测|扫描", sentence))
    referral = bool(re.search(r"就医|就诊|联系医生|咨询医生", sentence))
    if activity and not diet and not monitoring and not referral:
        return "activity"
    if diet and not activity and not monitoring and not referral:
        return "diet"
    if monitoring and not diet and not activity and not referral:
        return "monitoring"
    if referral and not diet and not activity and not monitoring:
        return "referral"
    return "other"


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cgm_report_advisor.ingest",
        description="把本地文本草稿化成待审知识条目，或在人工确认后接受这些条目。不下载指南全文。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft", help="从本地 txt（或可选的 PDF）生成 pending_review 草稿。")
    draft.add_argument("--file", required=True, help="使用者已放在本地的 .txt 或 .pdf。")
    draft.add_argument("--source-id", required=True)
    draft.add_argument("--title", required=True)
    draft.add_argument("--drafts-dir", default="knowledge-base/drafts")
    draft.add_argument("--extracted-dir", default="knowledge-base/extracted")
    draft.add_argument("--year", type=int)
    draft.add_argument("--version")
    draft.add_argument("--publisher")
    draft.add_argument("--series-id")
    draft.add_argument("--applies-to", help="仅保存使用者自己填写的适用说明，程序不推断。")

    accept = sub.add_parser("accept", help="把点名的草稿条目写入本地索引，并设置阅读状态。")
    accept.add_argument("--draft", required=True)
    accept.add_argument("--index", required=True, help="使用者自己的 sources.json，不要用仓库里的示例冒充已读文献。")
    accept.add_argument("--read-status", required=True, choices=["full_text_read", "selected_sections_read"])
    accept.add_argument("--entry-id", action="append", dest="entry_ids")
    accept.add_argument("--accept-all", action="store_true", help="明确接受该草稿里的全部条目。")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "draft":
            destination = draft_from_file(
                Path(args.file),
                source_id=args.source_id,
                title=args.title,
                drafts_dir=Path(args.drafts_dir),
                extracted_dir=Path(args.extracted_dir) if args.extracted_dir else None,
                year=args.year,
                version=args.version,
                publisher_or_society=args.publisher,
                series_id=args.series_id,
                applies_to=args.applies_to,
            )
            document = json.loads(destination.read_text(encoding="utf-8"))
            print(
                f"已写入草稿 {destination}。"
                f"待审条目 {len(document['entries'])} 条，未生成份量的片段 {len(document['not_drafted'])} 条。"
                "状态为 pending_review，分析流程不会把它们用于饮食、运动或监测建议。"
            )
            return 0
        result = accept_draft(
            Path(args.draft),
            Path(args.index),
            read_status=args.read_status,
            entry_ids=args.entry_ids,
            accept_all=args.accept_all,
        )
        superseded = "、".join(result["superseded_source_ids"]) or "无"
        print(
            f"已接受 {len(result['accepted_entry_ids'])} 条，写入 {result['index_path']}，"
            f"阅读状态为 {result['read_status']}。"
            f"同一系列中被标记为撤换的旧来源：{superseded}。"
        )
        return 0
    except (IngestError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
