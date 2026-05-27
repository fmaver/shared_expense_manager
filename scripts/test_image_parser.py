#!/usr/bin/env python
"""Manual test script for image_expense_parser.

Usage:
    GEMINI_API_KEY=<key> python scripts/test_image_parser.py path/to/receipt.jpg
    GEMINI_API_KEY=<key> python scripts/test_image_parser.py *.png
"""

import mimetypes
import os
import sys
from pathlib import Path

# Ensure src/ is on the path when run from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from template.service_layer.image_expense_parser import (  # noqa: E402
    GEMINI_MODEL,
    parse_image_expense,
)


def _mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "image/jpeg"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_image_parser.py <image1> [image2 ...]")
        sys.exit(1)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable first.")
        sys.exit(1)

    categories = ["comida", "supermercado", "entretenimiento", "servicios", "transporte", "viajes", "salud", "otros"]
    print(f"Model: {GEMINI_MODEL}\n")

    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"[SKIP] {path} — file not found")
            continue

        mime = _mime_for(path)
        image_bytes = path.read_bytes()
        print(f"--- {path.name} ({len(image_bytes):,} bytes, {mime}) ---")

        result = parse_image_expense(image_bytes, mime, categories)
        if result is None:
            print("  Result: FAILED — could not parse (amount missing or API error)\n")
        else:
            print(f"  Amount:       ${result.amount:,.2f}")
            print(f"  Description:  {result.description}")
            print(f"  Date:         {result.expense_date}")
            print(f"  Category:     {result.category}")
            print(f"  Payment type: {result.payment_type}")
            print(f"  Confidence:   {result.confidence}")
            print()


if __name__ == "__main__":
    main()
