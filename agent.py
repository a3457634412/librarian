"""
Librarian Agent — 主编排器

管线: 抓取 → tagger (过滤+摘要) → 写 Obsidian → 策展 → 归档

用法:
  python agent.py                        # 完整 cron 运行
  python agent.py 2026-05-30             # 指定日期
  python agent.py --manual --url "..."   # 手动投喂 URL
  python agent.py --manual --text "标题" "内容"  # 手动投喂文本
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from config import config

import fetch_sources
import tagger
import obsidian_writer
import curator
import archiver
from models import ArticleStore


def process_incoming(articles: list[dict], date_str: str, store: ArticleStore = None,
                     skip_write: bool = False, tagged_file: str = None):
    """
    统一处理入口 — 所有新文章无论来源都走这里。
    """
    if store is None:
        store = ArticleStore()

    # ── 1. 过滤 + 摘要 (只保留 agent 领域) ──
    print(f"  tagger: 过滤 + 摘要 ({len(articles)} 篇)...")
    tagged = tagger.summarize(articles)
    if not tagged:
        print("  ⚠️ 无 agent 领域文章")
        return []

    tagged_for_store = []
    for a in tagged:
        aid = store._make_id(date_str, a.get("title", ""))
        if store.get(aid):
            a["id"] = aid
            tagged_for_store.append(a)
    if tagged_for_store:
        store.update_tags(tagged_for_store)

    if tagged_file is None:
        tagged_file = str(Path(config["paths"]["data_dir"]) / f"{date_str}_tagged.json")
    json.dump(tagged, open(tagged_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ── 2. 写入 Obsidian ──
    if not skip_write:
        print("  写入 Obsidian...")
        obsidian_writer.write_daily_markdown(tagged_file, date_str)
    else:
        obsidian_writer.write_manual_markdown(tagged, date_str)

    # ── 3. 策展 ──
    try:
        cur = curator.Curator()
        cur.curate(tagged, date_str)
    except Exception as e:
        print(f"  ⚠️ 策展失败: {e}")

    # ── 4. 归档 ──
    try:
        archiver.archive(date_str)
    except Exception as e:
        print(f"  ⚠️ 归档失败: {e}")

    return tagged


def manual_ingest(url: str = None, text_title: str = None, text_content: str = None):
    """手动投喂入口"""
    from urllib.request import Request, urlopen

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    store = ArticleStore()

    if url:
        try:
            req = Request(url, headers={"User-Agent": "Librarian/1.0"})
            with urlopen(req, timeout=15) as resp:
                html = resp.read().decode(errors="ignore")
            m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            title = m.group(1).strip() if m else url.split("/")[-1] or url
            body = re.sub(r'<[^>]+>', ' ', html)
            body = re.sub(r'\s+', ' ', body)
            article = {
                "title": title, "url": url, "source": "手动投喂",
                "points": 0, "published_at": now.isoformat(), "summary": body[:500],
            }
        except Exception as e:
            print(f"  ⚠️ 抓取失败: {e}")
            return
        print(f"  手动投喂: {article['title']}")
    elif text_title and text_content:
        article = {
            "title": text_title, "url": "", "source": "手动投喂",
            "points": 0, "published_at": now.isoformat(), "summary": text_content[:500],
        }
    else:
        print("用法: --manual --url <URL> 或 --manual --text <标题> <内容>")
        return

    store.ingest([article], date_str)
    process_incoming([article], date_str, store=store, skip_write=True)
    print("  手动投喂完成")


def daily_run(date_str: str = None):
    """cron 每日完整管线"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    data_dir = Path(config["paths"]["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    store = ArticleStore()

    print(f"{'='*50}")
    print(f"  Librarian Agent — {date_str}")
    print(f"{'='*50}")

    # ── 补抓 + 抓取 ──
    print("\n[1/2] 抓取信源...")
    recovered = fetch_sources.retry_pending()
    if recovered:
        print(f"  补抓成功 {len(recovered)} 篇 → 入库")
        store.ingest(recovered, date_str)

    articles = fetch_sources.fetch_all()
    if not articles:
        print("  ⚠️ 所有信源返回空")
        return

    ingested_ids = store.ingest(articles, date_str)
    print(f"  ArticleStore: {len(ingested_ids)} 条新文章 (累计 {store.stats()['total']})")

    fetch_sources.save_raw(articles, date_str)

    # ── 统一处理 ──
    print(f"\n[2/2] 处理...")
    process_incoming(articles, date_str, store=store)

    print(f"\n{'='*50}")
    print(f"  完成 — {date_str}")
    s = store.stats()
    print(f"  ArticleStore: 共 {s['total']} 条 "
          f"(ingested:{s['by_state'].get('ingested', 0)} "
          f"tagged:{s['by_state'].get('tagged', 0)} "
          f"curated:{s['by_state'].get('curated', 0)} "
          f"archived:{s['by_state'].get('archived', 0)})")
    print(f"{'='*50}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        if len(sys.argv) > 3 and sys.argv[2] == "--url":
            manual_ingest(url=sys.argv[3])
        elif len(sys.argv) > 4 and sys.argv[2] == "--text":
            manual_ingest(text_title=sys.argv[3], text_content=" ".join(sys.argv[4:]))
        else:
            print("用法: python agent.py --manual --url <URL>")
            print("      python agent.py --manual --text <标题> <内容>")
    else:
        date_str = sys.argv[1] if len(sys.argv) > 1 else None
        daily_run(date_str)