"""
四路信源抓取 + 去重

Simon Willison — 个人博客，工程视角
GitHub       — 多个细分 query，按更新时间排，抓早期项目
Hacker News  — 多个细分 query，提高质量门槛
Arxiv        — 论文源，agent + LLM 方向
"""
import json
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from difflib import SequenceMatcher

from config import config

PENDING_FILE = Path(__file__).parent / ".pending_fetches.json"


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _load_pending():
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    return []


def _save_pending(items):
    PENDING_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_with_retry(fn, source_name, max_tries=3, wait_seconds=30):
    for i in range(max_tries):
        try:
            result = fn()
            if result:
                return result
        except Exception as e:
            print(f"  [{source_name}] 第{i+1}次尝试失败: {e}")
        if i < max_tries - 1:
            time.sleep(wait_seconds)

    print(f"  [{source_name}] {max_tries}次全部失败，已标记下次优先处理")
    pending = _load_pending()
    pending.append({"source": source_name, "date": datetime.now().strftime("%Y-%m-%d"), "attempts_left": 2})
    _save_pending(pending)
    return []


def retry_pending():
    pending = _load_pending()
    if not pending:
        return []
    print(f"  补抓 {len(pending)} 个之前失败的源...")
    recovered = []
    still_failed = []
    for item in pending:
        source = item["source"]
        try:
            if source == "simon":
                result = _fetch_with_retry(lambda: fetch_simon(config["sources"]["simon"]["max_articles"]), "simon")
            elif source == "github":
                result = _fetch_with_retry(lambda: fetch_github(config["sources"]["github"]), "github")
            elif source == "hn":
                result = _fetch_with_retry(lambda: fetch_hn(config["sources"]["hn"]), "hn")
            elif source == "arxiv":
                result = _fetch_with_retry(lambda: fetch_arxiv(config["sources"]["arxiv"]), "arxiv")
            else:
                continue
        except Exception:
            result = []
        if result:
            recovered.extend(result)
        else:
            still_failed.append(item)
    _save_pending(still_failed)
    if recovered:
        print(f"  已补抓 {len(recovered)} 篇")
    return recovered


# ── Simon Willison ──────────────────────────────────

def fetch_simon(max_articles: int = 5) -> list[dict]:
    articles = []
    try:
        with urlopen(Request("https://simonwillison.net/atom/entries/"), timeout=30) as resp:
            content = resp.read().decode()
        entries = content.split("<entry>")[1:]
        for entry in entries[:max_articles]:
            title = link = published = ""
            if "<title>" in entry:
                title = entry.split("<title>")[1].split("</title>")[0].strip()
            if '<link rel="alternate" href="' in entry:
                link = entry.split('<link rel="alternate" href="')[1].split('"')[0]
            elif "<link href=" in entry:
                link = entry.split('<link href="')[1].split('"')[0].strip()
            if "<published>" in entry:
                published = entry.split("<published>")[1].split("</published>")[0].strip()
            if title:
                articles.append({
                    "title": title, "url": link, "source": "Simon Willison",
                    "points": 0, "published_at": published, "summary": "",
                })
    except Exception as e:
        print(f"  [Simon Willison] 抓取失败: {e}")
    return articles


# ── GitHub ──────────────────────────────────────────

def fetch_github(cfg: dict) -> list[dict]:
    """多个细分 query，按更新时间排序，抓早期项目"""
    articles = []
    for query in cfg["queries"]:
        q = urllib.parse.quote(query)
        url = (f"https://api.github.com/search/repositories"
               f"?q={q}+stars:>{cfg['min_stars']}&sort={cfg['sort']}"
               f"&order=desc&per_page={cfg['per_query']}")
        try:
            req = Request(url, headers={"User-Agent": "librarian-fetcher"})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            for item in data.get("items", []):
                articles.append({
                    "title": item.get("full_name", ""),
                    "url": item.get("html_url", ""),
                    "source": "GitHub",
                    "points": item.get("stargazers_count", 0),
                    "published_at": item.get("created_at", ""),
                    "summary": item.get("description") or "",
                })
        except Exception as e:
            print(f"  [GitHub:{query[:30]}] 抓取失败: {e}")
    return articles


# ── Hacker News ─────────────────────────────────────

def fetch_hn(cfg: dict) -> list[dict]:
    """多个细分 query，提高质量门槛"""
    articles = []
    for query in cfg["queries"]:
        q = urllib.parse.quote(query)
        url = (f"https://hn.algolia.com/api/v1/search_by_date"
               f"?query={q}&tags=({cfg['tags']})"
               f"&numericFilters=points>{cfg['min_points']}"
               f"&hitsPerPage={cfg['per_query']}")
        try:
            req = Request(url, headers={"User-Agent": "librarian-fetcher"})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            for item in data.get("hits", []):
                title = item.get("title", "")
                url_val = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}"
                articles.append({
                    "title": title,
                    "url": url_val,
                    "source": "Hacker News",
                    "points": item.get("points", 0),
                    "published_at": item.get("created_at", ""),
                    "summary": "",
                })
        except Exception as e:
            print(f"  [HN:{query[:30]}] 抓取失败: {e}")
    return articles


# ── Arxiv ───────────────────────────────────────────

def fetch_arxiv(cfg: dict) -> list[dict]:
    """论文源：agent + LLM"""
    import ssl
    articles = []
    for query in cfg["queries"]:
        q = urllib.parse.quote(query)
        url = (f"https://export.arxiv.org/api/query"
               f"?search_query=all:{q}&sortBy=submittedDate&sortOrder=descending"
               f"&max_results={cfg['per_query']}")
        try:
            req = Request(url, headers={"User-Agent": "librarian-fetcher"})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urlopen(req, timeout=30, context=ctx) as resp:
                content = resp.read().decode()
            entries = content.split("<entry>")[1:]
            for entry in entries:
                title = link = published = summary = ""
                if "<title>" in entry:
                    title = entry.split("<title>")[1].split("</title>")[0].strip()
                if "<id>" in entry:
                    link = entry.split("<id>")[1].split("</id>")[0].strip()
                if "<published>" in entry:
                    published = entry.split("<published>")[1].split("</published>")[0].strip()
                if "<summary>" in entry:
                    summary = entry.split("<summary>")[1].split("</summary>")[0].strip()[:300]
                if title:
                    articles.append({
                        "title": title,
                        "url": link,
                        "source": "Arxiv",
                        "points": 0,
                        "published_at": published,
                        "summary": summary,
                    })
        except Exception as e:
            print(f"  [Arxiv:{query[:30]}] 抓取失败: {e}")
    return articles


# ── 去重 ────────────────────────────────────────────

def deduplicate(articles: list[dict], threshold: float = 0.85) -> list[dict]:
    result = []
    for a in articles:
        dup = False
        for existing in result:
            if a["url"] == existing["url"]:
                dup = True
                break
            if title_similarity(a["title"], existing["title"]) > threshold:
                dup = True
                break
        if not dup:
            result.append(a)
    return result


# ── 主入口 ──────────────────────────────────────────

def fetch_all() -> list[dict]:
    sources = config["sources"]

    print("[1/4] 抓取信源...")

    simon = _fetch_with_retry(lambda: fetch_simon(sources["simon"]["max_articles"]), "simon")
    print(f"  Simon Willison: {len(simon)} 篇")

    github = _fetch_with_retry(lambda: fetch_github(sources["github"]), "github")
    print(f"  GitHub: {len(github)} 篇")

    hn = _fetch_with_retry(lambda: fetch_hn(sources["hn"]), "hn")
    print(f"  Hacker News: {len(hn)} 篇")

    arxiv = _fetch_with_retry(lambda: fetch_arxiv(sources["arxiv"]), "arxiv")
    print(f"  Arxiv: {len(arxiv)} 篇")

    all_articles = simon + github + hn + arxiv
    print(f"  合并: {len(all_articles)} 篇")

    if not all_articles:
        print("  ⚠️ 所有信源无结果")
        return []

    deduped = deduplicate(all_articles, config["dedup"]["title_similarity_threshold"])
    removed = len(all_articles) - len(deduped)
    if removed:
        print(f"  去重: 去除 {removed} 篇 → {len(deduped)} 篇")

    return deduped


def save_raw(articles: list[dict], date_str: str = None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    data_dir = Path(config["paths"]["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_file = data_dir / f"{date_str}_raw.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {raw_file}")
    return raw_file


if __name__ == "__main__":
    articles = fetch_all()
    if articles:
        save_raw(articles)
    else:
        print("所有信源返回空，退出")
