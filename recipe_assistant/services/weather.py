"""Optional weather access behind injectable providers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


class WeatherContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    available: bool
    city: str = ""
    condition: str = ""
    temperature_c: str = ""
    humidity_percent: str = ""
    warning: str = ""


LocationProvider = Callable[[], str]
WeatherProvider = Callable[[str], Mapping[str, Any] | str]


class WeatherService:
    """Normalize legacy weather providers and degrade without raising."""

    def __init__(
        self,
        *,
        weather_provider: WeatherProvider | None = None,
        location_provider: LocationProvider | None = None,
    ) -> None:
        self.weather_provider = weather_provider
        self.location_provider = location_provider

    def get_current(self, city: str | None = None) -> WeatherContext:
        try:
            resolved_city = (city or "").strip()
            if not resolved_city and self.location_provider is not None:
                resolved_city = self.location_provider().strip()
            if not resolved_city or "未知" in resolved_city:
                return WeatherContext(available=False, warning="未获得可用城市")
            if self.weather_provider is None:
                return WeatherContext(
                    available=False,
                    city=resolved_city,
                    warning="天气服务未配置",
                )
            raw = self.weather_provider(resolved_city)
            data = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if data.get("success") is False:
                return WeatherContext(
                    available=False,
                    city=str(data.get("city") or resolved_city),
                    warning=str(data.get("message") or "天气查询失败"),
                )
            return WeatherContext(
                available=True,
                city=str(data.get("city") or resolved_city),
                condition=str(data.get("weather") or data.get("condition") or ""),
                temperature_c=str(data.get("temperature_c") or ""),
                humidity_percent=str(data.get("humidity_percent") or ""),
            )
        except Exception as exc:
            return WeatherContext(
                available=False,
                city=(city or "").strip(),
                warning=f"天气查询失败：{exc}",
            )

