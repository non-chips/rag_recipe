from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeWeather:
    """Offline replacement for location and current-weather access."""

    city: str = "测试市"
    weather: str = "晴"
    temperature_c: str = "22"

    def get_user_location(self) -> str:
        return self.city

    def get_weather(self, city: str) -> dict[str, str | bool]:
        return {
            "success": True,
            "city": city,
            "weather": self.weather,
            "temperature_c": self.temperature_c,
        }
