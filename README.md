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
- **Accurate project introductions** — Combines each repository's official GitHub About text with its most informative README paragraphs while filtering badges, installation commands, warnings, and promotional noise
- **Bilingual descriptions** — Keeps an evidence-based English introduction and generates a faithful Chinese translation for the dashboard's language tabs
- **Dual rankings (deduplicated)**
  - AI/LLM Core Repos Top 10 (frameworks, models, training & inference tools)
  - AI Personal Apps Top 20 (CLI tools, local models, personal assistants, etc. — enterprise platforms filtered out, deduplicated against Core ranking)
- **Fully configurable** — Customize keywords, scoring weights, Top N counts, search scope, and more via `config.yaml`
- **Multi-format reports** — Terminal Rich tables + JSON + Markdown + GitHub Pages HTML

## One-Click Deploy (Recommended)

After forking this repo, GitHub Actions will **run automatically every day**, committing reports to your repository. GitHub Pages will auto-deploy the dashboard.

### Steps

1. **Fork** this repository
2. Enable **GitHub Pages**:
   - Go to **Settings → Pages**
   - Set Source to **GitHub Actions**
3. Go to the **Actions** tab and enable workflows
4. Click **Daily AI Trending Report → Run workflow** to trigger a manual run and verify everything works

After that, it runs automatically every day at UTC 08:00 (16:00 Beijing Time):
- Reports appear in the `reports/` directory
- Dashboard auto-updates at `https://<your-username>.github.io/github-ai-radar/`

> No personal access token or LLM API key is required for GitHub Actions. The workflow uses its job-scoped `GITHUB_TOKEN` for GitHub API access and GitHub Models; the required `contents`, `pages`, `id-token`, and `models` permissions are already declared in `daily.yml`.

To use a different OpenAI-compatible provider, optionally add `LLM_API_KEY`, `LLM_API_BASE`, and `LLM_MODEL` under **Settings → Secrets and variables → Actions**.

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

# Use a GitHub token to increase the API rate limit
python github_trending.py --token <YOUR_GITHUB_TOKEN>
# Or via environment variable:
export GITHUB_TOKEN=<YOUR_GITHUB_TOKEN>
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
| `--output` | Base path for report output (without extension; generates both .json and .md) | `reports/YYYY-MM-DD/github_ai_hot_repo_YYYY-MM-DD` |
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

# README extraction and bilingual introductions
readme:
  max_chars: 262144
  summary_max_chars: 320

llm:
  enabled: true
  batch_size: 10
  max_summary_chars: 220
  temperature: 0.1
```

See [`config.yaml`](config.yaml) for all configuration options and classification keywords.

### Bilingual Project Introductions

The English introduction is grounded in the repository's official GitHub About text and a filtered, scored selection of its README. The Chinese introduction is a faithful translation of that evidence rather than an invented marketing summary.

GitHub Actions uses GitHub Models by default with the job-scoped `GITHUB_TOKEN`, so forks do not need an additional secret. For local runs or a custom OpenAI-compatible provider, export:

```bash
export LLM_API_KEY=<YOUR_LLM_API_KEY>
export LLM_API_BASE=<YOUR_OPENAI_COMPATIBLE_ENDPOINT>
export LLM_MODEL=<YOUR_MODEL_NAME>
```

If translation is unavailable, the dashboard still shows the accurate official About/README-based English introduction instead of fabricating content.

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
- Introduction source badge: `About`, `README`, or `About + README`
- `中文` / `EN` tabs switch between the actual `intro_zh` and `intro_en` fields
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
│       ├── github_ai_hot_repo_2026-04-08_en.md
│       ├── github_ai_hot_repo_2026-04-08_zh.md
│       └── github_ai_hot_repo_2026-04-08.json
└── .github/workflows/
    ├── daily.yml                      ← Daily generation, commit, and Pages deployment
    └── pages.yml                      ← Manual/docs-push Pages deployment fallback
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
        │  Fetch About + README          │
        │  Extract and score core text   │
        │  Build intro_en + intro_zh     │
        └───────────────┬────────────────┘
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
