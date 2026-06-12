#!/usr/bin/env bash
# 资料管理员 — 配置文件
# 调参、改路径、加字段 只改这一个文件

# ── 路径 ──────────────────────────────────────────────
OBSIDIAN_DIR="D:/obsidian/1/raw/每日AI动态"
OBSIDIAN_VAULT="D:/obsidian/1"
PITFALL_DIR="D:/obsidian/1/pitfalls"
LOG_DIR="D:/Claude code/librarian/logs"

# 全 vault 搜索范围（排除系统目录）
VAULT_EXCLUDE_DIRS=(".obsidian" ".claude" ".claudian" "templates")

# source_type 中文标签
declare -A SOURCE_TYPE_LABEL
SOURCE_TYPE_LABEL[article]="每日AI"
SOURCE_TYPE_LABEL[review]="综述"
SOURCE_TYPE_LABEL[pitfall]="踩坑"
SOURCE_TYPE_LABEL[personal]="关于我"
SOURCE_TYPE_LABEL[chat]="对话"
SOURCE_TYPE_LABEL["cli-session"]="CLI会话"
SOURCE_TYPE_LABEL[wiki]="Wiki"
SOURCE_TYPE_LABEL[report]="报告"
SOURCE_TYPE_LABEL[note]="笔记"

# ── 检索 ──────────────────────────────────────────────
MAX_RESULTS=8
MAX_SUMMARY_CHARS=300

# ── 关键词命中权重（标签 > 标题 > one_liner > 摘要） ──
# 总和建议不超过 1.0
WEIGHT_TAG=0.35
WEIGHT_TITLE=0.30
WEIGHT_ONE_LINER=0.20
WEIGHT_SUMMARY=0.15

# ── 权威度公式：1 + min(log10(points+1) / AUTHORITY_SCALE, AUTHORITY_MAX_BOOST) ──
AUTHORITY_SCALE=6
AUTHORITY_MAX_BOOST=0.5

# ── 时效衰减：TIME_DECAY_FLOOR + (1-FLOOR) × 0.7^(days_old / HALF_LIFE_DAYS) ──
HALF_LIFE_DAYS=30
TIME_DECAY_FLOOR=0.3

# ── 搜索的字段（按 .md frontmatter / 正文中的位置） ──
SEARCH_FIELDS=("tech_tag" "maturity_tag" "relevance" "title" "one_liner" "summary")

# ── 默认过滤 — 不指定时只看相关文章，设空则不启 ──
DEFAULT_FILTER_RELEVANCE="#可能与我的部署相关"

# ── 会话（V3） ──
SESSION_DIR="D:/Claude code/librarian/sessions"
SESSION_MAX_TURNS=10
SESSION_CONTEXT_TURNS=3

# ── 混合检索（V3: 三层索引） ──
HYBRID_KEYWORD_WEIGHT=0.4
HYBRID_SEMANTIC_WEIGHT=0.6
SEMANTIC_TOP_N=20

# ── 知识边界感知 ──
# 语义最高分低于此阈值时，在结果末尾追加"知识库覆盖不足"提示
BOUNDARY_THRESHOLD=0.3

# 三层索引文件（indexer.py 写入 indexes/ 目录）
CORE_INDEX="D:/Claude code/librarian/indexes/core_index.json"
RECENT_INDEX="D:/Claude code/librarian/indexes/recent_index.json"
ARCHIVE_INDEX="D:/Claude code/librarian/indexes/archive_index.json"

# 兼容旧引用
EMBEDDINGS_FILE="$CORE_INDEX"

# 层级检索权重 (core 优先)
LAYER_WEIGHT_CORE=1.5
LAYER_WEIGHT_RECENT=1.0
LAYER_WEIGHT_ARCHIVE=0.0  # 默认不参与检索

INDEX_BUILDER="D:/Claude code/librarian/indexer.py"
INDEX_MANAGER="D:/Claude code/librarian/indexer.py"

# ── 自主策展（V7） ──
CURATE_MIN_ARTICLES=15
CURATE_REFRESH_DAYS=14
CURATED_DIR="D:/obsidian/1/curated"
CURATE_MANIFEST="D:/Claude code/librarian/curated/manifest.json"

# 策展触发 — 连续活跃（提前触发，不等到 15 篇）
CURATE_CONSEC_MIN_COUNT=8   # 连续活跃时最低篇数
CURATE_CONSEC_MIN_DAYS=3    # 连续出现天数
CURATE_CONSEC_REFRESH=7     # 连续活跃时刷新间隔（天）

# ── 主动处理（process_new.sh） ──
MAX_RELATED_PER_ARTICLE=2
MIN_RELEVANCE_SCORE=0.05

# ── 标签统计排序 ──
TAG_ORDER=("#agent" "#rag" "#prompt-engineering" "#vllm" "#model-release" "#benchmark" "#tools" "#其他")
