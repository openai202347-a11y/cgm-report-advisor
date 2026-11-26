"""Command-line entry point for the pipeline skeleton."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cgm-report-advisor",
        description=(
            "根据已整理的 CGM 指标、临床资料和本地知识库索引，生成带出处的建议草稿。"
            "第一版不能完整解析各厂商 PDF，也不是医疗器械。"
        ),
    )
    parser.add_argument(
        "--metrics",
        nargs="+",
        required=True,
        metavar="JSON",
        help="一份或多份已按 docs/report-schema.md 整理的指标 JSON。不要传入未提取的 PDF。",
    )
    parser.add_argument(
        "--knowledge-base",
        required=True,
        metavar="JSON",
        help="本地知识库索引 JSON。未读来源不会被当作已掌握。",
    )
    parser.add_argument(
        "--intake",
        metavar="JSON",
        help="已收集的临床资料 JSON。如缺知识库所需项目且未指定 --metrics-only，将停在询问清单。",
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="只做指标解读并标明资料缺口，不输出饮食或运动处方。",
    )
    parser.add_argument(
        "--output",
        metavar="MD",
        help="把 Markdown 草稿写入该路径。省略时打印到标准输出。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_pipeline(
            metrics_paths=args.metrics,
            knowledge_path=args.knowledge_base,
            intake_path=args.intake,
            metrics_only=args.metrics_only,
        )
    except NotImplementedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if result.stopped_for_intake and result.intake_questions:
        banner = "资料尚未齐，已生成询问清单，并输出不含饮食运动处方的指标解读。\n"
        text = banner + "\n" + result.intake_questions + "\n" + result.markdown
    else:
        text = result.markdown

    if args.output:
        path = Path(args.output)
        path.write_text(text, encoding="utf-8")
        print(f"已写入 {path}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
