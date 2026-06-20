# 资料管理员 — 项目记忆

## 职责

管理 Obsidian 知识库的外部信息入口：四路信源 → 过滤摘要 → 入库 → 策展 → wiki 更新。

### 与沈念的分工

| | 资料管理员 | 沈念 |
|---|---|---|
| 管什么 | 外面发生了什么 | 你是谁、越来越懂你 |
| 写什么 | wiki/ + curated/ insights | about-me/ |
| 触发 | 每天 7:30 管线 + 被动检索 | 对话 + 早晚主动关怀 |
| 输出给谁 | 喂给沈念（外部信号 + wiki 更新） | 喂给你（个性化输出） |

### Obsidian Vault 结构

```
D:/obsidian/1/
├── wiki/                    ← 提炼后的知识 (Librarian 维护)
│   └── agent/
│       ├── _index.md        ← Agent 总览
│       ├── 架构/             ← ReAct与变体、图、记忆、安全、交互 + 综述
│       ├── 工具/             ← MCP协议、调用原理 + 综述
│       ├── 检索/             ← RAG/embedding + 综述
│       └── 评估/             ← 评估体系 + 综述
├── curated/
│   ├── about-me/            ← 沈念画像 (沈念写)
│   └── pitfalls/            ← 踩坑记录
├── raw/
│   └── agent/
│       ├── 每日/             ← cron 自动抓取 (>7天归档)
│       └── 手动/             ← 手动投喂 (永久保留)
└── archive/                  ← 归档文章 (>7天)
```

### 架构

```
四路信源 (Simon/GitHub/HN/Arxiv)
    │  25条/天
    ▼
tagger.py (DeepSeek)
    ├─ 领域判断: agent / 其他
    ├─ core_content: 文章讲了什么
    ├─ value_judgment: 可信度/趋势
    └─ 非 agent → 丢弃
    │  5-10条 agent 文章
    ▼
obsidian_writer.py → raw/agent/每日/
    │
    ▼
curator.py (单 Agent, DeepSeek)
    ├─ search_wiki (LLM匹配, 降级关键词)
    ├─ read_wiki_page (读全文)
    ├─ 判断: skip / merge / create
    ├─ 写前护栏: 确认不重复
    └─ write_wiki_page → wiki/agent/
    │
    ▼
reviewer.py (千问, 独立评测)
    ├─ 过滤质量 / 决策质量 / 内容质量
    └─ review_tracker.json (7日趋势)
    │
    ▼
archiver.py (>7天 → archive/)
```

### 检索

```
searcher.py (LLM匹配 + 关键词降级)
    ├─ router.py 轻量路由 (broad → 优先综述, specific → 优先细节)
    ├─ curator.search_wiki (LLM匹配 wiki 页面)
    ├─ keyword.py 关键词匹配 (降级)
    └─ 分层返回: 综述 → 知识 → 关键词补充
```

## Librarian 目录

```
librarian/
├── agent.py                ← 主编排器 (cron 入口)
├── models.py               ← Article + ArticleStore
├── config.py               ← 统一配置 (.env + config.yaml)
├── config.yaml              ← 集中配置
├── .env                     ← 敏感凭证 (API key)
├── articles.json            ← ArticleStore 持久化
│
├── fetch_sources.py        ← 四路抓取 + 去重 + retry + pending
├── tagger.py               ← DeepSeek 过滤 + 摘要 (agent only)
├── obsidian_writer.py      → Obsidian .md
├── curator.py              ← 单 Agent 策展 (search→read→decide→write)
├── archiver.py             ← >7天归档
├── searcher.py             ← 统一检索入口 (LLM匹配)
│
├── search/
│   ├── router.py           ← 查询分类 (broad/specific)
│   └── keyword.py          ← 关键词匹配 (降级)
│
├── multi_agent_curation/   ← [已弃用] 旧三人小组，保留供参考
│   └── reviewer.py         ← 策展质量评测 (千问, 独立运行)
│
├── logs/                   ← 运行日志
│   └── curation/           ← 策展决策日志 + review.md
└── CLAUDE.md               ← 本文件
```

## 使用说明

### 配置

```bash
echo "DEEPSEEK_API_KEY=sk-xxx" > "D:/Claude code/librarian/.env"
echo "QWEN_API_KEY=sk-xxx" >> "D:/Claude code/librarian/.env"
python -c "from config import DEEPSEEK_API_KEY; print('OK' if DEEPSEEK_API_KEY.startswith('sk-') else 'MISSING')"
```

### 被动检索

```bash
python "D:/Claude code/librarian/searcher.py" "查询词"
```

检索流程: LLM 匹配 wiki 页面 + 关键词降级。不依赖本地 embedding 模型。

### 主动管线 (cron)

Windows 计划任务 7:30 → `获取信息/daily_run.sh` → `agent.py`:

```
补抓 pending → 四路抓取 + 去重
  → tagger (过滤: agent only + 摘要)
  → 写入 raw/agent/每日/
  → 策展 (单 Agent: search→read→decide→write)
  → 评测 (千问 reviewer)
  → 归档 (>7天)
```

### 手动投喂

```bash
python "D:/Claude code/librarian/agent.py" --manual --url "https://..."
python "D:/Claude code/librarian/agent.py" --manual --text "标题" "内容"
```

走同一套 `process_incoming()`。写入 `raw/agent/手动/`，不受 7 天归档。

### 评测

```bash
python "D:/Claude code/librarian/multi_agent_curation/reviewer.py"           # 今天
python "D:/Claude code/librarian/multi_agent_curation/reviewer.py" 2026-06-03
```

## 信源

```
Simon Willison → 个人博客，工程视角
GitHub         → 早期项目 (按更新时间，不按 star)
Hacker News    → 社区讨论，points>10
Arxiv          → 论文，追新范式
```

### 加新信源

`config.yaml` 的 `sources` 下加一段，然后在 `fetch_sources.py` 加对应的 `fetch_xxx()` 函数。

### 加新领域

`config.yaml` 的 `summarizer.domains` 加新领域名，`raw_domains` 加对应的 raw 路径。tagger prompt 自动扩展。

## 设计决策

- **tagger 只做过滤** — 是不是 agent + 讲什么 + 可信度。不判断价值，不判断要不要策展
- **策展单 Agent** — 读文章 → 搜 wiki → 读全文 → 判断 skip/merge/create → 写。写前确认不重复
- **全 LLM 检索** — 不用本地 embedding。search_wiki 用 LLM 匹配页面，失败降级关键词
- **千问独立评测** — reviewer 用千问而非 DeepSeek，避免自评偏差。评测失败不阻塞管线
- **非 agent 直接丢弃** — tagger 输出 domain != "agent" 的文章不写入 Obsidian
- **raw 封存不反复碰** — 入口处理一次, 7 天归档, 之后只搜 wiki
- **4 层 JSON 解析兜底** — tagger/curator 共用，不信任单一输出格式
- **路径全硬编码** — Git Bash + 中文路径 + 空格下相对路径不可靠
- **ArticleStore 统一数据模型** — 所有模块通过 store 交换数据，.md 只是导出视图
- **抓取 retry + pending** — 每个信源 3 次重试，失败写 .pending_fetches.json，下次 cron 补抓
- **cron 入口 agent.py** — 单一 Python 入口，不通过 shell 串联
- **防编造规则** (2026-06-20) — curator 描述外部项目/工具时只写原文信息，不要推测实现原理/技术栈。不确定写"待确认"
- **正文 wikilink** (2026-06-20) — curator 写内容时正文里提到已有 wiki 页面的项目/术语 → 用 [[wikilink]] 包裹，不只在末尾"## 相关"放链接
- **3 日重复写入控制** (2026-06-20) — 目标页面 3 天内被策展更新过 → 优先 skip，除非新信息确实重大
- **同主题页面合并** (2026-06-20) — 记忆主题 4 页 → 2 页。策展造成的碎片化需要手动定期清理

## 遇到过的坑

### 1. sentence-transformers 本地模型不适合 cron 场景
**现象:** `search_wiki` 首次调用卡 5 分钟+，cron 每天新进程
**解决:** 全切 LLM 检索，用 DeepSeek Chat 做查询→页面匹配。零启动成本，每次 ~2s

### 2. HuggingFace 被墙
**现象:** WinError 10060
**解决:** 设 `HF_ENDPOINT=https://hf-mirror.com`（已废弃，全切 LLM 后不再需要）

### 3. 三人小组信息衰减
**现象:** Signal Agent 吃 tagger 摘要，Curation Agent 只看标题，Wiki Agent 只读前 3000 字
**解决:** 合为单 Agent，读原文 + 读 wiki 全文再做决策

### 4. 策展会编造技术细节 (2026-06-17/20)
**现象:** curator 描述 Claw Patrol 用了"规则引擎+ML检测"，但 HN 原文明确写的是纯规则引擎、零 ML。如果不纠正，按这个描述做集成会制造安全盲区
**根因:** curator 只读 wiki 前 3000 字 + tagger 摘要，没见过原文。LLM 凭工具名"推测"实现原理
**解决:** curator prompt 加硬规则：只写原文明确提到的信息，不确定写"待确认"。不加验证流程，就靠 prompt 约束

### 5. 策展重复写入导致页面膨胀 (2026-06-20)
**现象:** 16 天策展中，安全架构/ReAct/框架对比/记忆架构每天被更新。taosmd 在 4 个不同页面出现 8+ 次，Total Recall 出现 6+ 次
**根因:** curator 没有"这个页面最近被写过"的感知，新文章只要相关就往里塞。评测 review 发现但写不阻止
**解决:** ① curator 加 3 日重复写入控制 ② 手动定期扫 wiki 合并同主题碎片页面