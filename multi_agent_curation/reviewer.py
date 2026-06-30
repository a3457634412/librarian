"""
策展质量评测 — 独立于管线运行

读取当天策展日志 → LLM 逐项评分 → 写 review.md + 更新 review_tracker.json

用法:
  python reviewer.py                     # 评测今天
  python reviewer.py 2026-06-03          # 评测指定日期
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI

from config import QWEN_API_KEY, QWEN_BASE_URL

_qwen_client = OpenAI(base_url=QWEN_BASE_URL, api_key=QWEN_API_KEY)


def _call_qwen(prompt: str, max_tokens: int = 3000, temperature: float = 0.2) -> str:
    resp = _qwen_client.chat.completions.create(
        model="qwen-plus",
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


LOG_DIR = Path("D:/Claude code/librarian/logs/curation")
TRACKER_FILE = LOG_DIR / "review_tracker.json"
WIKI_ROOT = Path("D:/obsidian/1/wiki")

REVIEW_PROMPT = """你是策展质量评测员。评估今天的策展效果。

评分要严格。每项 1-5 分，2-4 为常态，5 仅给例外。

## 今天的策展决策

__DECISIONS__

## 被修改的 wiki 页面

__WIKI_PAGES__

## 评测维度

### 过滤质量（满分 10）
- **precision**: 策展的文章是否都有实质价值？（1=很多噪音, 3=有干货有水分, 5=每个决策都有信息增量）
- **recall**: 有没有明显该策但没策的文章？（1=漏掉重要信息, 3=基本覆盖, 5=无一遗漏）

### 决策质量（满分 15）
- **decision_quality**: skip/merge/create 判断对不对？（1=多处错判, 3=基本合理, 5=全对）
- **conservatism**: 是否优先更新已有页面而非新建？（1=乱建新页面, 3=基本克制, 5=完美克制）
- **target_accuracy**: 写入的目标页面选对了吗？（1=指错地方, 3=基本对, 5=精准）

### 内容质量（满分 15）
- **content_quality**: 写的有没有知识增量？（1=水文, 3=有信息, 5=有洞察）
- **structure**: 插入位置是否正确？（1=乱塞, 3=基本对, 5=精准）
- **no_duplication**: 有没有写入重复内容？（1=明显重复, 3=基本不重复, 5=完美去重）

### 全局（满分 10）
- **overall_value**: 今天的策展对知识库有没有实质帮助？（1=浪费时间, 3=有点用, 5=非常有价值）

## 输出 JSON

{
  "date": "__DATE__",
  "overall_score": 0,
  "filter": {"precision": 0, "recall": 0, "total": 0, "note": ""},
  "decision": {"decision_quality": 0, "conservatism": 0, "target_accuracy": 0, "total": 0, "note": ""},
  "content": {"content_quality": 0, "structure": 0, "no_duplication": 0, "total": 0, "note": ""},
  "global": {"overall_value": 0, "total": 0, "note": ""},
  "flags": [],
  "suggestions": []
}

规则:
- 必须指出至少 1 条具体改进建议
- 4-5 分必须在 note 里给出明确理由
- flags 标注必须人工确认的项
- 只输出 JSON"""


def _build_decisions_text(date_str: str) -> str:
    """从策展日志提取决策"""
    log_file = LOG_DIR / date_str / "curation.json"
    if not log_file.exists():
        return "无策展日志"

    decisions = json.loads(log_file.read_text(encoding="utf-8"))
    lines = []
    for d in decisions:
        decision = d.get("decision", "?")
        status = d.get("status", "")
        emoji = {"written": "✅", "skipped": "⏭️", "write_failed": "❌"}.get(status, "")
        lines.append(f"- {emoji} [{decision}] {d.get('title', '?')[:80]}")
        lines.append(f"  理由: {d.get('rationale', '?')}")
        if d.get("target_page"):
            lines.append(f"  目标: {d['target_page']}")
        lines.append("")
    return "\n".join(lines)


def _build_wiki_diffs(date_str: str) -> str:
    """构建 wiki 修改前后对比"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", str(WIKI_ROOT), "diff", "--", "wiki/agent/"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:4000]
    except Exception:
        pass

    # fallback: 列出被修改的页面
    lines = []
    log_file = LOG_DIR / date_str / "curation.json"
    if log_file.exists():
        decisions = json.loads(log_file.read_text(encoding="utf-8"))
        from curator import read_wiki_page
        for d in decisions:
            target = d.get("target_page", "")
            if target and d.get("status") == "written":
                content = read_wiki_page(target)
                if content:
                    lines.append(f"### {target}\n\n{content[:1500]}\n")
    return "\n".join(lines)


def review_date(date_str: str = None) -> dict:
    """评测指定日期的策展质量"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    log_date_dir = LOG_DIR / date_str
    if not log_date_dir.exists():
        print(f"⚠️ 日志目录不存在: {log_date_dir}")
        return {}

    print(f"策展评测 — {date_str}")

    decisions_text = _build_decisions_text(date_str)
    wiki_pages_text = _build_wiki_diffs(date_str)

    prompt = REVIEW_PROMPT.replace("__DATE__", date_str)\
        .replace("__DECISIONS__", decisions_text)\
        .replace("__WIKI_PAGES__", wiki_pages_text[:3000])

    print("  评测中...")
    try:
        raw = _call_qwen(prompt, max_tokens=3000, temperature=0.2)
        review = json.loads(raw)
    except Exception:
        import re
        try:
            m = re.search(r'\{[\s\S]*\}', raw)
            review = json.loads(m.group(0)) if m else {}
        except Exception:
            print(f"  ⚠️ 解析失败")
            review = {"error": "parse failed", "date": date_str}

    if not review or not isinstance(review, dict):
        review = {"error": "parse failed", "date": date_str}

    # 计算总分
    for section in ["filter", "decision", "content"]:
        if section in review:
            sec = review[section]
            sec["total"] = sum(sec.get(k, 0) for k in sec if k != "total" and k != "note")
    if "global" in review:
        review["global"]["total"] = review["global"].get("overall_value", 0)

    total_possible = 10 + 15 + 15 + 10
    achieved = (
        review.get("filter", {}).get("total", 0) +
        review.get("decision", {}).get("total", 0) +
        review.get("content", {}).get("total", 0) +
        review.get("global", {}).get("total", 0)
    )
    review["overall_score"] = round(achieved / total_possible * 100) if total_possible > 0 else 0

    # 写入 review.md
    _write_review(log_date_dir, review, date_str)
    _update_tracker(review)
    _print_summary(review)

    return review


def _write_review(log_dir: Path, review: dict, date_str: str):
    lines = [
        f"# 策展评测 — {date_str}",
        f"",
        f"**总分**: {review.get('overall_score', '?')}/100",
        f"",
        "---",
        "",
        "## 过滤质量",
        f"- precision: {_stars(review, 'filter', 'precision')}",
        f"- recall: {_stars(review, 'filter', 'recall')}",
        f"- **小计**: {review.get('filter', {}).get('total', 0)}/10",
        f"> {review.get('filter', {}).get('note', '')}",
        "",
        "## 决策质量",
        f"- decision_quality: {_stars(review, 'decision', 'decision_quality')}",
        f"- conservatism: {_stars(review, 'decision', 'conservatism')}",
        f"- target_accuracy: {_stars(review, 'decision', 'target_accuracy')}",
        f"- **小计**: {review.get('decision', {}).get('total', 0)}/15",
        f"> {review.get('decision', {}).get('note', '')}",
        "",
        "## 内容质量",
        f"- content_quality: {_stars(review, 'content', 'content_quality')}",
        f"- structure: {_stars(review, 'content', 'structure')}",
        f"- no_duplication: {_stars(review, 'content', 'no_duplication')}",
        f"- **小计**: {review.get('content', {}).get('total', 0)}/15",
        f"> {review.get('content', {}).get('note', '')}",
        "",
        "## 全局",
        f"- overall_value: {_stars(review, 'global', 'overall_value')}",
        f"- **小计**: {review.get('global', {}).get('total', 0)}/10",
        f"> {review.get('global', {}).get('note', '')}",
        "",
    ]

    flags = review.get("flags", [])
    if flags:
        lines.append("## ⚠️ 需人工确认")
        for f in flags:
            lines.append(f"- [ ] {f}")
        lines.append("")

    suggestions = review.get("suggestions", [])
    if suggestions:
        lines.append("## 💡 优化建议")
        for s in suggestions:
            lines.append(f"- {s}")
        lines.append("")

    md_path = log_dir / "review.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  评测报告: {md_path}")


def _stars(review: dict, section: str, key: str) -> str:
    score = review.get(section, {}).get(key, 0)
    filled = "★" * score
    empty = "☆" * (5 - score)
    return f"{filled}{empty} ({score}/5)"


def _update_tracker(review: dict):
    tracker = {"daily": [], "trends": {}}
    if TRACKER_FILE.exists():
        try:
            tracker = json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    date_str = review.get("date", "")
    tracker["daily"] = [d for d in tracker.get("daily", []) if d.get("date") != date_str]

    entry = {
        "date": date_str,
        "overall_score": review.get("overall_score"),
        "filter_total": review.get("filter", {}).get("total"),
        "decision_total": review.get("decision", {}).get("total"),
        "content_total": review.get("content", {}).get("total"),
        "global_total": review.get("global", {}).get("total"),
    }
    tracker["daily"].append(entry)

    daily = tracker["daily"]
    if len(daily) >= 2:
        recent = daily[-7:]
        tracker["trends"] = {
            "avg_overall": round(sum(d["overall_score"] for d in recent) / len(recent)),
            "days_tracked": len(daily),
            "score_delta": daily[-1]["overall_score"] - daily[-2]["overall_score"] if len(daily) >= 2 else 0,
        }

    TRACKER_FILE.write_text(json.dumps(tracker, ensure_ascii=False, indent=2))


def _print_summary(review: dict):
    print(f"\n  {'='*40}")
    print(f"  总分: {review.get('overall_score', '?')}/100")
    print(f"  过滤:  {review.get('filter', {}).get('total', 0)}/10")
    print(f"  决策:  {review.get('decision', {}).get('total', 0)}/15")
    print(f"  内容:  {review.get('content', {}).get('total', 0)}/15")
    print(f"  全局:  {review.get('global', {}).get('total', 0)}/10")
    flags = review.get("flags", [])
    if flags:
        print(f"  ⚠️ {len(flags)} 条需人工确认")
    print(f"  {'='*40}")


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    review_date(date_str)
