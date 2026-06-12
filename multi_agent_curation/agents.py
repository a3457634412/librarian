"""多 Agent 策展 — 三个 Agent 实现

Signal Agent   — 从 tagged articles 提炼信号（无工具，纯 LLM）
Curation Agent — 根据信号 + wiki 现状做策展方案（有 read_wiki / search_wiki）
Wiki Agent     — 审方案 + 写 wiki 内容（有 read_wiki / search_wiki / write_wiki）
"""

import json
from multi_agent_curation.state import CurationState
from multi_agent_curation.llm import call, parse_json
from multi_agent_curation.tools import (
    read_wiki_page, search_wiki, write_wiki_page,
    get_wiki_index, get_wiki_frontmatter_tags,
)
from multi_agent_curation.logger import log_agent, log_error


# ═══════════════════════════════════════════════
# Signal Agent
# ═══════════════════════════════════════════════

SIGNAL_PROMPT = """你是信息筛选助手，为一个正在努力成为资深 Agent 工程师的用户管理个人知识库。

你的用户背景：
- 全栈后端转 AI/Agent，在生产环境维护个人 AI 助手"沈念"
- 已深入掌握 Agent 架构理论（ReAct/LangGraph/多Agent/CodeAct/端到端），读过 DeepSeek 源码
- 有自己的 Obsidian 知识库（三层索引 + 混合检索 + wiki 提炼）
- 现在需要从外部信息流中筛选出能帮助他变得更好的信号

## 今天的信息

__ARTICLES_TEXT__

## 你的任务

从以上文章中提炼**值得策展的信号**。没有数量限制——有两三个就输出两三个，有七八个就输出七八个。唯一标准是每个信号都必须有实质依据和明确价值。

信号分为两类：

### 第一类：多文章信号（优先级最高）
多篇文章指向同一个方向。这是最强的信号类型——独立来源的收敛说明趋势真实。

### 第二类：单篇触及已有领域（不可跳过）
即使只有一篇文章，如果它明确触及用户的 wiki 已有领域，也必须作为独立信号输出。示例：
- MCP 官方 SDK 新语言支持 → 触及 wiki 的 MCP 协议领域
- Agent 权限控制/安全方案 → 触及 wiki 的安全架构领域
- Agent 维护的语义层 → 触及 wiki 的检索/知识库领域
→ 这类信号 confidence 标 low 或 medium，但必须被输出

对每个信号，判断类型：
- **update_existing**: 更新/挑战/补充 wiki 已有知识。你不需要知道 wiki 里有什么，从文章判断"这看起来是在已有领域上的新进展"
- **new_direction**: 多篇文章指向全新方向，wiki 可能没覆盖。单篇文章不能标 new_direction

输出 JSON：

```json
{{
  "signals": [
    {{
      "type": "update_existing",
      "topic": "Agent 评估",
      "signal": "一句话描述这个信号是什么",
      "evidence": ["文章标题1", "文章标题2"],
      "article_ids": [0, 3, 7],
      "confidence": "high",
      "suggested_action": "curate",
      "rationale": "为什么这个信号值得关注，对成为资深 Agent 工程师有什么帮助"
    }}
  ]
}
```

规则：
- 不设数量限制。信息密度低就少输出，不要凑数；信息密度高就多输出，不要砍有价值的信号
- confidence: high / medium / low。单篇文章信号禁止标 high
- suggested_action: curate（值得写综述）/ watch（持续观察）/ skip（不处理）
- evidence 必须引用真实文章标题
- rationale 要具体——"这个信号对 Agent 工程师意味着什么"，不能泛泛说"值得关注"
- 不要漏掉单篇触及已有领域的文章。宁可多输出一个 low-confidence 信号让下游 Curation Agent 决定，也不要漏掉
- 只输出 JSON，不要其他内容"""


def signal_agent(state: CurationState) -> CurationState:
    """从 tagged articles 提炼信号"""
    articles = state.articles
    if not articles:
        state.errors.append("Signal Agent: 无文章输入")
        return state

    # 构建文章摘要文本（精简，每篇只取关键字段）
    lines = []
    for i, a in enumerate(articles):
        title = a.get("title", "")
        core = a.get("core_content") or a.get("tech_summary") or ""
        trend = a.get("value_judgment") or a.get("trend_signal") or ""
        relevance = a.get("relevance_to_me") or ""

        lines.append(f"[{i}] {title}")
        if core:
            lines.append(f"    核心: {core}")
        if trend:
            lines.append(f"    趋势: {trend}")
        if relevance:
            lines.append(f"    相关: {relevance}")
        lines.append("")

    articles_text = "\n".join(lines)
    input_summary = {"article_count": len(articles), "articles_text_len": len(articles_text)}

    prompt = SIGNAL_PROMPT.replace("__ARTICLES_TEXT__", articles_text[:8000])

    try:
        raw = call(prompt, max_tokens=3000, temperature=0.4, json_mode=True)
        parsed = parse_json(raw)
        if parsed and isinstance(parsed, dict) and "signals" in parsed:
            state.signals = parsed["signals"]
            print(f"  [Signal] {len(state.signals)} 个信号")
            for s in state.signals:
                print(f"    [{s.get('confidence', '?')}] {s.get('signal', '')[:80]}")
        else:
            state.errors.append(f"Signal Agent: 解析失败")
            log_error(state.date_str, "signal_agent", "JSON parse failed")
    except Exception as e:
        state.errors.append(f"Signal Agent: {e}")
        log_error(state.date_str, "signal_agent", str(e))

    log_agent(state.date_str, "signal_agent", input_summary,
              {"signals": state.signals, "errors": state.errors})

    return state


# ═══════════════════════════════════════════════
# Curation Agent
# ═══════════════════════════════════════════════

CURATION_PROMPT = """你是策展决策助手，为一个正在努力成为资深 Agent 工程师的用户管理个人知识库。

你的用户已经有一个成熟的 wiki 知识库（Obsidian），覆盖了 Agent 架构、工具协议、评估体系、产品设计等领域。
你的任务不是"收集信息"，而是**判断哪些新信息能帮助用户变得更好**。

## Wiki 知识库现状

__WIKI_OVERVIEW__

## Signal Agent 提炼的信号

__SIGNALS_TEXT__

## 你的任务

对每个信号做两步判断：

### 第一步：能不能更新已有知识？

读 wiki 相关页面，判断新信息是否：
- **替代**: 新方案比 wiki 里已有的明显更好（有数据/指标支撑）
- **补充**: wiki 没覆盖的细节/工具/实践
- **冲突**: 新结论和 wiki 矛盾 → 不改原内容，标记出来等人确认
- **跳过**: wiki 已有，或信息质量不够

### 第二步：值不值得开新方向？

如果信号是 new_direction 类型：
- 这个方向对 Agent 工程师有没有实质价值？
- 多篇文章的证据链够不够强？
- 放在 wiki 的哪个目录下最合理？
- 和现有页面会不会重叠？

输出 JSON：

```json
{{
  "plan": [
    {{
      "signal": "信号原文",
      "decision": "curate",
      "type": "update_existing",
      "target_page": "wiki/agent/评估/评估体系.md",
      "action": "补充有 CI/CD 集成评测流水线方案的内容",
      "rationale": "wiki 里只写了手动评估，新信息补充了自动化评测实践",
      "priority": "high"
    }},
    {{
      "signal": "信号原文",
      "decision": "curate",
      "type": "new_direction",
      "target_page": "wiki/agent/可靠性方案对比.md",
      "action": "新建页面，对比 Statewright/MemOS/Torrix 三种可靠性方案",
      "suggested_directory": "wiki/agent/可靠性/",
      "rationale": "三个独立项目同时探索 Agent 可靠性，方向清晰且不重叠已有页面",
      "priority": "medium"
    }},
    {{
      "signal": "信号原文",
      "decision": "merge",
      "type": "update_existing",
      "merge_target": "wiki/agent/架构/ReAct与变体.md",
      "action": "在相关段落追加一句话",
      "rationale": "信息有价值但不足以独立成篇"
    }},
    {{
      "signal": "信号原文",
      "decision": "skip",
      "rationale": "wiki 已有充分覆盖，没有新信息"
    }}
  ]
}}
```

决策类型：
- **curate**: 值得大幅更新或新建页面。优先更新已有页面，确定 wiki 无覆盖才新建
- **merge**: 有价值但不足以独立成篇，合并到已有页面
- **skip**: 不做操作
- **schema_gap**: 信号本身有价值，但 wiki 当前没有对应目录/页面可落。标注 suggested_directory 建议新建的目录或页面路径，供用户决策

规则：
- 先处理 update_existing 类型信号——检查 wiki 里哪些页面可以更新
- 再处理 new_direction 类型信号——确认 wiki 里是否有遗漏后，再决定要不要建新页面
- 优先更新已有页面。能追加到已有页面的绝不新建。碎片化是知识库的敌人
- 开新方向要谨慎：必须有 ≥3 篇独立文章支撑，且搜索确认 wiki 里没有相关覆盖
- 如果 wiki 已有相关页面 → 必须用 merge，标注 merge_target
- target_page 和 merge_target 必须是真实存在的 wiki 路径
- schema_gap 不要滥用——只有信号确实有价值、有足够证据、但因为 wiki 目录设计缺陷无处可放时才用。不确定时选 skip
- priority: high / medium / low
- 只输出 JSON，不要其他内容"""


def curation_agent(state: CurationState) -> CurationState:
    """基于信号和 wiki 现状，做策展方案"""
    if not state.signals:
        state.errors.append("Curation Agent: 无信号输入")
        return state

    # ── 预加载 wiki 上下文 ──
    wiki_index = get_wiki_index("agent")
    wiki_overview = _build_wiki_overview(wiki_index)

    # 对每个 signal 搜索相关 wiki 页面
    search_results = {}
    for sig in state.signals:
        topic = sig.get("topic", "")
        if topic:
            search_results[topic] = search_wiki(topic, domain="agent", max_results=5)

    signals_text = json.dumps(state.signals, ensure_ascii=False, indent=2)

    # 拼接 wiki 搜索结果
    search_text = ""
    for topic, results in search_results.items():
        if results:
            search_text += f"\n### 搜索 '{topic}' 的相关 wiki:\n"
            for r in results[:3]:
                search_text += f"- {r['path']}: {r['snippet'][:150]}\n"

    wiki_context = wiki_overview + "\n" + search_text

    input_summary = {
        "signal_count": len(state.signals),
        "wiki_pages_checked": len(wiki_index),
        "search_topics": list(search_results.keys()),
    }

    prompt = CURATION_PROMPT.replace("__WIKI_OVERVIEW__", wiki_context[:4000]).replace("__SIGNALS_TEXT__", signals_text)

    try:
        raw = call(prompt, max_tokens=4000, temperature=0.2, json_mode=True)
        parsed = parse_json(raw)
        if parsed and isinstance(parsed, dict) and "plan" in parsed:
            state.curation_plan = parsed["plan"]
            print(f"  [Curation] {len(state.curation_plan)} 条决策")
            for p in state.curation_plan:
                print(f"    [{p.get('decision', '?')}] {p.get('type', '')} → {p.get('target_page', p.get('merge_target', '?'))}")
        else:
            state.errors.append("Curation Agent: 解析失败")
            log_error(state.date_str, "curation_agent", "JSON parse failed")
    except Exception as e:
        state.errors.append(f"Curation Agent: {e}")
        log_error(state.date_str, "curation_agent", str(e))

    log_agent(state.date_str, "curation_agent", input_summary,
              {"plan": state.curation_plan, "errors": state.errors})

    return state


def _build_wiki_overview(wiki_index: list[dict]) -> str:
    """构建 wiki 目录概览 — 按目录分组，展示层级结构"""
    from collections import defaultdict
    by_dir = defaultdict(list)
    for p in wiki_index:
        parts = p["path"].replace("\\", "/").split("/")
        directory = "/".join(parts[:-1]) if len(parts) > 1 else "/"
        by_dir[directory].append((parts[-1], p["title"]))

    lines = ["## wiki/agent/ 目录结构\n"]
    for directory in sorted(by_dir):
        pages = by_dir[directory]
        indent = "  " * (directory.count("/"))
        lines.append(f"- **{directory}/** ({len(pages)} 页)")
        for filename, title in sorted(pages):
            lines.append(f"  - `{filename}` — {title}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
# Wiki Agent
# ═══════════════════════════════════════════════

WIKI_PROMPT = """你是知识库审核和写作助手，为一个正在努力成为资深 Agent 工程师的用户维护个人 wiki。

## 用户 wiki 质量原则

- 内容必须是提炼后的知识，不是文章摘要堆砌
- 每篇有明确的核心洞察和工程实践价值
- 保留已有高质量内容，只改受影响的段落
- 结论矛盾时标注 ⚠️ 不静默覆盖

## wiki/agent/ 目录参考

```
wiki/agent/
├── _index.md / 综述.md
├── 产品分类学.md / 产品UX范式.md / 产品拆解-Claude-Code.md
├── 失败模式分类.md / 成本模型.md / 记忆-产品视角.md / 评估实操.md
├── 架构/
│   ├── _index.md / 综述.md / 框架对比.md
│   ├── ReAct与变体.md / 图架构.md / 多Agent协作.md / 搜索架构.md
│   ├── 认知架构.md / 记忆架构.md / 安全架构.md / 交互架构.md
│   ├── CodeAct.md / 内存原生架构（MemGPT）.md / 端到端模型.md
├── 工具/
│   ├── _index.md / 综述.md / 调用原理.md / MCP协议.md / A2A协议.md
├── 检索/ 评估/ pitfalls/
```

写 `[[双向链接]]` 即可，链接路径有后续自动化节点统一修复，你专注内容质量。

## 内容质量标准

你的 wiki 已有页面达到了这个水平（以 ReAct与变体.md 为例）：
- 开篇一句话讲清楚核心思路
- 有深层解析（不是罗列项目，是提取设计洞察）
- 有对比表格（不同方案/变体的适用场景）
- 有关键实验结论或数据支撑
- 有根本局限的诚实讨论
- 每个断言有依据，不是"感觉"
- 有完整演进线，把碎片知识串成体系

新建的页面也要对标这个标准。如果只是罗列项目名+一句话介绍，就是不合格。

## Curation Agent 的方案

__PLAN_TEXT__

## 相关 wiki 页面当前内容

__WIKI_PAGES_TEXT__

## 你的任务

### 第一步：审方案

对每条策展方案，判断：

1. **对成为资深 Agent 工程师有没有实质帮助？**
   - 这个方向是"知道更好"还是"不知道会有盲区"？
   - 和已有 wiki 有没有重复？（反复搜，确认没有遗漏）
2. **目录位置对吗？**
   - 参考上面 wiki 目录结构，判断 Curation 建议的位置合不合理
   - 需不需要调整？
3. **优先更新已有页面**
   - 如果 wiki 已有高度相关的页面 → 用 update，追加到合适位置
   - 只有当前 wiki 确定没有覆盖该方向时 → 才 create 新页面
   - 碎片化是知识库的敌人——宁可一个长页面也不要五个短页面

### 第二步：写内容

对批准的方案：

- **create（新建页面）**: 写完整的新页面，对标上面「内容质量标准」。包括 frontmatter、核心洞察、技术对比、工程实践建议、局限讨论、## 相关 段落
- **update（合并到已有）**: 只输出要追加的段落（new_section），标注插入位置（insert_after）
- **skip（驳回）**: 说明为什么驳回，不写内容

输出 JSON：

```json
{{
  "updates": [
    {{
      "signal": "信号原文",
      "approval": "approved",
      "page": "wiki/agent/可靠性/可靠性方案对比.md",
      "action": "create",
      "review": "方案合理。这个方向 wiki 没覆盖，且有三个独立项目支撑。",
      "directory_adjustment": null,
      "content": "---\\ntitle: 可靠性方案对比\\ntype: synthesis\\ntags: [agent, reliability]\\n---\\n\\n# 可靠性方案对比\\n\\n一句话: xxx\\n\\n## 核心洞察\\n...(深度分析)",
      "contradictions_found": []
    }},
    {{
      "signal": "信号原文",
      "approval": "approved",
      "page": "wiki/agent/评估/评估体系.md",
      "action": "update",
      "review": "补充工程实践细节有价值。目标页面存在且已覆盖概念，在此追加实践。",
      "insert_after": "## 技术实现",
      "new_section": "### CI/CD 集成评测\\n\\n...(追加内容)",
      "contradictions_found": []
    }},
    {{
      "signal": "信号原文",
      "approval": "rejected",
      "page": null,
      "action": "skip",
      "review": "和 架构/框架对比.md 高度重叠",
      "reason": "与已有页面重复"
    }}
  ]
}}
```

写作规范：
- frontmatter 必须包含 title, type, created, tags
- type: synthesis / comparison / concept（参考已有页面）
- 不要写"本文介绍了..."这种废话开头
- 不要堆链接列表
- 每个断言有依据
- [[双向链接]]按上述路径规则写，写完后自查链接是否正确

规则：
- 对每条方案逐一审核，不打包
- 驳回不是失败——没价值的方案就该驳回
- 发现和已有页面矛盾 → contradictions_found 标注，不改已有内容
- 建新页面必须确认目录存在，不在目录里的先 mkdir
- 涉及具体项目/工具时，不要猜测实现语言、依赖等技术细节。不确定就留空或写"待确认"
- 只输出 JSON，不要其他内容"""


def wiki_agent(state: CurationState) -> CurationState:
    """审方案 + 写 wiki"""
    if not state.curation_plan:
        state.errors.append("Wiki Agent: 无策展方案输入")
        return state

    # ── 预加载相关 wiki 页面 ──
    wiki_pages_text = ""
    loaded_pages = set()
    for plan_item in state.curation_plan:
        target = plan_item.get("target_page") or plan_item.get("merge_target") or ""
        if target and target not in loaded_pages:
            content = read_wiki_page(target)
            if content:
                wiki_pages_text += f"\n### {target}\n\n{content[:3000]}\n\n---\n"
                loaded_pages.add(target)

    # 对 new_direction 类型，搜相关页面确保不重复
    for plan_item in state.curation_plan:
        if plan_item.get("type") == "new_direction":
            topic = plan_item.get("signal", "")[:60]
            results = search_wiki(topic, domain="agent", max_results=5)
            if results:
                wiki_pages_text += f"\n### 搜索 '{topic}' (重复检查):\n"
                for r in results[:3]:
                    wiki_pages_text += f"- {r['path']}: {r['snippet'][:200]}\n"

    plan_text = json.dumps(state.curation_plan, ensure_ascii=False, indent=2)

    input_summary = {
        "plan_count": len(state.curation_plan),
        "pages_loaded": list(loaded_pages),
    }

    prompt = WIKI_PROMPT.replace("__PLAN_TEXT__", plan_text).replace("__WIKI_PAGES_TEXT__", wiki_pages_text[:6000])

    try:
        raw = call(prompt, max_tokens=8000, temperature=0.2, json_mode=True)
        parsed = parse_json(raw)
        if parsed and isinstance(parsed, dict) and "updates" in parsed:
            state.wiki_updates = parsed["updates"]
            print(f"  [Wiki] {len(state.wiki_updates)} 条审核结果")
            for u in state.wiki_updates:
                status = "✅" if u.get("approval") == "approved" else "❌"
                action = u.get("action", "?")
                page = u.get("page") or "—"
                print(f"    {status} [{action}] {page}")
        else:
            state.errors.append("Wiki Agent: 解析失败")
            log_error(state.date_str, "wiki_agent", "JSON parse failed")
    except Exception as e:
        state.errors.append(f"Wiki Agent: {e}")
        log_error(state.date_str, "wiki_agent", str(e))

    # ── 执行写操作 ──
    for update in state.wiki_updates:
        if update.get("approval") != "approved":
            continue
        page = update.get("page", "")
        action = update.get("action", "")
        content = update.get("content") or update.get("new_section") or ""

        if not page or (not content and action != "skip"):
            update["status"] = "skipped"
            update["reason"] = update.get("reason") or "无页面或内容"
            continue

        if action == "create":
            ok = write_wiki_page(page, content)
            update["status"] = "written" if ok else "write_failed"
        elif action == "update":
            # 对已有页面：读原文 → 找到插入位置 → 插入新内容 → 写回
            current = read_wiki_page(page)
            if current:
                insert_after = update.get("insert_after", "")
                new_section = update.get("new_section") or content
                if insert_after and insert_after in current:
                    idx = current.find(insert_after)
                    # 找到该段落结束位置（下一个 ## 或文件末尾）
                    next_section = current.find("\n## ", idx + len(insert_after))
                    if next_section == -1:
                        next_section = len(current)
                    updated_content = (
                        current[:next_section].rstrip()
                        + "\n\n"
                        + new_section
                        + "\n"
                        + current[next_section:]
                    )
                else:
                    # 没找到插入位置 → 追加在 ## 相关 前
                    if "\n## 相关" in current:
                        idx = current.rfind("\n## 相关")
                        updated_content = current[:idx] + "\n" + new_section + "\n" + current[idx:]
                    else:
                        updated_content = current.rstrip() + "\n\n" + new_section + "\n"

                ok = write_wiki_page(page, updated_content)
                update["status"] = "written" if ok else "write_failed"
            else:
                # 页面不存在 → 新建
                ok = write_wiki_page(page, content)
                update["status"] = "written" if ok else "write_failed"
        else:
            update["status"] = "skipped"

    log_agent(state.date_str, "wiki_agent", input_summary,
              {"updates": state.wiki_updates, "errors": state.errors})

    return state
