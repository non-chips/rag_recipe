---
name: weather_aware_recommendation
version: "1.0.0"
description: Use verified weather context as a soft recommendation feature with a clear fallback.
routes:
  - RECIPE_RECOMMENDATION
  - COMPLEX
signals:
  - WEATHER_CONTEXT_REQUIRED
priority: 60
risk: LOW
requires: []
---

# Weather-aware recommendation

## Rules

- Use weather only when it comes from the weather Tool Adapter for the requested city.
- Treat weather as a soft ranking feature, never as a hard safety constraint.
- Do not guess a city or current conditions.
- If weather is unavailable, disclose the fallback and continue with non-weather evidence.
- Recommendation reasons must still cite candidate evidence and ranking features.
