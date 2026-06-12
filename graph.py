"""
知识图谱管理模块
- 读取/写入 knowledge-graph.json
- 从 triples 重建 edges 索引（当前为空）
- 同步 triples + entities + nodes 一致性
"""

import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path


class KnowledgeGraph:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._empty()

    def _empty(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "version": 1,
            "triples": [],
            "entities": {},
            "nodes": {},
            "edges": [],
            "indexes": {
                "by_type": {"Fact": [], "Narrative": [], "Entity": [], "Emotion": [], "Tendency": [], "Tension": [], "Relationship": []},
                "by_entity": {},
                "by_status": {"active": [], "archived": []},
            },
            "updated": now,
        }

    def save(self):
        self.data["updated"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ── 实体映射 ──────────────────────────────────

    def _entity_id(self, name: str) -> str:
        h = hashlib.md5(name.encode()).hexdigest()[:10]
        return f"entity_{h}"

    def _ensure_entity(self, name: str):
        eid = self._entity_id(name)
        entities = self.data.setdefault("entities", {})
        if name not in entities:
            entities[name] = {"first_seen": datetime.now(timezone.utc).isoformat()}

        nodes = self.data.setdefault("nodes", {})
        if eid not in nodes:
            nodes[eid] = {
                "type": "Entity",
                "body": name,
                "entity_type": None,
                "created": datetime.now(timezone.utc).isoformat(),
                "updated": datetime.now(timezone.utc).isoformat(),
                "status": "active",
            }
            by_type = self.data.setdefault("indexes", {}).setdefault("by_type", {})
            by_type.setdefault("Entity", []).append(eid)
            by_status = self.data.setdefault("indexes", {}).setdefault("by_status", {})
            by_status.setdefault("active", []).append(eid)

        return eid

    # ── 修复 ──────────────────────────────────────

    def rebuild(self):
        """从 triples 重建 edges 和 by_entity 索引"""
        triples = self.data.get("triples", [])

        edges = []
        by_entity = {}

        for t in triples:
            subj = t["s"]
            obj = t["o"]

            self._ensure_entity(subj)
            self._ensure_entity(obj)

            edges.append({
                "from": self._entity_id(subj),
                "to": self._entity_id(obj),
                "predicate": t["p"],
                "confidence": t.get("confidence", 5),
                "evidence": t.get("evidence", ""),
            })

            by_entity.setdefault(subj, []).append({"predicate": t["p"], "object": obj})

        self.data["edges"] = edges
        self.data.setdefault("indexes", {})["by_entity"] = by_entity

    # ── 添加 ──────────────────────────────────────

    def add_triple(self, subject: str, predicate: str, obj: str, confidence: int = 5, evidence: str = ""):
        triple = {
            "s": subject,
            "p": predicate,
            "o": obj,
            "confidence": confidence,
            "evidence": evidence,
            "since": datetime.now().strftime("%Y-%m-%d"),
            "updated": datetime.now().strftime("%Y-%m-%d"),
            "access_count": 0,
        }
        self.data["triples"].append(triple)
        self._ensure_entity(subject)
        self._ensure_entity(obj)

        self.data.setdefault("edges", []).append({
            "from": self._entity_id(subject),
            "to": self._entity_id(obj),
            "predicate": predicate,
            "confidence": confidence,
            "evidence": evidence,
        })

        by_entity = self.data.setdefault("indexes", {}).setdefault("by_entity", {})
        by_entity.setdefault(subject, []).append({"predicate": predicate, "object": obj})

    # ── 查询 ──────────────────────────────────────

    def get_related(self, name: str) -> list[dict]:
        """获取与实体直接相关的所有关系"""
        result = []
        for t in self.data.get("triples", []):
            if t["s"] == name or t["o"] == name:
                result.append(t)
        return result

    def search(self, keyword: str) -> list[str]:
        """按关键词搜索实体名"""
        kw = keyword.lower()
        return [name for name in self.data.get("entities", {}) if kw in name.lower()]

    def stats(self) -> dict:
        return {
            "triples": len(self.data.get("triples", [])),
            "entities": len(self.data.get("entities", {})),
            "nodes": len(self.data.get("nodes", {})),
            "edges": len(self.data.get("edges", [])),
            "has_by_entity": len(self.data.get("indexes", {}).get("by_entity", {})) > 0,
        }


# ── CLI ───────────────────────────────────────────

if __name__ == "__main__":
    import sys
    kg = KnowledgeGraph("D:/obsidian/1/curated/knowledge-graph.json")

    if len(sys.argv) < 2:
        s = kg.stats()
        print(f"三元组: {s['triples']} | 实体: {s['entities']} | 节点: {s['nodes']} | 边: {s['edges']} | by_entity 索引: {'有' if s['has_by_entity'] else '空'}")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "fix":
        kg.rebuild()
        kg.save()
        s = kg.stats()
        print(f"修复完成: {s['triples']} 三元组 → {s['edges']} 条边 | by_entity: {'已重建' if s['has_by_entity'] else '失败'}")

    elif cmd == "related":
        name = sys.argv[2] if len(sys.argv) > 2 else "沈念项目"
        for t in kg.get_related(name):
            print(f"  {t['s']} → {t['p']} → {t['o']} ({t.get('confidence', '?')})")

    elif cmd == "search":
        kw = sys.argv[2] if len(sys.argv) > 2 else ""
        for name in kg.search(kw):
            rels = kg.get_related(name)
            print(f"  {name} ({len(rels)} 条关系)")

    elif cmd == "add":
        if len(sys.argv) < 5:
            print("用法: graph.py add <主体> <关系> <客体>")
        else:
            kg.add_triple(sys.argv[2], sys.argv[3], sys.argv[4])
            kg.save()
            print(f"已添加: {sys.argv[2]} → {sys.argv[3]} → {sys.argv[4]}")
