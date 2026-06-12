"""
Librarian 数据模型 — Article + ArticleStore

所有模块读写的唯一数据源。底层 JSON，以后可换 SQLite 而不影响调用方。

Article 生命周期:
  ingested → tagged → indexed → archived

用法:
  store = ArticleStore()
  store.ingest(raw_articles, date_str)          # fetch 产出
  untagged = store.get_by_state("ingested")      # tagger 读取
  store.update_tags(article_id, tag_fields)      # tagger 写入
  store.mark_state(article_id, "tagged")
"""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

STORE_PATH = Path(__file__).parent / "articles.json"


@dataclass
class Article:
    id: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    points: int = 0
    published_at: str = ""

    # tagger 产出
    tech_tag: str = ""
    maturity_tag: str = ""
    relevance: str = ""
    tech_summary: str = ""
    trend_signal: str = ""
    relevance_to_me: str = ""

    # 信号分级 (新)
    signal_level: str = "green"

    # 关联阶段
    related_notes: list[str] = field(default_factory=list)
    collision_verdict: str = ""

    # 生命周期
    date: str = ""
    state: str = "ingested"


class ArticleStore:
    def __init__(self, path: Path = STORE_PATH):
        self.path = path
        self._articles: dict[str, Article] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._articles = {
                k: Article(**v) for k, v in data.get("articles", {}).items()
            }

    def _save(self):
        data = {
            "updated": datetime.now().isoformat(),
            "count": len(self._articles),
            "articles": {k: asdict(v) for k, v in self._articles.items()},
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _make_id(date_str: str, title: str) -> str:
        h = hashlib.md5(f"{date_str}::{title}".encode()).hexdigest()[:10]
        return f"{date_str}::{h}"

    # ── 写入 ──

    def ingest(self, raw_articles: list[dict], date_str: str) -> list[str]:
        """批量入库。返回新创建的 article_id 列表"""
        ids = []
        for a in raw_articles:
            aid = self._make_id(date_str, a.get("title", ""))
            if aid in self._articles:
                continue
            article = Article(
                id=aid,
                title=a.get("title", ""),
                url=a.get("url", ""),
                source=a.get("source", ""),
                points=a.get("points", 0),
                published_at=a.get("published_at", ""),
                date=date_str,
                state="ingested",
            )
            self._articles[aid] = article
            ids.append(aid)
        self._save()
        return ids

    def update_tags(self, tagged: list[dict]):
        """批量更新标签字段"""
        for a in tagged:
            aid = a.get("id", "")
            if aid and aid in self._articles:
                art = self._articles[aid]
                art.tech_tag = a.get("tech_tag", "")
                art.maturity_tag = a.get("maturity_tag", "")
                art.relevance = a.get("relevance", "")
                art.tech_summary = a.get("tech_summary", "")
                art.trend_signal = a.get("trend_signal", "")
                art.relevance_to_me = a.get("relevance_to_me", "")
                art.signal_level = a.get("signal_level", "green")
                art.state = "tagged"
        self._save()

    def update_collision(self, article_id: str, verdict: str):
        if article_id in self._articles:
            self._articles[article_id].collision_verdict = verdict
            self._save()

    def add_related(self, article_id: str, notes: list[str]):
        if article_id in self._articles:
            self._articles[article_id].related_notes = notes
            self._save()

    def mark_state(self, article_id: str, new_state: str):
        if article_id in self._articles:
            self._articles[article_id].state = new_state
            self._save()

    def mark_archived(self, article_ids: list[str]):
        for aid in article_ids:
            if aid in self._articles:
                self._articles[aid].state = "archived"
        self._save()

    # ── 查询 ──

    def get(self, article_id: str) -> Optional[Article]:
        return self._articles.get(article_id)

    def get_by_state(self, state: str) -> list[Article]:
        return [a for a in self._articles.values() if a.state == state]

    def get_by_date(self, date_str: str) -> list[Article]:
        return [a for a in self._articles.values() if a.date == date_str]

    def get_by_tag(self, tech_tag: str, max_age_days: int = None) -> list[Article]:
        result = []
        for a in self._articles.values():
            if tech_tag.lower() in a.tech_tag.lower():
                if max_age_days is None:
                    result.append(a)
                else:
                    try:
                        d = datetime.strptime(a.date, "%Y-%m-%d")
                        age = (datetime.now() - d).days
                        if age <= max_age_days:
                            result.append(a)
                    except ValueError:
                        pass
        return result

    def get_relevant(self, date_str: str = None) -> list[Article]:
        """取核心相关或可能相关的文章"""
        result = []
        for a in self._articles.values():
            if date_str and a.date != date_str:
                continue
            if a.relevance in ("#核心相关", "#可能与我的部署相关"):
                result.append(a)
        return result

    def search_keyword(self, query: str) -> list[tuple[Article, float]]:
        """简单关键词搜索。返回 (Article, score) 列表"""
        keywords = query.lower().split()
        scored = []
        for a in self._articles.values():
            text = f"{a.title} {a.tech_summary} {a.trend_signal} {a.tech_tag}".lower()
            score = sum(text.count(kw) for kw in keywords)
            if score > 0:
                scored.append((a, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def all(self) -> list[Article]:
        return list(self._articles.values())

    def stats(self) -> dict:
        states = {"ingested": 0, "tagged": 0, "indexed": 0, "archived": 0}
        for a in self._articles.values():
            states[a.state] = states.get(a.state, 0) + 1
        return {"total": len(self._articles), "by_state": states}
