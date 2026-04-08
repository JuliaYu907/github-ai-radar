# GitHub AI Radar

**[中文](README_zh.md) | English**

[![Daily Report](https://github.com/JuliaYu907/github-ai-radar/actions/workflows/daily.yml/badge.svg)](https://github.com/JuliaYu907/github-ai-radar/actions/workflows/daily.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)

> Fork this repo and get **daily auto-generated AI trending reports** + a **live dashboard** via GitHub Actions & Pages. Zero maintenance.

Discover the hottest AI repositories on GitHub from the past 48 hours, ranked by **star growth rate** instead of total stars — helping you spot the newest and most trending AI projects.

## Features

- **Auto-run daily** — GitHub Actions fetches data on schedule and auto-commits reports to the `reports/` directory
- **GitHub Pages Dashboard** — Dark-themed live dashboard, auto-deployed after forking to `https://<user>.github.io/github-ai-radar/`
- **Multi-source data collection** — GitHub Search API (18 AI topic queries + 5 new-project burst queries) + GitHub Trending page scraping
- **Growth-driven ranking** — Hotness scoring formula: `today_stars(40%) + growth_rate(30%) + recency(15%) + base_stars(15%)`
- **Real growth rate** — Prioritizes historical report comparison for true daily gain, falls back to Trending daily increment, then to `stars/√age`
- **New project detection** — Brand-new projects created within 48 hours that gain stars quickly are highlighted
- **Dual rankings (deduplicated)**
  - AI/LLM Core Repos Top 10 (frameworks, models, training & inference tools)
  - AI Personal Apps Top 20 (CLI tools, local models, personal assistants, etc. — enterprise platforms filtered out, deduplicated against Core ranking)
- **Fully configurable** — Customize keywords, scoring weights, Top N counts, search scope, and more via `config.yaml`
- **Multi-format reports** — Terminal Rich tables + JSON + Markdown + GitHub Pages HTML

## One-Click Deploy (Recommended)

After forking this repo, GitHub Actions will **run automatically every day**, committing reports to your repository. GitHub Pages will auto-deploy the dashboard.

### Steps

1. **Fork** this repository
2. In your forked repo, go to **Settings → Secrets and variables → Actions**
3. Add a Repository Secret:
   - Name: `GH_PAT`
   - Value: Your [GitHub Personal Access Token](https://github.com/settings/tokens) (requires `public_repo` scope)
4. Enable **GitHub Pages**:
   - Go to **Settings → Pages**
   - Set Source to **GitHub Actions**
5. Go to the **Actions** tab and enable workflows
6. Click **Daily AI Trending Report → Run workflow** to trigger a manual run and verify everything works

After that, it runs automatically every day at UTC 08:00 (16:00 Beijing Time):
- Reports appear in the `reports/` directory
- Dashboard auto-updates at `https://<your-username>.github.io/github-ai-radar/`

> **Token is optional**: It works without one, but the API rate limit drops from 30 req/min to 10 req/min, potentially missing some data.

## Local Usage

### Requirements

- Python 3.10+

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run

```bash
# Basic usage (reports auto-saved to reports/YYYY-MM-DD/, Pages generated to docs/)
python github_trending.py

# Skip SSL verification (proxy/VPN environments)
python github_trending.py --no-verify

# Use a GitHub Token to increase API rate limit (10 → 30 req/min)
python github_trending.py --token ghp_xxxxxxxxxxxx
# Or via environment variable:
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python github_trending.py

# Use a custom config file
python github_trending.py --config my_config.yaml

# Specify output path (generates both .json and .md)
python github_trending.py --output reports/custom/my_report

# Preview GitHub Pages dashboard locally
python -m http.server 8000 -d docs
# Then open http://localhost:8000
```

### CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--token` | GitHub Personal Access Token to increase API rate limit | Env variable `GITHUB_TOKEN` |
| `--no-verify` | Skip SSL certificate verification for proxy/VPN environments | Disabled |
| `--output` | Base path for report output (without extension; generates both .json and .md) | `reports/YYYY-MM-DD/ai_trending_YYYY-MM-DD` |
| `--config` | Path to configuration file | `config.yaml` |

## Configuration

Customize all parameters via `config.yaml` — no code changes needed:

```yaml
# Time window
time_window_hours: 48

# Scoring formula weights (must sum to 1.0)
scoring:
  today_stars_weight: 0.40
  growth_rate_weight: 0.30
  recency_weight: 0.15
  base_stars_weight: 0.15

# Ranking settings
rankings:
  core_top_n: 10
  app_top_n: 20
  deduplicate: true        # Repos in Core ranking won't appear in App ranking

# Search topic list (customize to track any domain)
search_topics:
  - llm
  - machine-learning
  - ai-agent
  - mcp
  # ... see config.yaml for the full list

# Output formats
output:
  formats: [json, markdown, html]
  pages_dir: docs
```

See [`config.yaml`](config.yaml) for all configuration options and classification keywords.

## Output Examples

### Terminal Output

```
AI/LLM Core — Top 10 (Hottest)
┌──┬────────────────────────────┬──────┬───────┬───────┬─────────┬─────┐
│# │ Repository                 │ Lang │ Stars │ +Today│ Growth/d│ Hot │
├──┼────────────────────────────┼──────┼───────┼───────┼─────────┼─────┤
│1 │ milla-jovovich/mempalace   │ Py   │ 20.2k │ -     │ 11.2k/d │ 11.2│
│2 │ langgenius/dify            │ TS   │ 136k  │ -     │ 4.1k/d  │ 11.1│
│…
```

### GitHub Pages Dashboard

Dark-themed card layout with gold/silver/bronze glow effects for the Top 3:

- Rank, repository name (clickable), language badge
- Total stars, today's increment, daily growth rate, hotness score
- NEW badge (for projects created within the last 7 days)
- Rank change indicators (↑ rising / ↓ falling / ★ new entry)

### Directory Structure

```
github-ai-radar/
├── README.md                          ← English README
├── README_zh.md                       ← Chinese README
├── config.yaml                        ← Configuration file (customizable)
├── github_trending.py                 ← Main script
├── templates/
│   └── index.html                     ← Pages template
├── docs/                              ← GitHub Pages site (auto-generated)
│   ├── index.html
│   └── data/
│       └── latest.json
├── reports/                           ← Daily reports (auto-generated)
│   └── 2026-04-08/
│       ├── ai_trending_2026-04-08_en.md
│       ├── ai_trending_2026-04-08_zh.md
│       └── ai_trending_2026-04-08.json
└── .github/workflows/
    ├── daily.yml                      ← Daily auto-run
    └── pages.yml                      ← GitHub Pages auto-deploy
```

## How It Works

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  GitHub Search API  │     │  GitHub Trending Page │     │  Historical Report   │
│  23 queries         │     │  Daily star increment │     │  JSON (prev. day)    │
│                     │     │  data                 │     │                      │
└────────┬────────────┘     └──────────┬───────────┘     └───────┬─────────────┘
         │                             │                         │
         └──────────┬──────────────────┴─────────────────────────┘
                    ▼
           ┌───────────────────────┐
           │  Merge & deduplicate  │
           │  ~2400 repos          │
           └───────┬───────────────┘
                   ▼
           ┌────────────────────────────────────┐
           │  Compute growth rate               │
           │  (3-tier strategy)                 │
           │  1. Historical comparison          │
           │     → real daily gain              │
           │  2. Trending today_stars           │
           │  3. stars / √age                  │
           └───────┬────────────────────────────┘
                   ▼
           ┌────────────────────────┐
           │  Compute hotness score │
           │  (configurable weights)│
           └───────┬────────────────┘
                   ▼
           ┌──────────────────────────┐
           │  Classify (Core / App)   │
           │  Filter enterprise       │
           │  projects                │
           │  Deduplicate dual        │
           │  rankings                │
           └───────┬──────────────────┘
                   ▼
        ┌────────────────────────────────┐
        │  Sort & output                 │
        │  JSON + Markdown + HTML        │
        │  GitHub Pages dashboard update │
        └────────────────────────────────┘
```

## Classification Logic

**AI/LLM Core** — Repositories matching keywords such as: `machine-learning`, `deep-learning`, `llm`, `transformer`, `diffusion`, `pytorch`, `tensorflow`, `fine-tuning`, `inference`, `multimodal`, etc.

**AI Personal Apps** — Repositories matching keywords like `ai-agent`, `chatbot`, `rag`, `copilot`, `ollama`, `mcp`, `prompt`, etc., excluding projects tagged with enterprise labels such as `enterprise`, `saas`, `mlops`, `devops`; repos already in the Core ranking are automatically deduplicated

> All classification keywords can be customized via `config.yaml` and can also be used to track domains beyond AI.

## Contributing

PRs and Issues are welcome!

- **Keyword additions** — Found an AI repo that's being missed? Open an Issue or PR to add classification keywords in `config.yaml`
- **Bug fixes** — Found data anomalies in reports or script errors? Open an Issue with your run logs
- **New features** — Have a great idea? Open an Issue to discuss first, then submit a PR

```bash
# Local development
git clone https://github.com/JuliaYu907/github-ai-radar.git
cd github-ai-radar
pip install -r requirements.txt
python github_trending.py --no-verify
```

## License

[MIT](LICENSE)
