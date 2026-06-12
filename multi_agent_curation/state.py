"""多 Agent 策展 — 共享状态定义"""


class CurationState:
    """在三个 Agent 间传递的状态。用 class 而非 TypedDict，兼容 DeepSeek 环境。"""

    def __init__(self, articles: list[dict], date_str: str):
        self.date_str = date_str
        self.articles = articles

        # Signal Agent 产出
        self.signals: list[dict] = []

        # Curation Agent 产出
        self.curation_plan: list[dict] = []

        # Wiki Agent 产出
        self.wiki_updates: list[dict] = []

        # 错误收集
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "date_str": self.date_str,
            "article_count": len(self.articles),
            "signals": self.signals,
            "curation_plan": self.curation_plan,
            "wiki_updates": self.wiki_updates,
            "errors": self.errors,
        }
