# GitHub AI Radar

[![Daily Report](https://github.com/YOUR_USERNAME/github-ai-radar/actions/workflows/daily.yml/badge.svg)](https://github.com/YOUR_USERNAME/github-ai-radar/actions/workflows/daily.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)

> Fork this repo and get **daily auto-generated AI trending reports** via GitHub Actions. Zero maintenance.

抓取过去 48 小时 GitHub 上真正热门的 AI 仓库，以 **star 增长速率**而非总 star 数排序，帮你发现最新、最火的 AI 项目。

## 特性

- **每日自动运行** — GitHub Actions 定时抓取，报告自动 commit 到 `reports/` 目录
- **多维度数据采集** — GitHub Search API (19 组 AI 关键词查询) + GitHub Trending 页面爬取
- **增长驱动排序** — 热度评分公式: `today_stars(40%) + growth_rate(30%) + recency(15%) + base_stars(15%)`
- **新项目捕获** — 48 小时内创建且快速获星的全新项目优先展示
- **双榜单输出**
  - AI/LLM 核心仓库 Top 10 (框架、模型、训练推理工具)
  - AI 个人应用 Top 20 (CLI 工具、本地模型、个人助手等，过滤企业级平台)
- **多格式报告** — 终端 Rich 表格 + JSON 报告 + Markdown 报告

## 一键部署（推荐）

Fork 本仓库后，GitHub Actions 会**每天自动运行**并将报告提交到你的仓库。

### 步骤

1. **Fork** 本仓库
2. 在 fork 的仓库中进入 **Settings → Secrets and variables → Actions**
3. 添加一个 Repository Secret:
   - Name: `GH_PAT`
   - Value: 你的 [GitHub Personal Access Token](https://github.com/settings/tokens)（需要 `public_repo` 权限）
4. 进入 **Actions** 页面，启用 workflows
5. 点击 **Daily AI Trending Report → Run workflow** 手动触发一次，验证是否正常

之后每天 UTC 08:00（北京时间 16:00）会自动运行，报告出现在 `reports/` 目录下。

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
# 基本用法 (报告自动保存到 reports/YYYY-MM-DD/)
python github_trending.py

# 跳过 SSL 验证 (代理/VPN 环境)
python github_trending.py --no-verify

# 使用 GitHub Token 提升 API 速率限制 (10 → 30 req/min)
python github_trending.py --token ghp_xxxxxxxxxxxx
# 或通过环境变量:
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python github_trending.py

# 指定输出路径 (同时生成 .json 和 .md)
python github_trending.py --output reports/custom/my_report
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--token` | GitHub Personal Access Token，提升 API 速率 | 环境变量 `GITHUB_TOKEN` |
| `--no-verify` | 跳过 SSL 证书验证，解决代理/VPN 环境下的连接问题 | 关闭 |
| `--output` | 报告输出基础路径 (不含扩展名，同时生成 .json 和 .md) | `reports/YYYY-MM-DD/github_hot_repo_YYYY-MM-DD` |

## 输出示例

### 终端输出

```
AI/LLM Core — Top 10 (48h Hottest)
┌──┬────────────────────────────┬──────┬───────┬───────┬─────────┬─────┐
│# │ Repository                 │ Lang │ Stars │ +Today│ Growth/d│ Hot │
├──┼────────────────────────────┼──────┼───────┼───────┼─────────┼─────┤
│1 │ affaan-m/everything-claud… │ JS   │ 134k  │ -     │ 1.8k/d  │ 10.3│
│2 │ JackChen-me/open-multi-a… │ TS   │ 2.8k  │ -     │ 1.1k/d  │ 9.24│
│…
```

### 报告目录结构

```
reports/
├── 2026-04-03/
│   ├── github_hot_repo_2026-04-03.md    ← Markdown 报告 (适合阅读/分享)
│   └── github_hot_repo_2026-04-03.json  ← JSON 报告 (适合程序消费)
├── 2026-04-04/
│   ├── github_hot_repo_2026-04-04.md
│   └── github_hot_repo_2026-04-04.json
└── ...
```

## 工作原理

```
┌─────────────────────┐     ┌──────────────────────┐
│  GitHub Search API  │     │  GitHub Trending 页面 │
│  19 组 AI 关键词查询 │     │  当日 star 增量数据    │
└────────┬────────────┘     └──────────┬───────────┘
         │                             │
         └──────────┬──────────────────┘
                    ▼
           ┌────────────────┐
           │  合并去重 ~2000 │
           └───────┬────────┘
                   ▼
           ┌────────────────┐
           │  计算增长速率    │
           │  计算热度评分    │
           └───────┬────────┘
                   ▼
           ┌────────────────┐
           │  分类 (核心/应用)│
           │  过滤企业级项目  │
           └───────┬────────┘
                   ▼
        ┌──────────────────────┐
        │  排序 & 输出双榜单    │
        │  JSON + Markdown 报告│
        └──────────────────────┘
```

## 分类逻辑

**AI/LLM 核心** — 命中以下关键词的仓库: `machine-learning`, `deep-learning`, `llm`, `transformer`, `diffusion`, `pytorch`, `tensorflow`, `fine-tuning`, `inference` 等

**AI 个人应用** — 命中 `ai-agent`, `chatbot`, `rag`, `copilot`, `ollama`, `prompt` 等关键词，并排除带有 `enterprise`, `saas`, `mlops`, `devops` 等企业级标签的项目

## 贡献

欢迎 PR 和 Issue！

- **关键词补充** — 发现有 AI 仓库被遗漏？请提 Issue 或 PR 补充分类关键词
- **Bug 修复** — 发现报告数据异常或脚本报错？请提 Issue 附上运行日志
- **新功能** — 有好的想法？先开 Issue 讨论，再提 PR

```bash
# 本地开发
git clone https://github.com/YOUR_USERNAME/github-ai-radar.git
cd github-ai-radar
pip install -r requirements.txt
python github_trending.py --no-verify
```

## License

[MIT](LICENSE)
