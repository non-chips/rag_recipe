---
name: ingredient_substitution
version: "1.0.0"
description: Ground ingredient substitutions in recipe evidence and re-check safety constraints.
routes:
  - RECIPE_KNOWLEDGE
  - RECIPE_RECOMMENDATION
  - COMPLEX
signals:
  - SUBSTITUTION_REQUESTED
priority: 80
risk: MEDIUM
requires: []
---

# Ingredient substitution

## Rules

- Use recipe evidence for the substitute, expected function and changed cooking behavior.
- Do not invent an exact ratio when the source does not provide one.
- Re-run allergen, excluded-ingredient, appliance and time constraints after substitution.
- Explain uncertainty when the substitution may change texture, flavor or cooking time.
