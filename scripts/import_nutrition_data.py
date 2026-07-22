"""Validate a source-attributed nutrition CSV and write canonical JSON."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recipe_assistant.schemas.nutrition import RecipeNutritionData


_NUMERIC_FIELDS = (
    "serving_size",
    "calories_kcal",
    "protein_g",
    "fat_g",
    "carbohydrate_g",
    "fiber_g",
    "sodium_mg",
)


def _row_to_payload(row: dict[str, str]) -> dict:
    payload: dict = {
        "recipe_id": row.get("recipe_id", ""),
        "source": row.get("source", ""),
        "quality": row.get("quality", "UNKNOWN"),
        "calculation_version": row.get("calculation_version", ""),
        "food_categories": [
            item.strip()
            for item in row.get("food_categories", "").split("|")
            if item.strip()
        ],
    }
    for field_name in _NUMERIC_FIELDS:
        raw = row.get(field_name, "").strip()
        payload[field_name] = float(raw) if raw else None
    return payload


def import_csv(source_path: Path, target_path: Path) -> int:
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records = [RecipeNutritionData.model_validate(_row_to_payload(row)) for row in rows]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(
            [record.model_dump(mode="json") for record in records],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_csv", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/nutrition/recipes.json"),
    )
    args = parser.parse_args()
    count = import_csv(args.source_csv, args.output)
    print(f"Imported {count} nutrition records into {args.output}")


if __name__ == "__main__":
    main()
