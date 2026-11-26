"""Bibliographic watch: report a possible newer edition, never download it.

The watchlist stores series names, societies, and only those URLs or DOIs
that were checked when the list was written. A run compares that list with
the user's local sources index.

Offline fixture mode is what tests use. Live mode may ask Crossref, Europe
PMC, or PubMed for metadata (title, year, DOI). It does not fetch PDFs and
does not write them into the repository. If a live lookup fails, that row is
skipped and no update is invented.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .knowledge import KnowledgeBase


class WatchError(ValueError):
    """The watchlist, index, or fixture cannot be used."""


class LookupSkipped(Exception):
    """This row has no check result. The caller must not invent one."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class WatchSeries:
    series_id: str
    title: str
    publisher_or_society: Optional[str]
    official_url: Optional[str]
    doi: Optional[str]
    suggested_query: str
    last_seen_year: Optional[int]
    last_seen_version: Optional[str]


@dataclass(frozen=True)
class CheckHit:
    series_id: str
    year: Optional[int]
    version_label: Optional[str]
    obtain_from: Optional[str]
    source_label: str


@dataclass(frozen=True)
class SeriesFinding:
    series: WatchSeries
    status: str
    local_year: Optional[int]
    local_source_id: Optional[str]
    hit: Optional[CheckHit]
    detail: str


Lookup = Callable[[WatchSeries], CheckHit]

_USER_AGENT = "cgm-report-advisor-watch/0.1 (metadata only; no full text)"
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def load_watchlist(path: Path) -> list[WatchSeries]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("series")
    if not isinstance(rows, list) or not rows:
        raise WatchError(f"{path} 没有 series 数组。")
    series: list[WatchSeries] = []
    for row in rows:
        if not isinstance(row, dict):
            raise WatchError("监测清单中有无法读取的系列。")
        series_id = str(row.get("series_id") or "").strip()
        title = str(row.get("title") or "").strip()
        query = str(row.get("suggested_query") or "").strip()
        if not series_id or not title or not query:
            raise WatchError("每个系列都需要 series_id、title 和 suggested_query。")
        last_seen = row.get("last_seen") or {}
        if last_seen is None:
            last_seen = {}
        if not isinstance(last_seen, dict):
            raise WatchError(f"{series_id} 的 last_seen 必须是对象或留空。")
        official_url = _optional_str(row.get("official_url"))
        if official_url and _is_pdf_url(official_url):
            raise WatchError(f"{series_id} 的官方地址不能是 PDF 链接。")
        series.append(
            WatchSeries(
                series_id=series_id,
                title=title,
                publisher_or_society=_optional_str(row.get("publisher_or_society")),
                official_url=official_url,
                doi=_optional_str(row.get("doi")),
                suggested_query=query,
                last_seen_year=_optional_int(last_seen.get("year")),
                last_seen_version=_optional_str(last_seen.get("version_label")),
            )
        )
    return series


def load_fixture(path: Path) -> dict[str, CheckHit]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("results")
    if not isinstance(rows, list):
        raise WatchError("夹具文件需要 results 数组。")
    hits: dict[str, CheckHit] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise WatchError("夹具中有无法读取的核对结果。")
        series_id = str(row.get("series_id") or "").strip()
        if not series_id:
            raise WatchError("夹具核对结果缺少 series_id。")
        obtain_from = _optional_str(row.get("obtain_from"))
        if obtain_from and _is_pdf_url(obtain_from):
            raise WatchError("夹具中的获取位置不能是 PDF。监测不会下载全文。")
        hits[series_id] = CheckHit(
            series_id=series_id,
            year=_optional_int(row.get("year")),
            version_label=_optional_str(row.get("version_label")),
            obtain_from=obtain_from,
            source_label=_optional_str(row.get("source_label")) or "fixture",
        )
    return hits


def run_watch(
    watchlist_path: Path,
    *,
    index_path: Optional[Path] = None,
    fixture_path: Optional[Path] = None,
    live: bool = False,
    lookup: Optional[Lookup] = None,
) -> str:
    """Compare the watchlist with a local index. Returns a Chinese report."""
    if fixture_path is not None and live:
        raise WatchError("夹具模式与在线模式不能同时使用。")
    series_rows = load_watchlist(watchlist_path)
    local_sources = []
    if index_path is not None:
        if not index_path.is_file():
            raise WatchError(f"找不到本地索引：{index_path}")
        local_sources = KnowledgeBase.from_json_path(index_path).sources

    if fixture_path is not None:
        hits = load_fixture(fixture_path)
        mode = "离线夹具（不访问网络，不下载全文）"

        def resolve(series: WatchSeries) -> CheckHit:
            hit = hits.get(series.series_id)
            if hit is None:
                raise LookupSkipped("离线夹具没有该系列的核对结果，已跳过，未臆造更新。")
            return hit

    elif live:
        mode = "在线书目核对（仅题名、年份和标识，不下载全文）"
        resolve = lookup or live_lookup
    else:
        mode = "未核对（没有夹具，也没有 --live）"

        def resolve(series: WatchSeries) -> CheckHit:
            raise LookupSkipped("未进行在线或夹具核对，不能判断是否有更新。")

    findings: list[SeriesFinding] = []
    for series in series_rows:
        local = _best_local(series, local_sources)
        try:
            hit = resolve(series)
        except LookupSkipped as exc:
            findings.append(
                SeriesFinding(
                    series=series,
                    status="skipped",
                    local_year=None if local is None else local.year,
                    local_source_id=None if local is None else local.id,
                    hit=None,
                    detail=exc.reason,
                )
            )
            continue
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            findings.append(
                SeriesFinding(
                    series=series,
                    status="skipped",
                    local_year=None if local is None else local.year,
                    local_source_id=None if local is None else local.id,
                    hit=None,
                    detail=f"在线核对失败：{exc}。该条已跳过，未臆造更新。",
                )
            )
            continue
        findings.append(_judge(series, local, hit))
    return format_report(findings, mode=mode)


def live_lookup(series: WatchSeries) -> CheckHit:
    """Ask public metadata APIs. Never requests a PDF body."""
    candidates: list[CheckHit] = []
    errors: list[str] = []
    for fetcher in (
        lambda: _crossref_query(series),
        lambda: _europepmc_query(series),
        lambda: _pubmed_query(series),
    ):
        try:
            candidates.extend(fetcher())
        except LookupSkipped as exc:
            errors.append(exc.reason)
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
    related = [hit for hit in candidates if hit.year is not None]
    if related:
        return max(related, key=lambda hit: hit.year or 0)
    if series.doi:
        try:
            return _crossref_doi(series)
        except (LookupSkipped, OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
    detail = "；".join(errors) if errors else "没有与系列名称相符的书目记录"
    raise LookupSkipped(f"在线核对没有可用结果（{detail}）。该条已跳过，未臆造更新。")


def format_report(findings: list[SeriesFinding], *, mode: str) -> str:
    lines = [
        "文献系列监测报告",
        "本报告只比较书目信息，不下载、不保存指南全文。",
        f"核对方式：{mode}",
        "",
    ]
    newer = [item for item in findings if item.status == "newer"]
    if newer:
        lines.append("可能有更新，请自行从官方途径取得原文，放入本地 sources 目录后再导入：")
        for item in newer:
            lines.extend(_format_finding(item))
        lines.append("")
    else:
        lines.append("未发现比本地索引更新的版本。")
        lines.append("")
    others = [item for item in findings if item.status != "newer"]
    if others:
        lines.append("其余系列：")
        for item in others:
            lines.extend(_format_finding(item))
    return "\n".join(lines).rstrip() + "\n"


def _judge(series: WatchSeries, local: Any, hit: CheckHit) -> SeriesFinding:
    local_year = None if local is None else local.year
    local_id = None if local is None else local.id
    if hit.year is None:
        return SeriesFinding(
            series, "check_without_year", local_year, local_id, hit, "核对结果没有年份，不能把它当成更新。"
        )
    if local is None or local_year is None:
        return SeriesFinding(
            series,
            "no_local_year",
            local_year,
            local_id,
            hit,
            "本地索引没有该系列的年份，因此还不能称为比本地更新。",
        )
    if hit.year > local_year:
        return SeriesFinding(series, "newer", local_year, local_id, hit, "")
    return SeriesFinding(series, "not_newer", local_year, local_id, hit, "")


def _format_finding(item: SeriesFinding) -> list[str]:
    title = f"《{item.series.title}》（{item.series.series_id}）"
    if item.status == "newer" and item.hit is not None:
        version = item.hit.version_label or str(item.hit.year)
        obtain = _obtain_text(item)
        return [
            f"- {title}",
            f"  本地索引年份：{item.local_year}（来源标识 {item.local_source_id}）",
            f"  核对看到的年份或版本：{version}",
            f"  官方获取位置：{obtain}",
            "  本程序没有下载或保存全文。",
        ]
    if item.status == "not_newer" and item.hit is not None:
        return [
            f"- {title}：本地索引年份为 {item.local_year}，核对结果为 {item.hit.year}，没有比本地更新的版本。"
        ]
    if item.status == "no_local_year" and item.hit is not None:
        return [
            f"- {title}：{item.detail}核对看到的年份为 {item.hit.year}。获取位置：{_obtain_text(item)}"
        ]
    if item.status == "skipped":
        recorded = ""
        if item.series.last_seen_year is not None:
            recorded = f"清单里原有的观察年份是 {item.series.last_seen_year}，那不是本次核对结果。"
        return [f"- {title}：{item.detail}{recorded}"]
    if item.status == "check_without_year":
        return [f"- {title}：{item.detail}"]
    return [f"- {title}：{item.detail or item.status}"]


def _obtain_text(item: SeriesFinding) -> str:
    hit = item.hit
    if hit and hit.obtain_from and not _is_pdf_url(hit.obtain_from):
        return hit.obtain_from
    if item.series.official_url:
        return item.series.official_url
    if item.series.doi:
        return f"DOI {item.series.doi}（只作为书目标识，本次不打开落地页，也不下载全文）"
    return "本次没有已核验的官方网址。请用检索式向发布机构查找，不要使用来源不明的全文。"


def _best_local(series: WatchSeries, sources: list[Any]) -> Any:
    by_id = [source for source in sources if source.series_id and source.series_id == series.series_id]
    pool = by_id or [
        source for source in sources if _compact(series.title) and _compact(series.title) in _compact(source.title)
    ]
    if not pool:
        return None
    return max(pool, key=lambda source: source.year or -1)


def _crossref_query(series: WatchSeries) -> list[CheckHit]:
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query.bibliographic": series.suggested_query, "rows": "5"}
    )
    payload = _get_json(url)
    message = payload.get("message") or {}
    hits: list[CheckHit] = []
    for item in message.get("items") or []:
        hit = _hit_from_crossref_item(series, item, "Crossref")
        if hit is not None:
            hits.append(hit)
    return hits


def _crossref_doi(series: WatchSeries) -> CheckHit:
    if not series.doi:
        raise LookupSkipped("没有 DOI。")
    quoted = urllib.parse.quote(series.doi)
    payload = _get_json(f"https://api.crossref.org/works/{quoted}")
    item = payload.get("message") or {}
    hit = _hit_from_crossref_item(series, item, "Crossref DOI", require_related=False)
    if hit is None or hit.year is None:
        raise LookupSkipped("Crossref 没有返回可用年份。")
    return hit


def _hit_from_crossref_item(
    series: WatchSeries,
    item: dict[str, Any],
    source_label: str,
    *,
    require_related: bool = True,
) -> Optional[CheckHit]:
    title = " ".join(item.get("title") or [])
    if require_related and not _related(series.title, title):
        return None
    issued = item.get("issued") or {}
    parts = (issued.get("date-parts") or [[]])[0]
    issued_year = parts[0] if parts else None
    year = _edition_year(title, _optional_int(issued_year))
    doi = _optional_str(item.get("DOI"))
    obtain = series.official_url or (f"DOI {doi}" if doi else None)
    return CheckHit(
        series_id=series.series_id,
        year=year,
        version_label=title[:120] if title else (str(year) if year else None),
        obtain_from=obtain,
        source_label=source_label,
    )


def _europepmc_query(series: WatchSeries) -> list[CheckHit]:
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {
            "query": series.suggested_query,
            "format": "json",
            "resultType": "lite",
            "pageSize": "5",
        }
    )
    payload = _get_json(url)
    results = ((payload.get("resultList") or {}).get("result")) or []
    hits: list[CheckHit] = []
    for item in results:
        title = str(item.get("title") or "")
        if not _related(series.title, title):
            continue
        year = _edition_year(title, _optional_int(item.get("pubYear")))
        doi = _optional_str(item.get("doi"))
        hits.append(
            CheckHit(
                series_id=series.series_id,
                year=year,
                version_label=title[:120] if title else None,
                obtain_from=series.official_url or (f"DOI {doi}" if doi else None),
                source_label="Europe PMC",
            )
        )
    return hits


def _pubmed_query(series: WatchSeries) -> list[CheckHit]:
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "retmode": "json", "retmax": "5", "term": series.suggested_query}
    )
    searched = _get_json(search_url)
    ids = ((searched.get("esearchresult") or {}).get("idlist")) or []
    if not ids:
        return []
    summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "retmode": "json", "id": ",".join(ids)}
    )
    summary = _get_json(summary_url)
    result = summary.get("result") or {}
    hits: list[CheckHit] = []
    for pubmed_id in ids:
        item = result.get(pubmed_id) or {}
        title = str(item.get("title") or "")
        if not _related(series.title, title):
            continue
        year = _edition_year(title, _year_in_text(str(item.get("pubdate") or "")))
        hits.append(
            CheckHit(
                series_id=series.series_id,
                year=year,
                version_label=title[:120] if title else None,
                obtain_from=series.official_url,
                source_label="PubMed",
            )
        )
    return hits


def _get_json(url: str) -> dict[str, Any]:
    if _is_pdf_url(url):
        raise LookupSkipped("拒绝请求 PDF 地址。")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        content_type = response.headers.get("Content-Type") or ""
        if "pdf" in content_type.lower():
            raise LookupSkipped("书目接口返回了 PDF，已丢弃，未保存。")
        body = response.read()
    payload = json.loads(body.decode("utf-8"))
    if isinstance(payload, dict):
        payload.pop("abstract", None)
        return payload
    raise LookupSkipped("书目接口没有返回对象。")


def _related(series_title: str, found_title: str) -> bool:
    if not found_title:
        return False
    series_compact = _compact(series_title)
    found_compact = _compact(found_title)
    if len(series_compact) >= 4 and series_compact in found_compact:
        return True
    words = [word for word in re.findall(r"[A-Za-z]{4,}", series_title.lower()) if word not in {"with", "from", "that"}]
    if not words:
        return False
    found_lower = found_title.lower()
    overlap = sum(1 for word in words if word in found_lower)
    return overlap >= max(1, (len(words) + 1) // 2)


def _edition_year(title: str, issued_year: Optional[int]) -> Optional[int]:
    years = [int(match) for match in _YEAR_RE.findall(title or "")]
    if years:
        return max(years)
    return issued_year


def _year_in_text(value: str) -> Optional[int]:
    match = _YEAR_RE.search(value or "")
    if not match:
        return None
    return int(match.group(0))


def _compact(text: str) -> str:
    return re.sub(r"[\s（）()《》〈〉,，。:：—\-]+", "", text or "").lower()


def _is_pdf_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(".pdf")


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cgm_report_advisor.watch",
        description="比较本地索引与文献系列的书目信息。不下载指南全文。",
    )
    parser.add_argument("--watchlist", default="knowledge-base/watchlist.json")
    parser.add_argument("--index", help="本地 sources.json。不传则只列出清单，无法和本地年份比较。")
    parser.add_argument("--fixture", help="离线夹具 JSON。测试用，不会访问网络。")
    parser.add_argument("--live", action="store_true", help="向 Crossref、Europe PMC 或 PubMed 查询书目，不下载 PDF。")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_watch(
            Path(args.watchlist),
            index_path=Path(args.index) if args.index else None,
            fixture_path=Path(args.fixture) if args.fixture else None,
            live=bool(args.live),
        )
    except (WatchError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
