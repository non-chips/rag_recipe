"""Manual embedding smoke test for the retained vector infrastructure."""

from rag.vector_store import embed_model


def main() -> None:
    vector = embed_model.embed_query("番茄炒鸡蛋")
    print(f"embedding dimensions: {len(vector)}")


if __name__ == "__main__":
    main()
