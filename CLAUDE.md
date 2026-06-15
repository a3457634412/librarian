# 资料管理员 — 项目记忆

## 职责

管理 Obsidian 知识库的外部信息入口：四路信源 → 领域自适应摘要 → 入库 → wiki 提炼 → 索引 → 检索。
踩坑记录（pitfalls/）归资料管理员维护。沈念画像（about-me/）归沈念维护。

### 与沈念的分工

| | 资料管理员 | 沈念 |
|---|---|---|
| 管什么 | 外面发生了什么、项目环境 | 你是谁、越来越懂你 |
| 写什么 | reviews/ insights/ pitfalls/ | about-me/ |
| 触发 | 每天 7:30 管线 + 被动查询 | 对话 + 早晚主动关怀 |
| 输出给谁 | 喂给沈念（外部信号） | 喂给你（个性化输出） |

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
│   └── pitfalls/            ← 踩坑记录 (Librarian 管)
├── raw/
│   ├── {领域}/               ← 按领域分目录 (agent/ 营养/ 其他/ ...)
│   │   ├── 每日/             ← cron 自动抓取 (>7天归档)
│   │   └── 手动/             ← 手动投喂 (永久保留，进 core 层)
│   ├── conversations/        ← 对话存档 (沈念写)
│   └── cli-sessions/         ← CLI 日志 (沈念写)
└── archive/                  ← 归档文章 (>7天)
```

### raw 与 wiki 的分工

```
raw/{domain}/                      wiki/{domain}/
══════════                         ═══════════
"外面说了什么"                       "你应该知道什么"
原始数据，按领域存                    提炼后的知识，按领域组织
目录即分类，不需要标签                 每个领域自定子结构

规则:                               规则:
1. 目录名 = 领域，自动路由             1. 只有 Librarian 能改
2. 文件写入后永不修改                  2. 每次只改受影响的段落
3. 每日 >7天 → archive/              3. 新方案更好 → 替换旧内容
4. 手动投喂永久保留进 core 层           4. wiki 没覆盖 → 增补新段落
                                      5. 结论矛盾 → 标注 ⚠️ 不回写
                                      6. 已有 → 跳过，不堆链接
```

### 新建知识库领域

只需改 `config.yaml`，代码不动：

1. `summarizer.domains` 加新领域名
2. `wiki_pages` 加新领域 → wiki 页面映射
3. `raw_domains` 加新领域的 每日/手动 路径
4. 目录自动创建，wiki 页面可以先放空 `_index.md`

示例 — 新建"营养"领域：
```yaml
summarizer:
  domains: ["agent", "营养", "其他"]

wiki_pages:
  agent: [...]
  营养:
    - "wiki/营养/_index.md"

raw_domains:
  营养:
    daily: "raw/营养/每日"
    manual: "raw/营养/手动"
```

然后手动创建 `wiki/营养/_index.md` 作为起点，Librarian 后续自动维护。

### 检索架构

```
用户/bot 查询
    │
    ▼
searcher.py（Python 入口）
    ├─ router.py 轻量路由（broad → 优先综述, specific → 优先细节）
    ├─ keyword.py 关键词匹配 + 权威度×时效排序
    ├─ semantic.py 语义检索（三层权重，动态调整）
    ├─ hybrid.py 混合合并（关键词/语义权重按路由动态分配）
    └─ 知识边界感知（最高语义分 < 0.3 时警告）

三层索引 (indexer.py):
  Layer 1: core_index.json    — wiki + curated + pitfalls + 手动投喂 (权重 1.5)
  Layer 2: recent_index.json  — <7 天每日AI精华 (权重 1.0)
  Layer 3: archive_index.json — 归档文章 (默认不参与检索)
```

### Librarian 目录

```
librarian/
├── agent.py                ← 主编排器（cron 入口通过 daily_run.sh 调这个）
├── models.py               ← Article + ArticleStore — 所有模块读写的唯一数据源
├── config.py               ← 统一配置模块（加载 .env + config.yaml，所有模块单点导入）
├── .env                     ← 敏感凭证（API key，不提交 git）
├── config.yaml              ← 集中配置（路径/权重/阈值）
├── articles.json            ← ArticleStore 持久化（生命周期: ingested→tagged→indexed→archived）
│
├── fetch_sources.py        ← 三路抓取 + 去重 + retry + pending 机制
├── tagger.py               ← DeepSeek 打标签（4层JSON解析兜底）
├── obsidian_writer.py      ← Store → Obsidian .md（导出视图）
├── notifier.py             ← 飞书×2 + 微信 统一推送
├── processor.py            ← 标签统计 + 异常检测 + 关联笔记 + Claude 洞察
├── curator.py              ← [已停用] 旧策展逻辑，被 multi_agent_curation/ 替代
├── wiki_updater.py         ← [已停用] 旧 wiki 更新逻辑，保留 maintain_all_links()
├── multi_agent_curation/   ← 三人小组策展 (2026-06-03)
│   ├── __init__.py
│   ├── state.py            ← CurationState — 三 Agent 共享状态
│   ├── llm.py              ← 共享 LLM 调用 + 4层JSON解析兜底
│   ├── tools.py            ← read_wiki / search_wiki(LLM匹配+关键词降级) / write_wiki / get_wiki_index
│   ├── agents.py           ← Signal / Curation / Wiki 三个 Agent 的 prompt + 逻辑
│   ├── graph.py            ← 编排入口 run_curation_pipeline()
│   ├── reviewer.py         ← 千问评测器 (每天管线跑完后自动评级)
│   └── logger.py           ← 每 Agent I/O 日志 + decisions_summary.md
├── contradiction.py        ← 碰撞检测（新文章 vs wiki/综述 → 冲突/补充/替代）
├── archiver.py             ← >7天文章归档
├── indexer.py              ← 三层向量索引（mtime原子化，编码失败不丢数据）
├── graph.py                ← 知识图谱管理（三元组+实体+边索引）
│
├── searcher.py             ← 统一检索入口（含轻量路由 broad/specific）
├── search/
│   ├── router.py           ← 查询分类
│   ├── keyword.py          ← 关键词匹配+打分
│   ├── semantic.py         ← 语义检索（支持动态权重）
│   └── hybrid.py           ← 混合检索融合
│
├── search_obsidian.sh      ← bash 检索入口（降级路径）
├── search_config.sh        ← shell 侧配置
├── preemptive_brief.sh     ← 主动简报
├── profile.sh              ← 搜索画像管理
├── session_manager.sh      ← 会话 CRUD
│
├── indexes/
│   ├── core_index.json     ← Layer 1: wiki + curated + pitfalls + 手动投喂
│   ├── recent_index.json   ← Layer 2: <7天每日AI精华
│   └── archive_index.json  ← Layer 3: 归档文章
├── .index_state.json       ← 文件 mtime 记录
├── .pending_fetches.json   ← 抓取失败的信源（下次补抓）
├── curated/manifest.json   ← 策展记录
├── sessions/               ← 会话文件 + profile.json
├── logs/                   ← 运行日志
│
├── architecture.md         ← 架构设计
├── roadmap.md              ← 优化路线图
└── CLAUDE.md               ← 本文件
```

## 使用说明

### 配置

```bash
# 1. 创建 .env 文件（从沈念复制 key）
echo "DEEPSEEK_API_KEY=sk-xxx" > "D:/Claude code/librarian/.env"

# 2. 验证
python -c "from config import DEEPSEEK_API_KEY; print('OK' if DEEPSEEK_API_KEY.startswith('sk-') else 'MISSING')"
```

所有模块通过 `from config import config, DEEPSEEK_API_KEY` 获取配置和凭证。`.env` 不提交 git。

### 被动检索

```bash
bash "D:/Claude code/librarian/search_obsidian.sh" "查询词"            # 默认只搜 #可能与我的部署相关
bash "D:/Claude code/librarian/search_obsidian.sh" "查询词" --no-filter # 搜全部
bash "D:/Claude code/librarian/search_obsidian.sh" "查询词" --session <id>  # 多轮对话
bash "D:/Claude code/librarian/search_obsidian.sh" --list-sessions
bash "D:/Claude code/librarian/search_obsidian.sh" --clear-session <id>
```

检索模式：有 embedding 索引 → 混合（关键词 40% + 语义 60%），无索引 → 纯关键词。

### 主动管线（cron）

Windows 计划任务 7:30 → `获取信息/daily_run.sh` → `agent.py` → `process_incoming()`:

```
补抓 pending → 四路抓取 (Simon/GitHub/HN/Arxiv) + 去重
  → 领域自适应摘要 (tagger.py: 核心内容/价值判断/与你相关)
  → 按领域写 raw/{domain}/  → 推送 (notifier.py)
  → 三人小组策展 (multi_agent_curation/: Signal→Curation→Wiki) → 碰撞 (contradiction.py)
  → 双向链接维护 (wiki_updater.maintain_all_links())
  → 归档 (archiver.py) → 增量索引 (indexer.py) → 知识图谱 (graph.py)
```

### 手动投喂

```bash
python "D:/Claude code/librarian/agent.py" --manual --url "https://..."
python "D:/Claude code/librarian/agent.py" --manual --text "标题" "内容"
```

与 cron 走同一套 `process_incoming()`。写入 `raw/手动投喂/`，进 core 层，不受 7 天归档。

### 手动操作

```bash
# 索引
python "D:/Claude code/librarian/indexer.py" --full        # 全量重建
python "D:/Claude code/librarian/indexer.py" --incremental # 增量更新
```

## 信源管理

### 设计原则

```
四路信源，各有分工，互补不重叠：

Simon Willison  → 个人博客，工程视角，只有他能写出的独特观察
GitHub          → 早期项目（按更新时间排，不按 star 排，抓还没火的）
Hacker News     → 社区讨论 + Show HN，质量门槛 points>10
Arxiv           → 论文，追新范式和研究方向
```

**为什么这么分**：如果多个源搜同一个 query，抓到的内容高度重叠，去重后有效信息量不变但浪费 token。每个源应该回答不同的问题——Simon 说"什么值得关注"，GitHub 说"什么刚出来"，HN 说"什么在讨论"，Arxiv 说"什么在研究"。

### 加新信源

在 `config.yaml` 的 `sources` 下加一段，然后在 `fetch_sources.py` 加对应的 `fetch_xxx()` 函数。

**通用模板** — 以"营养"领域为例：

```yaml
sources:
  # ... 现有源 ...
  营养-RSS:                          # 新源名称
    url: "https://example.com/feed"  # RSS/API 地址
    max_articles: 5                  # 每次抓取上限
```

```python
# fetch_sources.py 加函数
def fetch_营养(url: str, max_articles: int = 5) -> list[dict]:
    """营养领域信源"""
    articles = []
    try:
        # 抓取逻辑（RSS/API/HTML）
        ...
        articles.append({
            "title": ..., "url": ..., "source": "营养-RSS",
            "points": 0, "published_at": ..., "summary": ...,
        })
    except Exception as e:
        print(f"  [营养] 抓取失败: {e}")
    return articles
```

然后在 `fetch_all()` 里加一行调用，`retry_pending()` 里加对应的恢复逻辑。

### 多信源去重

去重是自动的，不需要手动处理。`deduplicate()` 按两条规则：

1. **URL 完全相同** → 保留第一个
2. **标题相似度 > 85%** 且来自不同域名 → 保留第一个

这意味着同一篇论文被 Arxiv 和 HN 同时讨论时，只存一次。

### 判断信源值不值得加

| 标准 | 问法 |
|------|------|
| 信息独特性 | 这个源的视角是其他源没有的吗？ |
| 信号密度 | 10 篇里能有几篇值得进 raw？≥30% 就值得 |
| 更新频率 | 每天有新内容吗？周更也行，月更就不值得自动化 |
| 抓取难度 | API 还是需要爬虫？需要登录吗？ |
| 领域匹配 | 跟你的知识库领域有关吗？ |

**不值得加的信号**：
- 纯新闻聚合（其他源已经覆盖）
- 标题党/低质量博客
- 需要 JS 渲染的页面（不适合 `urlopen`）
- 付费墙后面

### 推荐待加信源

当你想扩展知识库时，可以考虑：

| 信源 | 适合领域 | 为什么值 |
|------|---------|---------|
| Reddit r/LocalLLaMA | agent | 本地部署实战，跟你场景最近 |
| HuggingFace Daily Papers | agent | 论文 + 社区讨论，质量高 |
| 知乎专栏（AI/Agent） | agent | 中文视角，英文源没有 |
| Twitter/X Lists | agent | 实时动态，但抓取难度大 |
| PubMed RSS | 营养/医学 | 营养学研究的官方源 |
| 少数派 RSS | 工具/效率 | 中文工具评测 |

---

## 遇到过的坑

### 1. awk RS 转义 — bash/awk 双层转义冲突
**现象：** `RS='\\*\\*\\*'` 不生效
**解决：** `RS='[*][*][*]'` 字符类写法

### 2. awk 没读文件 — 缺输入参数
**现象：** grep 能找到，`_process_file` 无输出
**解决：** `}' "$file"`

### 3. emoji 多字节导致数值截断
**现象：** points 提取为 0
**解决：** 用 `/([0-9]+) +points/` 正则捕获

### 4. 多词查询不支持
**现象：** `"agent memory"` 搜不到
**解决：** grep 用 `sed 's/ /|/g'` → `grep -E`；awk 拆 query 为词数组

### 5. 新旧笔记格式不兼容
**现象：** 旧笔记日期提取异常
**解决：** 加条件判断 `if (ln ~ /points +·/)`

### 6. 关联用 OR 匹配导致泛化 (2026-05-16)
**现象：** #agent 标签 13/25 篇共用，全部指向相同旧笔记
**解决：** 改 AND 匹配

### 7. HuggingFace 被墙 (2026-05-17)
**现象：** WinError 10060
**解决：** 设 `HF_ENDPOINT=https://hf-mirror.com`

### 8. 语义结果去重 (2026-05-17)
**现象：** MemOS 跨 3 天出现 3 次
**解决：** hybrid_merge.py 按 title 去重

### 9. process_new.sh $grep_pat 未定义导致崩溃 (2026-05-22)
**现象：** 管线在"搜索关联笔记"步骤退出，set -u 杀进程
**解决：** 补 `grep_pat=$(echo "$query" | sed 's/ /|/g')`

### 10. rank() 用 $2 当分数字段 (2026-05-22)
**现象：** 关键词模式所有分数归 0, 排名随机
**解决：** 改 $1 + replace 字段而非 prepend, format 字段偏移同步调整

### 11. --no-filter 被默认过滤覆盖 (2026-05-22)
**现象：** 死代码 `[ -z "${filter_relevance+x}" ]` + 空串覆盖
**解决：** 用 `filter_explicit` flag 区分"没设置过"和"显式设空"

### 12. sentence-transformers 本地模型不适合 cron 场景 (2026-06-12)
**现象：** `search_wiki` 改语义检索后首次调用卡 5 分钟+，cron 每天是新进程，每天都卡
**根因：** `paraphrase-multilingual-MiniLM-L12-v2` 120MB 模型需从 HuggingFace 镜像下载/加载，国内网络不稳定。且 DeepSeek API 没有 embeddings 端点，不能用 API 做向量化
**解决：** 改用 DeepSeek Chat 做 LLM 匹配——传 wiki 页面目录 + 查询词，LLM 返回匹配路径。零启动成本，每次 ~2s。失败降级关键词搜索

## 设计决策

- **三文件分离**：改参数只动 config.sh，改逻辑只动 engine.sh，入口不动
- **混合检索**：关键词 40% + 语义 60%，语义优先搜核心层
- **路径全硬编码**：Git Bash + 中文路径 + 空格下相对路径不可靠
- **降级策略**：embedding 不存在 → 纯关键词；模型下载失败 → 不阻塞
- **不做向量数据库**：当前规模 JSON 文件够用
- **awk 里 emoji 可做正则判断，不可用 substr 算字节偏移**
- **踩坑独立管**：pitfall 是项目工程知识, 不混在沈念画像里
- **raw 封存不反复碰**：入口处理一次, 7 天归档, 之后只搜核心层
- **知识边界感知**：语义检索最高分 < 0.3 时，不在结果中凑数，诚实告知知识库覆盖不足 + 给出外查建议
- **关联用 OR + 命中打分**：AND 匹配太严格（一个词拼写偏差就全丢），OR 匹配 + 命中词数降序排列，容错更好
- **策展加连续活跃触发器**：同一标签连续 ≥3 天出现新文章 + ≥8 篇总数 → 提前策展，不等到 15 篇/14 天
- **日报推 insight 而不是原始统计**：每天调 Claude 提炼 3-5 条要点（格式：🔥 标题 + 一句话），写 Obsidian + 推送。Claude 不可用时静默跳过
- **打标签输出三字段替代 one_liner**：tech_summary（技术拆解 50-100字）+ trend_signal（趋势判断 50-80字）+ relevance_to_me（与你的相关性 30-50字）。信息密度远超 ≤30字标题翻译。上游 fetch_and_tag.sh 产出，下游全部消费
- **消费端统一 fallback**：所有读取新字段的地方 `tech_summary // .one_liner`，新旧数据兼容
- **新字段追加到输出末尾不破坏序号**：search_engine.sh 的 awk 输出在 $15-$17 加新字段，rank()/format() 的 $1-$14 不变
- **异常检测用 7 日滑动均值**：今日标签数 vs 过去7天日均，超 2× 标记异常。纯 bash 实现，不调 Claude
- **搜索画像存 profile.json**：记录搜索词/结果数/盲区。用于个性化加权 + "你可能关心"匹配 + 盲区自动标记策展需求
- **主动简报在搜索前返回**：标签连续活跃或搜索 ≥2 次 → preemptive_brief.sh 提前生成简报存 curated/preemptive/。下次搜索命中时优先返回
- **反向链接不泛滥**：旧笔记被关联 ≥2 次才追加 "🔗 外部动态" section，每篇最多 5 条。用临时文件解决 subshell 变量丢失
- **策展三层触发**：常规（≥15篇+≥14天）+ 连续活跃（≥3天+≥8篇+≥7天）+ 内容信号（🔮 中 "早期信号/快速演进" 占比 >30%+≥5篇）
- **碰撞检测独立运行不阻塞**：调 Claude 对比新文章 vs wiki/综述，输出冲突/补充/替代标记到日志，管线继续。Claude 不可用时跳过
- **Librarian 核心定位从"信息管道"转向"注意力引擎"** (2026-05-30 架构重想)：不是管理资料，是管理注意力
- **信号分级替代标签分类**：tagger prompt 下一步加 `signal_level`（🔴🟡🟢⚪）+ `urgency_reason` + `action_for_you`
- **知识有机体 > 知识仓库**：wiki 更新不只是追加"最新动态"，要检测结论是否被新证据动摇
- **长期方向 — 从固定配置到学习型系统**：搜索历史 → 动态权重、阅读行为追踪、沈念对话信号接入
- **演进路线四步走**：① tagger 加 signal_level → ② 事件驱动 → ③ 追踪线程 + wiki 过期检测 + 周报 → ④ 行为追踪 + 动态权重
- **ArticleStore 统一数据模型** (2026-05-30)：所有模块通过 store 读写，不再各自解析 .md。.md 只是导出视图，索引是派生索引
- **抓取 retry + pending** (2026-05-30)：每个信源 3 次重试，全失败写入 .pending_fetches.json，下次 cron 优先补抓
- **索引 mtime 原子化** (2026-05-30)：先编码+写索引，最后才更新 state。编码失败 → state 不变 → 下次自动重试
- **搜索轻量路由** (2026-05-30)：LLM 一句话分类 broad/specific → broad 调高 core 层权重优先返回综述，specific 调高关键词权重优先返回细节
- **cron 入口切到 agent.py** (2026-05-30)：daily_run.sh 从调 4 个独立 shell 脚本改为单一 Python 入口
- **wiki/agent/ 四大类重组** (2026-05-30)：架构/ 工具/ 检索/ 评估 各含 _index(总览) + 知识页 + 综述。ReAct 四变体合并为一页
- **统一处理入口 process_incoming()** (2026-05-30)：cron 和手动投喂走同一套流程。数据源变化自动触发完整管线（标签→wiki→碰撞→索引），不再有两条并行路径
- **手动投喂进 core 层** (2026-05-30)：raw/{domain}/手动/ 独立于每日抓取，不受 7 天归档影响
- **领域自适应替代标签** (2026-05-30)：目录即分类，不打 tech_tag。摘要器自动判断领域，输出三维通用摘要（核心内容/价值判断/与你相关）。raw 和 wiki 都按领域组织，新增领域只需改 config.yaml
- **四路信源差异化** (2026-05-30)：Simon 工程视角、GitHub 早期项目、HN 社区讨论、Arxiv 论文。各用不同 query，互补不重叠。去重自动处理（URL 相同 + 标题 >85%）
- **信源可扩展** (2026-05-30)：加新信源 = config.yaml 加一段 + fetch_sources.py 加一个 fetch_xxx() + fetch_all() 加一行。新领域信源可混在一起，摘要器自动分领域路由
- **搜索分层返回** (2026-05-30)：搜索结果按 综述 → 知识 两层输出，raw 不返回（已被提炼到 wiki）。每层独立排序去重，Agent 拿到直接知道优先级
- **wiki [[双向链接]] 自动化** (2026-05-30)：wiki_updater 每次更新页面后，自动扫描同领域其他页面，按关键词命中找到最相关的 5 个，追加 ## 相关 段落。Obsidian 图谱自动连线
- **索引 ID 可读化** (2026-05-30)：indexer ID 从纯 hash 改为 type::relpath::heading 格式，搜索时能区分来源（wiki/review/raw）
- **raw 不参与搜索** (2026-05-30)：raw 的价值已被 wiki_updater 提炼到 wiki，搜索结果只返回综述 + wiki。手动投喂的文章同理
- **config.py 统一配置模块** (2026-06-01)：消除 18 处重复的 `load_config()` 函数定义，所有模块从 `config.py` 单点导入 `config` + `DEEPSEEK_API_KEY`。api key 不再靠 shell 环境变量传递，统一由 `config.py` 加载 `.env` 后注入 os.environ
- **三人小组策展替代旧策展+wiki更新** (2026-06-03)：Signal Agent（提炼信号）→ Curation Agent（先更新已有知识再判断新方向）→ Wiki Agent（审方案+写内容）。三个 Agent 用统一的北星——"帮助用户成为资深 Agent 工程师"。替代原来的 curator.py（阈值规则）和 wiki_updater.py.update()（逐篇 LLM 判断）
- **策展 feature flag + 全量回退** (2026-06-03)：`config.yaml` 中 `multi_agent_curation.enabled` 控制走新/旧链路。三人小组不做逐层降级——任何 Agent 异常直接穿透到 agent.py，全量回退到旧 curator + wiki_updater。要么三个全跑通，要么全回退
- **search_wiki 用 LLM 匹配替代本地 embedding 模型** (2026-06-12)：`tools.py` 的 `search_wiki()` 优先用 DeepSeek Chat 做查询→页面匹配（传 wiki 目录 + 查询词，LLM 返回匹配路径），失败降级关键词搜索。不加载 sentence-transformers——每天 cron 是新进程，120MB 模型首次加载 30-60s，且 HuggingFace 镜像不稳定。LLM 方式零启动成本，每次 ~2s，一天 8-12 次调用成本可忽略
- **千问评测器接入管线** (2026-06-12)：`reviewer.py` 在 `graph.py` 的 `run_curation_pipeline()` 执行完后自动调用。每天管线跑完即出质量评分，review_tracker 不断档。评测失败不阻塞主流程
