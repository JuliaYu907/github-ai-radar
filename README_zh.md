# GitHub AI Radar

**中文 | [English](README.md)**

[![Daily Report](https://github.com/JuliaYu907/github-ai-radar/actions/workflows/daily.yml/badge.svg)](https://github.com/JuliaYu907/github-ai-radar/actions/workflows/daily.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)

> Fork this repo and get **daily auto-generated AI trending reports** + a **live dashboard** via GitHub Actions & Pages. Zero maintenance.

抓取过去 48 小时 GitHub 上真正热门的 AI 仓库，以 **star 增长速率**而非总 star 数排序，帮你发现最新、最火的 AI 项目。

## 特性

- **每日自动运行** — GitHub Actions 定时抓取，报告自动 commit 到 `reports/` 目录
- **GitHub Pages 看板** — 暗色主题实时看板，Fork 后自动部署到 `https://<user>.github.io/github-ai-radar/`
- **多维度数据采集** — GitHub Search API (18 组 AI topic 查询 + 5 组新项目爆发查询) + GitHub Trending 页面爬取
- **增长驱动排序** — 热度评分公式: `today_stars(40%) + growth_rate(30%) + recency(15%) + base_stars(15%)`
- **真实增长速率** — 优先用历史报告对比算真实日增，回退到 Trending 当日增量，再回退到 `stars/√age`
- **新项目捕获** — 48 小时内创建且快速获星的全新项目优先展示
- **双榜单输出（去重）**
  - AI/LLM 核心仓库 Top 10 (框架、模型、训练推理工具)
  - AI 个人应用 Top 20 (CLI 工具、本地模型、个人助手等，过滤企业级平台，与核心榜去重)
- **完全可配置** — 通过 `config.yaml` 自定义关键词、评分权重、Top N 数量、搜索范围等
- **多格式报告** — 终端 Rich 表格 + JSON + Markdown + GitHub Pages HTML

## 一键部署（推荐）

Fork 本仓库后，GitHub Actions 会**每天自动运行**并将报告提交到你的仓库，GitHub Pages 会自动部署看板。

### 步骤

1. **Fork** 本仓库
2. 在 fork 的仓库中进入 **Settings → Secrets and variables → Actions**
3. 添加一个 Repository Secret:
   - Name: `GH_PAT`
   - Value: 你的 [GitHub Personal Access Token](https://github.com/settings/tokens)（需要 `public_repo` 权限）
4. 启用 **GitHub Pages**:
   - 进入 **Settings → Pages**
   - Source 选择 **GitHub Actions**
5. 进入 **Actions** 页面，启用 workflows
6. 点击 **Daily AI Trending Report → Run workflow** 手动触发一次，验证是否正常

之后每天 UTC 08:00（北京时间 16:00）会自动运行：
- 报告出现在 `reports/` 目录下
- 看板自动更新到 `https://<your-username>.github.io/github-ai-radar/`

> **Token 是可选的**：不配置也能跑，但 API 速率限制会从 30 req/min 降到 10 req/min，可能漏掉部分数据。

## 本地运行

### 环境要求

- Python 3.10+

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行

```bash
# 基本用法 (报告自动保存到 reports/YYYY-MM-DD/, Pages 生成到 docs/)
python github_trending.py

# 跳过 SSL 验证 (代理/VPN 环境)
python github_trending.py --no-verify

# 使用 GitHub Token 提升 API 速率限制 (10 → 30 req/min)
python github_trending.py --token ghp_xxxxxxxxxxxx
# 或通过环境变量:
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python github_trending.py

# 使用自定义配置文件
python github_trending.py --config my_config.yaml

# 指定输出路径 (同时生成 .json 和 .md)
python github_trending.py --output reports/custom/my_report

# 本地预览 GitHub Pages 看板
python -m http.server 8000 -d docs
# 然后打开 http://localhost:8000
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--token` | GitHub Personal Access Token，提升 API 速率 | 环境变量 `GITHUB_TOKEN` |
| `--no-verify` | 跳过 SSL 证书验证，解决代理/VPN 环境下的连接问题 | 关闭 |
| `--output` | 报告输出基础路径 (不含扩展名，同时生成 .json 和 .md) | `reports/YYYY-MM-DD/ai_trending_YYYY-MM-DD` |
| `--config` | 配置文件路径 | `config.yaml` |

## 配置文件

通过 `config.yaml` 自定义所有参数，无需修改代码：

```yaml
# 时间窗口
time_window_hours: 48

# 评分公式权重（必须加起来 = 1.0）
scoring:
  today_stars_weight: 0.40
  growth_rate_weight: 0.30
  recency_weight: 0.15
  base_stars_weight: 0.15

# 排行榜设置
rankings:
  core_top_n: 10
  app_top_n: 20
  deduplicate: true        # 核心榜出现的仓库不再出现在应用榜

# 搜索 topic 列表（可自定义追踪领域）
search_topics:
  - llm
  - machine-learning
  - ai-agent
  - mcp
  # ... 完整列表见 config.yaml

# 输出格式
output:
  formats: [json, markdown, html]
  pages_dir: docs
```

完整配置项和分类关键词见 [`config.yaml`](config.yaml)。

## 输出示例

### 终端输出

```
AI/LLM Core — Top 10 (Hottest)
┌──┬────────────────────────────┬──────┬───────┬───────┬─────────┬─────┐
│# │ Repository                 │ Lang │ Stars │ +Today│ Growth/d│ Hot │
├──┼────────────────────────────┼──────┼───────┼───────┼─────────┼─────┤
│1 │ milla-jovovich/mempalace   │ Py   │ 20.2k │ -     │ 11.2k/d │ 11.2│
│2 │ langgenius/dify            │ TS   │ 136k  │ -     │ 4.1k/d  │ 11.1│
│…
```

### GitHub Pages 看板

暗色主题卡片式布局，Top 3 有金/银/铜发光效果：

- 排名、仓库名（可点击）、语言徽章
- Star 总数、今日增量、日增速、热度评分
- NEW 标记（7 天内创建的新项目）
- 排名变化指示器（↑ 上升 / ↓ 下降 / ★ 新上榜）

### 目录结构

```
github-ai-radar/
├── README.md                          ← 英文 README
├── README_zh.md                       ← 中文 README
├── config.yaml                        ← 配置文件 (可自定义)
├── github_trending.py                 ← 主脚本
├── templates/
│   └── index.html                     ← Pages 模板
├── docs/                              ← GitHub Pages 站点 (自动生成)
│   ├── index.html
│   └── data/
│       └── latest.json
├── reports/                           ← 每日报告 (自动生成)
│   └── 2026-04-08/
│       ├── ai_trending_2026-04-08_en.md
│       ├── ai_trending_2026-04-08_zh.md
│       └── ai_trending_2026-04-08.json
└── .github/workflows/
    ├── daily.yml                      ← 每日自动运行
    └── pages.yml                      ← GitHub Pages 自动部署
```

## 工作原理

```
┌─────────────────────┐     ┌──────────────────────┐     ┌────────────────┐
│  GitHub Search API  │     │  GitHub Trending 页面 │     │  历史报告 JSON  │
│  23 组查询           │     │  当日 star 增量数据    │     │  (前日数据)     │
└────────┬────────────┘     └──────────┬───────────┘     └───────┬────────┘
         │                             │                         │
         └──────────┬──────────────────┴─────────────────────────┘
                    ▼
           ┌────────────────┐
           │  合并去重 ~2400 │
           └───────┬────────┘
                   ▼
           ┌────────────────────────────┐
           │  计算增长速率 (三级策略)      │
           │  1. 历史对比 → 真实日增      │
           │  2. Trending today_stars    │
           │  3. stars / √age           │
           └───────┬────────────────────┘
                   ▼
           ┌────────────────┐
           │  计算热度评分    │
           │  (可配置权重)    │
           └───────┬────────┘
                   ▼
           ┌──────────────────┐
           │  分类 (核心/应用)  │
           │  过滤企业级项目    │
           │  双榜单去重       │
           └───────┬──────────┘
                   ▼
        ┌────────────────────────────┐
        │  排序 & 输出                │
        │  JSON + Markdown + HTML    │
        │  GitHub Pages 看板更新      │
        └────────────────────────────┘
```

## 分类逻辑

**AI/LLM 核心** — 命中以下关键词的仓库: `machine-learning`, `deep-learning`, `llm`, `transformer`, `diffusion`, `pytorch`, `tensorflow`, `fine-tuning`, `inference`, `multimodal` 等

**AI 个人应用** — 命中 `ai-agent`, `chatbot`, `rag`, `copilot`, `ollama`, `mcp`, `prompt` 等关键词，并排除带有 `enterprise`, `saas`, `mlops`, `devops` 等企业级标签的项目；核心榜已有的仓库自动去重

> 所有分类关键词均可通过 `config.yaml` 自定义，也可用于追踪 AI 以外的领域。

## 贡献

欢迎 PR 和 Issue！

- **关键词补充** — 发现有 AI 仓库被遗漏？请提 Issue 或 PR 补充 `config.yaml` 中的分类关键词
- **Bug 修复** — 发现报告数据异常或脚本报错？请提 Issue 附上运行日志
- **新功能** — 有好的想法？先开 Issue 讨论，再提 PR

```bash
# 本地开发
git clone https://github.com/JuliaYu907/github-ai-radar.git
cd github-ai-radar
pip install -r requirements.txt
python github_trending.py --no-verify
```

## License

[MIT](LICENSE)
