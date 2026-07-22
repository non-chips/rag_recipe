---
name: source_aware_nutrition_report
version: "1.0.0"
description: Build nutrition reports from confirmed meals and source-quality metadata without medical claims.
routes:
  - NUTRITION_PLANNING
  - COMPLEX
signals:
  - NUTRITION_REPORT_REQUESTED
priority: 70
risk: LOW
requires: []
---

# Source-aware nutrition report

## Rules

- Calculate only from confirmed meal records and structured nutrition data.
- Preserve source, data-quality and coverage fields in the report.
- When precise metrics are unavailable, provide food-category diversity only.
- Do not convert incomplete nutrition data into exact totals.
- Do not provide a medical diagnosis or treatment advice.
