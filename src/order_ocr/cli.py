from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dateutil import parser as date_parser

from .config import DEFAULT_SHEET, DEFAULT_WORKBOOK
from .excel_store import BalanceWorkbook
from .ocr import OCRUnavailable, ocr_image
from .parser import OrderCandidate, parse_order_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recognize order details from a screenshot or OCR text.")
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK), help="Path to Balance.xlsx.")
    parser.add_argument("--sheet", default=DEFAULT_SHEET, help="Worksheet name.")
    parser.add_argument("--image", help="Screenshot image path.")
    parser.add_argument("--text", help="Text file containing OCR output.")
    parser.add_argument("--save", action="store_true", help="Append parsed result to the workbook.")
    parser.add_argument("--date", help="Purchase date override, such as 2026-06-16.")
    parser.add_argument("--item", help="Item override.")
    parser.add_argument("--price", type=float, help="Price override.")
    parser.add_argument("--category", help="Category override.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create a workbook backup before saving.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = BalanceWorkbook(args.workbook, args.sheet)
    try:
        reference = store.load_reference()
    except Exception as exc:
        print(f"Could not load reference workbook: {exc}", file=sys.stderr)
        reference = None

    try:
        text = _load_text(args)
    except OCRUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2

    candidate = parse_order_text(text, reference)
    candidate = _apply_overrides(candidate, args)

    if args.save and candidate.needs_purchase_date:
        entered = input("Purchase date was not found. Enter date (YYYY-MM-DD): ").strip()
        candidate.purchase_date = _parse_date(entered)

    print(json.dumps(_candidate_to_json(candidate), ensure_ascii=False, indent=2))

    if args.save:
        rows = []
        backup_path = None
        save_candidates = [candidate]
        if candidate.lines:
            save_candidates = [
                OrderCandidate(
                    item=line.item,
                    purchase_date=candidate.purchase_date,
                    price=line.price,
                    category=line.category,
                    raw_text=candidate.raw_text,
                )
                for line in candidate.lines
            ]
        for index, save_candidate in enumerate(save_candidates):
            result = store.append_order(save_candidate, backup=(not args.no_backup and index == 0))
            rows.append(result.row)
            backup_path = backup_path or result.backup_path
        print(f"Saved {len(rows)} row(s) to {result.workbook_path}: {rows}")
        if backup_path:
            print(f"Backup: {backup_path}")
    return 0


def _load_text(args: argparse.Namespace) -> str:
    if args.image:
        return ocr_image(Path(args.image))
    if args.text:
        return Path(args.text).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise OCRUnavailable("Pass --image, --text, or pipe OCR text on stdin.")


def _apply_overrides(candidate: OrderCandidate, args: argparse.Namespace) -> OrderCandidate:
    if args.item:
        candidate.item = args.item
    if args.price is not None:
        candidate.price = args.price
    if args.category:
        candidate.category = args.category
    if args.date:
        candidate.purchase_date = _parse_date(args.date)
    return candidate


def _parse_date(value: str) -> date:
    return date_parser.parse(value, fuzzy=True).date()


def _candidate_to_json(candidate: OrderCandidate) -> dict[str, object]:
    return {
        "item": candidate.item,
        "purchase_date": candidate.purchase_date.isoformat() if candidate.purchase_date else None,
        "price": candidate.price,
        "category": candidate.category,
        "lines": [
            {
                "item": line.item,
                "unit_price": line.unit_price,
                "quantity": line.quantity,
                "total_price": line.price,
                "category": line.category,
                "confidence": line.confidence,
            }
            for line in candidate.lines
        ],
        "confidence": candidate.confidence,
        "needs_purchase_date": candidate.needs_purchase_date,
        "notes": candidate.notes,
    }


if __name__ == "__main__":
    raise SystemExit(main())
