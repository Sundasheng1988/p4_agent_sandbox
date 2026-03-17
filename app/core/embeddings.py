from __future__ import annotations

from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer


_MODEL_CACHE: dict[str, SentenceTransformer] = {}

LOCAL_MODEL_PATH = "/home/sundasheng/models/all-MiniLM-L6-v2"


def get_model(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    key = LOCAL_MODEL_PATH
    if key not in _MODEL_CACHE:
        print(f"[EMBED] loading local model: {LOCAL_MODEL_PATH}")
        _MODEL_CACHE[key] = SentenceTransformer(LOCAL_MODEL_PATH, device="cpu")
        print(f"[EMBED] model loaded: {LOCAL_MODEL_PATH}")
    return _MODEL_CACHE[key]


def embed_texts(
    texts: List[str],
    model_name: str = "all-MiniLM-L6-v2",
    normalize: bool = True,
) -> np.ndarray:
    """
    批量生成文本向量。
    返回 shape: [N, D] 的 float32 numpy array
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    model = get_model(model_name)
    vectors = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=normalize,
    )

    if not isinstance(vectors, np.ndarray):
        vectors = np.asarray(vectors)

    return vectors.astype(np.float32)


def embed_query(
    query: str,
    model_name: str = "all-MiniLM-L6-v2",
    normalize: bool = True,
) -> np.ndarray:
    """
    单条 query 向量化。
    返回 shape: [D] 的 float32 numpy array
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")

    vectors = embed_texts(
        texts=[q],
        model_name=model_name,
        normalize=normalize,
    )
    return vectors[0]


def cosine_score(query_vec: np.ndarray, doc_vec: np.ndarray) -> float:
    """
    如果向量已 normalize，则点积即可视为 cosine similarity。
    如果未 normalize，也仍可正常计算标准 cosine。
    """
    if query_vec.ndim != 1:
        raise ValueError("query_vec must be 1D")
    if doc_vec.ndim != 1:
        raise ValueError("doc_vec must be 1D")
    if query_vec.shape[0] != doc_vec.shape[0]:
        raise ValueError("vector dim mismatch")

    q_norm = float(np.linalg.norm(query_vec))
    d_norm = float(np.linalg.norm(doc_vec))

    if q_norm == 0.0 or d_norm == 0.0:
        return 0.0

    return float(np.dot(query_vec, doc_vec) / (q_norm * d_norm))