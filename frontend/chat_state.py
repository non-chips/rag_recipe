"""Pure state helpers shared by the Streamlit chat client and tests."""

from __future__ import annotations

from typing import Any


def merge_server_messages(
    local_messages: list[dict[str, Any]],
    server_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Use persisted history as truth while retaining local UI-only metadata."""

    local_by_message_id = {
        int(item["message_id"]): item
        for item in local_messages
        if item.get("message_id") is not None
    }
    merged: list[dict[str, Any]] = []
    for server_item in server_messages:
        message_id = int(server_item["id"])
        existing = local_by_message_id.get(message_id, {})
        merged.append(
            {
                **existing,
                "role": str(server_item["role"]).lower(),
                "content": str(server_item["content"]),
                "message_id": message_id,
                "created_at": server_item.get("created_at"),
            }
        )
    return merged
