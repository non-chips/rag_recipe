"""Shared API DTO configuration."""

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
