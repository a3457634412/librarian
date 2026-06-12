"""
语义检索
修复: 模型不再每次查询重新加载（Indexer 预编码 + 这里只读索引做余弦相似度）
"""
import json
import numpy as np
from pathlib import Path

from config import config


def cosine_similarity(vec1, vec2):
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    dot = np.dot(v1, v2)
    norm = np.linalg.norm(v1) * np.linalg.norm(v2)
    return dot / norm if norm > 0 else 0.0


class SemanticSearcher:
    def __init__(self, core_weight=None, recent_weight=None, archive_weight=None):
        self.config = config
        self.index_dir = Path(self.config["paths"]["librarian_dir"]) / "indexes"
        self.model = None
        self._indices = {}
        self._core_weight = core_weight
        self._recent_weight = recent_weight
        self._archive_weight = archive_weight

    def _get_model(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(
                self.config["index"]["embedding_model"],
                local_files_only=True,
            )
        return self.model

    def _load_index(self, name: str) -> dict | None:
        if name in self._indices:
            return self._indices[name]
        path = self.index_dir / f"{name}_index.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._indices[name] = json.load(f)
            return self._indices[name]
        return None

    def search(self, query: str, top_n: int = 20) -> list[tuple[str, float]]:
        """语义检索，返回 (article_id, score)"""
        model = self._get_model()
        query_vec = model.encode([query], show_progress_bar=False)[0]

        weights = {
            "core": self._core_weight if self._core_weight is not None else self.config["index"]["core_weight"],
            "recent": self._recent_weight if self._recent_weight is not None else self.config["index"]["recent_weight"],
            "archive": self._archive_weight if self._archive_weight is not None else self.config["index"]["archive_weight"],
        }

        results = []
        for layer_name, weight in weights.items():
            if weight == 0:
                continue
            idx = self._load_index(layer_name)
            if idx is None:
                continue

            for i, vec in enumerate(idx["vectors"]):
                sim = cosine_similarity(query_vec, vec)
                score = sim * weight
                if score > 0.15:  # 最低阈值
                    results.append((idx["ids"][i], score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_n]
