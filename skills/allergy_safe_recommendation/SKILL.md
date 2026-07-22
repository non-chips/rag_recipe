---
name: allergy_safe_recommendation
version: "1.0.0"
description: Apply conservative safety behavior when allergies or excluded ingredients are present.
routes:
  - RECIPE_RECOMMENDATION
  - COMPLEX
signals:
  - ALLERGY_MENTIONED
  - EXCLUDED_INGREDIENT_PRESENT
priority: 100
risk: HIGH
requires: []
---

# Allergy-safe recommendation

## Rules

- Treat declared allergens and excluded ingredients as hard constraints.
- Send candidates through ConstraintService; this Skill never replaces hard filtering.
- Check every known candidate ingredient before presenting a recommendation.
- Reject candidates with a known conflict.
- If ingredient evidence is incomplete, do not claim that a recipe is absolutely safe.
- State which safety constraint was applied without exposing private profile details.
