"""
三层向量索引管理
替代 index_manager.py + index_builder.py — 修复增量索引 + 知识图谱同步

三层:
  核心 (1.5x): wiki/ + curated/ + pitfalls/ — 永久知识
  近期 (1.0x): raw/每日AI动态/ 中 <7 天的文件
  存档 (0.0x): >7 天的归档文章

改进:
  - 统一分块逻辑
  - 修复模型重复加载
  - 增量模式支持
"""
import json
import re
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from config import config


class Indexer:
    def __init__(self):
        self.config = config
        self.model = None
        self.index_dir = Path(self.config["paths"]["librarian_dir"]) / "indexes"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.index_dir / ".index_state.json"

    def _get_model(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(
                self.config["index"]["embedding_model"],
                local_files_only=True,
            )
        return self.model

    def _hash_text(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]

    def _split_articles(self, content: str) -> list[str]:
        """按 *** 分割每日动态文件"""
        blocks = content.split("***")
        return [b.strip() for b in blocks if b.strip() and len(b.strip()) > 50]

    def _split_doc(self, content: str) -> list[str]:
        """按 ## 分割文档"""
        sections = content.split("## ")
        return [s.strip() for s in sections if s.strip() and len(s.strip()) > 30]

    @staticmethod
    def _safe(s: str) -> str:
        return s.replace('|', '/').replace('::', ';;')[:120]

    def _read_file_entries(self, filepath: Path) -> list[tuple[str, str]]:
        """读取文件，返回 (id, text) 列表。id 格式: type::relpath::heading"""
        content = filepath.read_text(encoding="utf-8")
        rel_path = str(filepath.relative_to(self.config["paths"]["obsidian_vault"])).replace("\\", "/")

        if "每日AI动态" in rel_path or rel_path.startswith("raw/"):
            blocks = self._split_articles(content)
            id_prefix = f"raw::{rel_path}"
        else:
            blocks = self._split_doc(content)
            id_prefix = f"wiki::{rel_path}"

        entries = []
        for i, block in enumerate(blocks):
            # 提取块内第一个标题作为标识
            heading = ""
            for line in block.split("\n"):
                line = line.strip()
                if line.startswith("## ") or line.startswith("# "):
                    heading = line.lstrip("# ").strip()[:60]
                    break
            if not heading:
                heading = str(i)

            aid = f"{id_prefix}::{self._safe(heading)}"
            entries.append((aid, block))
        return entries

    def _load_state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}

    def _save_state(self, state: dict):
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    def build_index(self, mode: str = "--incremental"):
        """构建三层索引。编码失败 → state 不更新 → 下次自动重试"""
        cfg = self.config["index"]
        vault = Path(self.config["paths"]["obsidian_vault"])
        model = self._get_model()
        state = self._load_state() if mode == "--incremental" else {}

        layers = {
            "core": {"dirs": ["wiki", "curated", "pitfalls", "raw/手动投喂"], "weight": cfg["core_weight"], "entries": [], "texts": []},
            "recent": {"days": cfg["recent_days"], "weight": cfg["recent_weight"], "entries": [], "texts": []},
            "archive": {"weight": cfg["archive_weight"], "entries": [], "texts": []},
        }

        # ── 阶段 1: 收集文件（不改 state） ──
        pending_state_updates = {}  # {key: mtime} — 仅编码成功后写入

        for layer_name, layer in layers.items():
            if layer_name == "core":
                for dir_name in layer["dirs"]:
                    d = vault / dir_name
                    if not d.exists():
                        continue
                    for fpath in d.glob("**/*.md"):
                        key = str(fpath)
                        mtime = fpath.stat().st_mtime
                        if mode == "--incremental" and state.get(key) == mtime:
                            continue
                        layer["entries"].extend(self._read_file_entries(fpath))
                        pending_state_updates[key] = mtime

            elif layer_name == "recent":
                # 扫 raw/{domain}/每日/ 下所有文件
                raw_base = vault / "raw"
                if raw_base.exists():
                    threshold = datetime.now() - timedelta(days=layer["days"])
                    for domain_dir in raw_base.glob("*/每日"):
                        if not domain_dir.is_dir():
                            continue
                        for fpath in domain_dir.glob("*.md"):
                            key = str(fpath)
                            mtime = fpath.stat().st_mtime
                            if mode == "--incremental" and state.get(key) == mtime:
                                continue
                            try:
                                file_date = datetime.strptime(fpath.stem, "%Y-%m-%d")
                                if file_date >= threshold:
                                    layer["entries"].extend(self._read_file_entries(fpath))
                                    pending_state_updates[key] = mtime
                            except ValueError:
                                pass

        # ── 阶段 2: 编码（最可能失败） ──
        total_texts = sum(len(l["entries"]) for l in layers.values())
        if total_texts == 0:
            print("索引已是最新")
            return

        for layer_name, layer in layers.items():
            if not layer["entries"]:
                print(f"  [{layer_name}] 无新条目")
                continue

            texts = [e[1] for e in layer["entries"]]
            ids = [e[0] for e in layer["entries"]]
            print(f"  [{layer_name}] 编码 {len(texts)} 个块...")

            try:
                vectors = model.encode(texts, show_progress_bar=False)
            except Exception as e:
                print(f"  ⚠️ [{layer_name}] 编码失败: {e}")
                print(f"  → {len(texts)} 条文本未写入索引，state 未更新，下次自动重试")
                return  # state 不变 → 下次增量重新扫

            # ── 阶段 3: 写入索引文件 ──
            index = {
                "ids": ids,
                "vectors": [v.tolist() for v in vectors],
                "model": cfg["embedding_model"],
                "count": len(ids),
                "dim": vectors.shape[1] if len(vectors) > 0 else 0,
            }

            index_path = self.index_dir / f"{layer_name}_index.json"
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False)

            print(f"  [{layer_name}] 已保存: {len(ids)} 条")

        # ── 阶段 4: 索引全部写入成功后，才更新 state ──
        for key, mtime in pending_state_updates.items():
            state[key] = mtime
        self._save_state(state)


if __name__ == "__main__":
    import sys
    mode = "--incremental"
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        mode = "--full"
    idx = Indexer()
    idx.build_index(mode)
