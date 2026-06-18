"""
Librarian 数据模型 — Article + ArticleStore

所有模块读写的唯一数据源。底层 JSON，以后可换 SQLite。

Article 生命周期: ingested → tagged → curated → archived

用法:
  store = ArticleStore()
  store.ingest(raw_articles, date_str)
  store.update_tags(tagged_articles)
  store.mark_state(aid, "tagged")
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
    domain: str = ""           # agent / 其他
    core_content: str = ""     # 文章讲了什么 (50-100字)
    value_judgment: str = ""   # 可信度/趋势阶段 (50-80字)

    # 策展产出
    curation_decision: str = ""  # skip / merge / create
    curation_target: str = ""    # 目标 wiki 页面路径
    curation_rationale: str = "" # 决策理由

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
                art.domain = a.get("domain", "")
                art.core_content = a.get("core_content", "")
                art.value_judgment = a.get("value_judgment", "")
                art.state = "tagged"
        self._save()

    def update_curation(self, article_id: str, decision: str, target: str = "", rationale: str = ""):
        if article_id in self._articles:
            art = self._articles[article_id]
            art.curation_decision = decision
            art.curation_target = target
            art.curation_rationale = rationale
            art.state = "curated"
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

    def get_by_domain(self, domain: str, max_age_days: int = None) -> list[Article]:
        result = []
        for a in self._articles.values():
            if a.domain == domain:
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

    def search_keyword(self, query: str) -> list[tuple[Article, float]]:
        """简单关键词搜索。返回 (Article, score) 列表"""
        keywords = query.lower().split()
        scored = []
        for a in self._articles.values():
            text = f"{a.title} {a.core_content} {a.value_judgment}".lower()
            score = sum(text.count(kw) for kw in keywords)
            if score > 0:
                scored.append((a, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def all(self) -> list[Article]:
        return list(self._articles.values())

    def stats(self) -> dict:
        states = {"ingested": 0, "tagged": 0, "curated": 0, "archived": 0}
        for a in self._articles.values():
            states[a.state] = states.get(a.state, 0) + 1
        return {"total": len(self._articles), "by_state": states}