"""
wiki 自动更新 — raw → wiki 知识提炼

替代旧版机械追加链接。新逻辑:
  1. 按 tech_tag 分组当天文章
  2. 读对应 wiki 页当前内容
  3. LLM 判断每篇价值: 替代 / 补充 / 冲突 / 跳过
  4. LLM 重写 wiki 页（只改受影响的段落，保持结构）
  5. 写回 wiki + 记录 changelog
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import config, DEEPSEEK_API_KEY


def _call_llm(prompt: str, max_tokens: int = 3000) -> str:
    api_key = DEEPSEEK_API_KEY
    if not api_key:
        return ""
    body = {
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        req = Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            return choices[0].get("message", {}).get("content", "") if choices else ""
    except Exception as e:
        print(f"  ⚠️ LLM 调用失败: {e}")
        return ""


UPDATE_PROMPT = """你是知识库维护助手。下面是当前 wiki 页面的内容，以及近期该领域的新文章。

## 当前 wiki
{current_content}

## 新文章（每条含标题、技术拆解、趋势判断、对你意味着什么）
{articles_text}

## 你的任务

逐条判断每篇文章对 wiki 的价值：

1. **替代**: 新方案比 wiki 里已有的方案更好（有具体数据/指标支撑，或解决同一问题但在某维度明显更优）→ 重写受影响的段落，融入新方案
2. **补充**: wiki 没覆盖的新方向/新工具/新实践 → 在合适位置插入新段落（3-5 句话）
3. **冲突**: 新结论和 wiki 矛盾 → 不改原内容，在末尾加 ⚠️ 冲突标记段落
4. **跳过**: wiki 已有 或 质量不够 或 与 wiki 主题不直接相关 → 不动

输出格式：

```
## 判断
- [文章标题]: 替代 | 理由: xxx
- [文章标题]: 补充 | 理由: xxx
- [文章标题]: 跳过 | 理由: xxx

## 更新后的 wiki 全文
（输出完整的更新后的 wiki 页面，markdown 格式）
```

规则：
- wiki 的结构、格式、frontmatter 保留不变
- 只改需要改的段落，不要重写整篇
- 新增内容控制在 3-5 句话，融入现有结构，不要堆在末尾
- 不要删除已有的高质量内容
- 如果已有内容本身就是优质手写稿，改动要极其克制
- 如果没有任何值得改的，输出 "## 判断\\n全部跳过\\n\\n## 更新后的 wiki 全文\\n（无变化）"
- 禁止在 wiki 末尾追加纯链接列表"""


class WikiUpdater:
    def __init__(self):
        self.config = config
        self.vault = Path(self.config["paths"]["obsidian_vault"])
        self.mapping = self.config.get("wiki_pages", {})
        self.log_file = Path(self.config["paths"]["librarian_logs"]) / "wiki_updates.log"
        self.updates = []

    def maintain_all_links(self):
        """全量维护所有 wiki 页面的 [[双向链接]]：修断链 + 补新链"""
        wiki_root = self.vault / "wiki"
        if not wiki_root.exists():
            return
        pages = list(wiki_root.glob("**/*.md"))
        fixed = 0
        for p in pages:
            rel = str(p.relative_to(self.vault))
            self._link_related(p, rel)
            fixed += 1
        print(f"  已维护 {fixed} 个页面的链接")

    def _log(self, msg: str):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")

    def _link_related(self, page_path: Path, page_rel: str):
        """自动维护 [[双向链接]]：补断链 + 找相似 + 更新 ## 相关 段落"""
        content = page_path.read_text(encoding="utf-8")

        # ── 1. 修复文中已有的断链 ──
        links = re.findall(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', content)
        for old_link in links:
            target = self._resolve_wiki_link(old_link, page_path)
            if target and target != page_path and target.exists():
                continue  # 链接有效
            # 尝试在当前同目录下找同名文件
            fixed = self._find_wiki_page(old_link.split("/")[-1], page_path)
            if fixed:
                old_pattern = f"[[{old_link}"
                new_link = str(fixed.relative_to(self.vault)).replace("\\", "/").replace(".md", "")
                content = content.replace(f"[[{old_link}", f"[[{new_link}")

        # ── 2. 找最相似的 wiki 页面 ──
        words = set(re.findall(r'[a-zA-Z一-鿿]{2,}', content))
        stopwords = {"the", "and", "for", "with", "that", "this", "are", "from", "can",
                     "的", "是", "在", "了", "和", "与", "或", "不", "也", "就", "都", "要", "有", "会", "可以"}
        keywords = words - stopwords

        wiki_root = self.vault / "wiki" / page_rel.split("/")[0]
        candidates = []
        for md in wiki_root.glob("**/*.md"):
            if md == page_path:
                continue
            try:
                other = md.read_text(encoding="utf-8")
            except Exception:
                continue
            hits = sum(1 for kw in keywords if kw in other)
            if hits > 5:
                candidates.append((hits, md.stem, md))

        candidates.sort(reverse=True)
        related_links = []
        seen = set()
        for _, stem, md_path in candidates[:5]:
            if stem not in seen:
                seen.add(stem)
                # 计算相对路径
                try:
                    link_path = str(md_path.relative_to(page_path.parent)).replace("\\", "/").replace(".md", "")
                except ValueError:
                    link_path = str(md_path.relative_to(self.vault)).replace("\\", "/").replace(".md", "")
                related_links.append(f"- [[{link_path}|{stem}]]")

        if not related_links:
            return

        # ── 3. 写回 ──
        related_section = "\n## 相关\n\n" + "\n".join(related_links) + "\n"
        if "## 相关" in content:
            content = re.sub(r'## 相关\n[\s\S]*?(?=\n## |\Z)', "", content)
            content = content.rstrip()
        content = content.rstrip() + "\n\n" + related_section

        page_path.write_text(content, encoding="utf-8")

    def _resolve_wiki_link(self, link: str, from_path: Path) -> Path | None:
        """把 [[target]] 解析为文件路径"""
        target = link.split("|")[0].replace("/", "\\") + ".md"
        # 尝试相对路径
        candidate = (from_path.parent / target).resolve()
        if candidate.exists():
            return candidate
        # 尝试从 vault 根
        candidate = (self.vault / target).resolve()
        if candidate.exists():
            return candidate
        return None

    def _find_wiki_page(self, name: str, near: Path) -> Path | None:
        """在同领域目录中找名为 name 的 .md 文件"""
        wiki_root = self.vault / "wiki"
        for md in wiki_root.glob("**/*.md"):
            if md.stem == name:
                return md
        return None

    def _format_articles(self, articles: list[dict]) -> str:
        lines = []
        for a in articles:
            lines.append(f"### {a.get('title', '')}")
            core = a.get("core_content") or a.get("tech_summary") or a.get("one_liner") or ""
            if core:
                lines.append(f"核心内容: {core}")
            val = a.get("value_judgment") or a.get("trend_signal") or ""
            if val:
                lines.append(f"价值判断: {val}")
            rel = a.get("relevance_to_me") or ""
            if rel:
                lines.append(f"与你相关: {rel}")
            if a.get("url"):
                lines.append(f"链接: {a['url']}")
            lines.append("")
        return "\n".join(lines)

    def _extract_new_content(self, raw_output: str) -> str | None:
        """从 LLM 输出中提取更新后的 wiki 全文"""
        marker = "## 更新后的 wiki 全文"
        idx = raw_output.find(marker)
        if idx == -1:
            return None
        content = raw_output[idx + len(marker):].strip()
        if content == "（无变化）" or content == "(无变化)":
            return None
        if len(content) < 50:
            return None
        return content

    def update(self, articles: list[dict], date_str: str = None):
        """主入口"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        # 只处理有实质内容的文章
        relevant = [a for a in articles if a.get("core_content") or a.get("value_judgment")]
        if not relevant:
            print("  无有效摘要，跳过 wiki 更新")
            return []

        # 按领域分组
        by_domain = defaultdict(list)
        for a in relevant:
            domain = a.get("domain", "其他")
            by_domain[domain].append(a)

        if not by_domain:
            return []

        # 收集需要更新的 wiki 页面
        pages_to_update = set()
        for domain in by_domain:
            for page_rel in self.mapping.get(domain, []):
                pages_to_update.add(page_rel)

        if not pages_to_update:
            return []

        print(f"  wiki 更新: {len(pages_to_update)} 个页面待检查")

        for page_rel in pages_to_update:
            page_path = self.vault / page_rel
            if not page_path.exists():
                print(f"  ⚠️ wiki 页面不存在: {page_rel}")
                continue

            # 收集影响这个页面的所有领域的文章
            page_articles = []
            page_domains = []
            for domain, paths in self.mapping.items():
                if page_rel in paths and domain in by_domain:
                    page_articles.extend(by_domain[domain])
                    page_domains.append(domain)

            if not page_articles:
                continue

            # 去重
            seen = set()
            unique = []
            for a in page_articles:
                t = a.get("title", "")
                if t not in seen:
                    seen.add(t)
                    unique.append(a)
            page_articles = unique

            current_content = page_path.read_text(encoding="utf-8")
            articles_text = self._format_articles(page_articles)

            prompt = UPDATE_PROMPT.format(
                current_content=current_content,
                articles_text=articles_text,
            )

            print(f"  → {page_rel}: {len(page_articles)} 篇文章 → LLM 判断中...")
            raw = _call_llm(prompt, max_tokens=4000)

            if not raw:
                print(f"  ⚠️ LLM 无响应，跳过 {page_rel}")
                continue

            # 记录判断结果
            judgment_section = raw.split("## 更新后的 wiki 全文")[0] if "## 更新后的 wiki 全文" in raw else raw[:500]
            verdicts = [l.strip("- ") for l in judgment_section.split("\n") if l.strip().startswith("- [")]
            for v in verdicts:
                print(f"    {v}")

            new_content = self._extract_new_content(raw)
            if new_content is None:
                domain_list = ", ".join(page_domains)
                print(f"  → {domain_list} → {page_rel}: 无需更新")
                self._log(f"SKIP {page_rel} (domains: {domain_list})")
                continue

            # 写回
            page_path.write_text(new_content, encoding="utf-8")
            domain_list = ", ".join(page_domains)
            print(f"  ✅ {domain_list} → {page_rel}: 已更新")
            self._log(f"UPDATE {page_rel} (domains: {domain_list}, articles: {len(page_articles)})")

            # 自动补 [[双向链接]] → Obsidian 图谱连线
            self._link_related(page_path, page_rel)

            self.updates.append({
                "page": str(page_rel),
                "domains": domain_list,
                "articles": len(page_articles),
                "verdicts": verdicts,
            })

        return self.updates


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")

    wu = WikiUpdater()
    tagged_file = f"D:/Claude code/获取信息/data/{date_str}_tagged.json"
    if Path(tagged_file).exists():
        with open(tagged_file, "r", encoding="utf-8") as f:
            articles = json.load(f)
        updates = wu.update(articles, date_str)
        print(f"\nwiki 更新完成: {len(updates)} 个页面")
    else:
        print(f"文件不存在: {tagged_file}")
