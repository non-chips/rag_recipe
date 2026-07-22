# Nutrition data

`recipes.json` is intentionally empty until source-attributed nutrition records are imported.
Use `scripts/import_nutrition_data.py` with a UTF-8 CSV whose rows include `recipe_id`,
`source`, `quality`, and `calculation_version`. Numeric values without a source are rejected.

