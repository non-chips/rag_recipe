from __future__ import annotations

import sys
from types import ModuleType

from langchain_core.documents import Document

from fakes import FakeChatModel, FakeVectorStoreService


def test_rag_retrieves_context_and_invokes_chat_model(
    monkeypatch,
    fresh_import,
) -> None:
    documents = [
        Document(
            page_content="白灼虾：水开后放入虾，煮熟后捞出。",
            metadata={"recipe_id": "recipe-shrimp", "source": "白灼虾.md"},
        )
    ]
    vector_service = FakeVectorStoreService(documents)
    fake_model = FakeChatModel(response_text="白灼虾离线基线回答")

    vector_module = ModuleType("rag.vector_store")
    vector_module.VectorStoreService = lambda: vector_service
    model_module = ModuleType("model.factory")
    model_module.chat_model = fake_model

    monkeypatch.setitem(sys.modules, "rag.vector_store", vector_module)
    monkeypatch.setitem(sys.modules, "model.factory", model_module)

    rag_module = fresh_import("rag.rag_service")
    service = rag_module.RagSummarizeService()

    assert service.retriever_docs("白灼虾怎么做？") == documents
    assert service.rag_summarize("白灼虾怎么做？") == "白灼虾离线基线回答"
    assert fake_model.invocation_count == 1
    assert vector_service.retriever.queries[-1][0] == "白灼虾怎么做？"
