#递归扫描加载文件

import os
import hashlib

from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
)

from utils.logger_handler import logger


def get_file_md5_hex(filepath: str):
    if not os.path.exists(filepath):
        logger.error(f"[md5计算]文件{filepath}不存在")
        return None

    if not os.path.isfile(filepath):
        logger.error(f"[md5计算]路径{filepath}不是文件")
        return None

    md5_obj = hashlib.md5()
    chunk_size = 4096

    try:
        with open(filepath, "rb") as file:
            while chunk := file.read(chunk_size):
                md5_obj.update(chunk)

        return md5_obj.hexdigest()

    except Exception as exc:
        logger.error(
            f"计算文件{filepath}的MD5失败：{exc}"
        )
        return None


def listdir_with_allowed_type(
    path: str,
    allowed_types: tuple[str, ...],
) -> tuple[str, ...]:
    """
    递归查找目录下所有允许类型的文件。
    允许配置传入 md、txt 等不带点的后缀。
    """
    if not os.path.isdir(path):
        logger.error(
            f"[listdir_with_allowed_type]{path}不是文件夹"
        )
        return tuple()

    normalized_types = tuple(
        suffix.lower()
        if suffix.startswith(".")
        else f".{suffix.lower()}"
        for suffix in allowed_types
    )

    files: list[str] = []

    for root, _, filenames in os.walk(path):
        for filename in filenames:
            if filename.lower().endswith(normalized_types):
                files.append(os.path.join(root, filename))

    return tuple(sorted(files))


def pdf_loader(
    filepath: str,
    passwd=None,
) -> list[Document]:
    return PyPDFLoader(
        filepath,
        password=passwd,
    ).load()


def txt_loader(filepath: str) -> list[Document]:
    return TextLoader(
        filepath,
        encoding="utf-8",
        autodetect_encoding=True,
    ).load()


def markdown_loader(filepath: str) -> list[Document]:
    documents = TextLoader(
        filepath,
        encoding="utf-8",
        autodetect_encoding=True,
    ).load()

    for document in documents:
        document.metadata.update(
            {
                "file_type": "markdown",
                "recipe_file": os.path.basename(filepath),
                "source": filepath,
            }
        )

    return documents