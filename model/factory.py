#创建DeepSeek Chat模型和加载本地BGE Embedding模型

import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings

from utils.config_handler import rag_conf

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def resolve_project_path(path_value: str) -> str:
    path = Path(path_value)

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return str(path.resolve())

class BaseModelFactory(ABC):

    @abstractmethod
    def generator(self):
        raise NotImplementedError


class ChatModelFactory(BaseModelFactory):

    def generator(self) -> Optional[BaseChatModel]:
        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise ValueError(
                f"未读取到环境变量 DEEPSEEK_API_KEY,"
                "请检查 Windows 用户环境变量并重启终端。"
            )

        return ChatOpenAI(
            model=rag_conf.get(
                "chat_model_name",
                "deepseek-v4-flash",
            ),
            api_key=api_key,
            base_url=rag_conf.get(
                "chat_base_url",
                "https://api.deepseek.com",
            ),
            temperature=float(
                rag_conf.get("temperature", 0.2)
            ),
            timeout=60,
            max_retries=2,
        )


class EmbeddingsFactory(BaseModelFactory):

    def generator(self) -> Optional[Embeddings]:
        model_path = resolve_project_path(
            rag_conf.get(
                "embedding_model_path",
                "model/embeddingmodels/bge-small-zh-v1.5",
            )
        )

        if not os.path.isdir(model_path):
            raise FileNotFoundError(
                f"本地嵌入模型目录不存在：{model_path}"
            )

        return HuggingFaceEmbeddings(
            model_name=model_path,
            model_kwargs={
                "device": rag_conf.get(
                    "embedding_device",
                    "cpu",
                ),
                "local_files_only": True,
            },
            encode_kwargs={
                "normalize_embeddings": True,
            },
        )


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()
