"""
GitHub AI Radar — 过去 48 小时真正热门的 AI 仓库追踪器

核心理念: 用 star 增量 / 增长速率排序, 而非总 star 数
  - today_stars  : 来自 GitHub Trending 页面 (当日 star 增量, 最准确)
  - growth_rate  : 与昨日报告对比的真实增速, 回退到 stars / sqrt(age)
  - 新创建查询   : created:>48h 捕获刚爆发的全新项目

榜单:
  1. AI/LLM 核心仓库 Top N
  2. AI 应用类仓库 Top N (个人使用向, 排除企业级)

用法:
  python github_trending.py [--token GITHUB_TOKEN] [--no-verify] [--output FILE] [--config FILE]
"""

import argparse
import base64
import io
import json
import math
import os
import re as _re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import urllib3
import requests
import yaml
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(force_terminal=True)

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"

# 内置默认值 (config.yaml 缺失或字段缺失时的回退)
DEFAULTS: dict[str, Any] = {
    "time_window_hours": 48,
    "api": {
        "pages_per_query": 2,
        "per_page": 100,
        "request_interval": 2,
        "rate_limit_sleep": 12,
        "max_retries": 3,
    },
    "scoring": {
        "today_stars_weight": 0.40,
        "growth_rate_weight": 0.30,
        "recency_weight": 0.15,
        "base_stars_weight": 0.15,
    },
    "rankings": {
        "core_top_n": 10,
        "app_top_n": 20,
        "deduplicate": True,
    },
    "output": {
        "reports_dir": "reports",
        "formats": ["json", "markdown", "html"],
        "pages_dir": "docs",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典, override 的值覆盖 base."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path: Optional[str] = None) -> dict:
    """加载配置文件, 与默认值合并."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        console.print(f"  [dim]配置文件: {cfg_path}[/dim]")
        return _deep_merge(DEFAULTS, user_cfg)
    console.print(f"  [dim]未找到配置文件, 使用内置默认值[/dim]")
    return DEFAULTS.copy()


# ---------------------------------------------------------------------------
# 全局状态 (在 main 中初始化)
# ---------------------------------------------------------------------------
SSL_VERIFY: bool = True
NOW: datetime = datetime.now(timezone.utc)
CFG: dict = {}

# ---------------------------------------------------------------------------
# 分类逻辑
# ---------------------------------------------------------------------------


def _get_sets(section: str) -> dict:
    """从配置中获取分类关键词集合."""
    cls = CFG.get("classification", {})
    return {
        "core_topics": set(cls.get("core_topics", [])),
        "core_kw_desc": cls.get("core_keywords_in_desc", []),
        "core_kw_name": cls.get("core_keywords_in_name", []),
        "app_topics": set(cls.get("app_topics", [])),
        "app_kw_desc": cls.get("app_keywords_in_desc", []),
        "app_kw_name": cls.get("app_keywords_in_name", []),
        "enterprise_topics": set(cls.get("enterprise_topics", [])),
        "enterprise_kw_desc": cls.get("enterprise_keywords_in_desc", []),
        "personal_boost_kw": cls.get("personal_boost_keywords", []),
    }


def _is_personal_use(repo: dict, kw: dict) -> bool:
    """过滤: 排除企业级平台, 保留个人使用向的 AI 应用."""
    desc = (repo.get("description") or "").lower()
    topics = set(t.lower() for t in repo.get("topics", []))
    if topics & kw["enterprise_topics"]:
        return False
    if any(k in desc for k in kw["enterprise_kw_desc"]):
        return False
    return True


def _classify(repo: dict, kw: dict) -> tuple[bool, bool]:
    topics = set(t.lower() for t in repo.get("topics", []))
    desc = (repo.get("description") or "").lower()
    # 仅对仓库名部分做匹配 (不含 owner), 避免误判
    full_name = (repo.get("full_name") or "")
    repo_name = full_name.split("/")[-1].lower() if "/" in full_name else full_name.lower()

    is_core = bool(topics & kw["core_topics"]) or any(k in desc for k in kw["core_kw_desc"])
    is_app = bool(topics & kw["app_topics"]) or any(k in desc for k in kw["app_kw_desc"])

    for k in kw["core_kw_name"]:
        if k in repo_name:
            is_core = True
    for k in kw["app_kw_name"]:
        if k in repo_name:
            is_app = True

    return is_core, is_app


# ---------------------------------------------------------------------------
# GitHub Search API
# ---------------------------------------------------------------------------

SEARCH_URL = "https://api.github.com/search/repositories"
HEADERS_BASE = {"Accept": "application/vnd.github+json"}


def _headers(token: Optional[str] = None) -> dict:
    h = HEADERS_BASE.copy()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _search(query: str, token: Optional[str] = None) -> list[dict]:
    """搜索仓库, 支持指数退避重试."""
    api_cfg = CFG.get("api", {})
    pages = api_cfg.get("pages_per_query", 2)
    per_page = api_cfg.get("per_page", 100)
    interval = api_cfg.get("request_interval", 2)
    max_retries = api_cfg.get("max_retries", 3)
    base_sleep = api_cfg.get("rate_limit_sleep", 12)

    headers = _headers(token)
    repos: list[dict] = []

    for page in range(1, pages + 1):
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": per_page, "page": page}

        for attempt in range(max_retries):
            try:
                resp = requests.get(SEARCH_URL, headers=headers, params=params,
                                    timeout=15, verify=SSL_VERIFY)
                if resp.status_code == 403:
                    wait = base_sleep * (2 ** attempt)
                    # 尝试从 header 获取精确等待时间
                    reset = resp.headers.get("X-RateLimit-Reset")
                    if reset:
                        try:
                            wait = max(int(reset) - int(time.time()) + 1, 1)
                        except (ValueError, TypeError):
                            pass
                    console.print(f"  [yellow]速率受限, 等待 {wait}s (retry {attempt+1}/{max_retries})...[/yellow]")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                if data.get("incomplete_results"):
                    console.print(f"  [yellow]搜索结果不完整 (GitHub 超时)[/yellow]")
                if not items:
                    break
                repos.extend(items)
                break
            except requests.RequestException as exc:
                if attempt < max_retries - 1:
                    time.sleep(base_sleep)
                    continue
                console.print(f"  [red]请求失败 (page {page}): {exc}[/red]")
                break
        else:
            console.print(f"  [red]page {page} 重试耗尽[/red]")

        time.sleep(interval)
    return repos


def fetch_ai_repos(token: Optional[str] = None) -> list[dict]:
    """
    多维度搜索策略:
      A) pushed:>time_window + topic:X  → 活跃的已有项目
      B) created:>time_window + AI 关键词 → 新创建且快速增长的项目
    """
    hours = CFG.get("time_window_hours", 48)
    d2 = (NOW - timedelta(hours=hours)).strftime("%Y-%m-%d")

    # A: 主力查询 — 各 AI topic 下最近有 push 的项目
    search_topics = CFG.get("search_topics", [
        "llm", "machine-learning", "deep-learning", "ai-agent",
        "generative-ai", "chatbot", "rag", "langchain",
        "transformer", "diffusion", "nlp", "computer-vision",
        "openai", "agent",
    ])
    topic_queries = [f"pushed:>{d2} topic:{t}" for t in search_topics]

    # B: 新项目爆发查询
    min_stars = CFG.get("new_project_min_stars", {})
    new_queries = [
        f"created:>{d2} stars:>{min_stars.get('ai', 50)} topic:ai",
        f"created:>{d2} stars:>{min_stars.get('llm', 50)} topic:llm",
        f"created:>{d2} stars:>{min_stars.get('agent', 20)} topic:agent",
        f"created:>{d2} stars:>{min_stars.get('general', 50)} machine learning",
        f"created:>{d2} stars:>{min_stars.get('general', 50)} deep learning",
    ]

    all_queries = topic_queries + new_queries
    seen: dict[str, dict] = {}
    total = len(all_queries)

    for idx, q in enumerate(all_queries, 1):
        label = q.split("topic:")[-1] if "topic:" in q else q.split(f">{d2} ")[-1]
        console.print(f"  [dim][{idx}/{total}] {label[:40]}...[/dim]")
        items = _search(q, token=token)
        for repo in items:
            key = repo.get("full_name", "").lower()
            if key not in seen:
                seen[key] = repo
        console.print(f"       +{len(items)} (累计 {len(seen)})")

    return list(seen.values())


# ---------------------------------------------------------------------------
# GitHub Trending (今日 star 增量的黄金数据源)
# ---------------------------------------------------------------------------

TRENDING_URL = "https://github.com/trending"

# 多套 CSS 选择器, 按优先级尝试
TRENDING_SELECTORS = [
    {   # 当前已知结构 (2024-2026)
        "row": "article.Box-row",
        "name": "h2 a",
        "desc": "p",
        "lang": "[itemprop='programmingLanguage']",
        "stars_link": "a.Link--muted",
        "today": "span.d-inline-block.float-sm-right",
    },
    {   # 降级: 更宽泛的选择器
        "row": "article",
        "name": "h2 a",
        "desc": "p",
        "lang": "[itemprop='programmingLanguage']",
        "stars_link": "a.Link--muted",
        "today": "span.float-sm-right",
    },
]


def fetch_trending() -> list[dict]:
    """从 GitHub Trending 页面抓取今日 star 增量."""
    try:
        resp = requests.get(
            TRENDING_URL, params={"since": "daily"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15, verify=SSL_VERIFY,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        console.print(f"  [red]Trending 请求失败: {exc}[/red]")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    repos: list[dict] = []

    # 尝试多套选择器
    for selectors in TRENDING_SELECTORS:
        rows = soup.select(selectors["row"])
        if len(rows) < 3:
            continue

        for row in rows:
            h2 = row.select_one(selectors["name"])
            if not h2:
                continue
            full_name = h2.get("href", "").strip("/")
            if not full_name or "/" not in full_name:
                continue

            desc_tag = row.select_one(selectors["desc"])
            lang_tag = row.select_one(selectors["lang"])

            stars_total = forks_total = today_stars = 0
            for link in row.select(selectors["stars_link"]):
                href = link.get("href", "")
                text = link.get_text(strip=True).replace(",", "")
                num = _parse_int(text)
                if "/stargazers" in href:
                    stars_total = num
                elif "/forks" in href:
                    forks_total = num

            ts = row.select_one(selectors["today"])
            if ts:
                today_stars = _parse_int(ts.get_text(strip=True))

            repos.append({
                "full_name": full_name,
                "description": desc_tag.get_text(strip=True) if desc_tag else "",
                "language": lang_tag.get_text(strip=True) if lang_tag else "",
                "stargazers_count": stars_total,
                "forks_count": forks_total,
                "today_stars": today_stars,
                "source": "trending",
            })

        # 选择器成功, 跳出
        break

    # 健壮性校验
    if not repos:
        console.print("  [yellow]警告: Trending 页面未解析到任何仓库 (选择器可能已过期)[/yellow]")
    elif len(repos) < 10:
        console.print(f"  [yellow]警告: Trending 仅解析到 {len(repos)} 个仓库 (预期 ~25)[/yellow]")

    return repos


def _parse_int(text: str) -> int:
    cleaned = "".join(ch for ch in text if ch.isdigit())
    return int(cleaned) if cleaned else 0


# ---------------------------------------------------------------------------
# 历史对比 — 用于计算真实增长速率
# ---------------------------------------------------------------------------


def _load_previous_report() -> dict[str, dict]:
    """加载前一天的 JSON 报告, 返回 {full_name_lower: repo_summary}."""
    reports_dir = Path(CFG.get("output", {}).get("reports_dir", "reports"))
    if not reports_dir.exists():
        return {}

    # 查找最近的报告目录 (排除今天)
    today_str = NOW.strftime("%Y-%m-%d")
    date_dirs = sorted(
        [d for d in reports_dir.iterdir() if d.is_dir() and d.name != today_str and d.name[:4].isdigit()],
        reverse=True,
    )

    for d in date_dirs[:3]:  # 最多回溯 3 天
        json_files = list(d.glob("*.json"))
        for jf in json_files:
            if "details" in jf.name:
                continue
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                prev: dict[str, dict] = {}
                for section in ("ai_llm_core_top10", "ai_app_top20"):
                    for r in data.get(section, []):
                        key = (r.get("full_name") or "").lower()
                        if key:
                            prev[key] = r
                if prev:
                    console.print(f"  [dim]历史数据: {jf.name} ({len(prev)} 个仓库)[/dim]")
                    return prev
            except (json.JSONDecodeError, OSError):
                continue
    return {}


# ---------------------------------------------------------------------------
# 增长速率 & 热度评分 (核心改造)
# ---------------------------------------------------------------------------


def _compute_growth_rate(repo: dict, prev_data: dict[str, dict]) -> float:
    """
    计算增长速率, 优先使用真实数据:
      1. 如果有昨天的报告, 用 (today_stars - yesterday_stars) 作为真实日增
      2. 如果有 today_stars (来自 Trending), 直接使用
      3. 回退到 total_stars / sqrt(age_days), 比 total/age 更公平
    """
    stars = repo.get("stargazers_count", 0)
    key = (repo.get("full_name") or "").lower()
    today = repo.get("today_stars", 0)

    # 方法 1: 历史对比
    if key in prev_data:
        prev_stars = prev_data[key].get("stars", 0)
        if prev_stars > 0 and stars > prev_stars:
            return round(stars - prev_stars, 1)

    # 方法 2: Trending 的 today_stars
    if today > 0:
        return float(today)

    # 方法 3: 回退公式 — sqrt 衰减, 对老项目更公平
    created = repo.get("created_at")
    if not created or stars == 0:
        return 0.0
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_days = max((NOW - dt).total_seconds() / 86400, 0.5)
        return round(stars / math.sqrt(age_days), 1)
    except (ValueError, TypeError):
        return 0.0


def hotness_score(repo: dict) -> float:
    """
    热度评分 (增长导向):
      - today_stars          * weight_today   (最直接的近期热度, 来自 Trending)
      - growth_rate          * weight_growth  (日均增速, 可来自历史对比)
      - recency_bonus        * weight_recency (push 时间越近越高)
      - log2(total_stars)    * weight_base    (基础影响力, 权重压低)
    """
    scoring = CFG.get("scoring", {})
    w_today = scoring.get("today_stars_weight", 0.40)
    w_growth = scoring.get("growth_rate_weight", 0.30)
    w_recency = scoring.get("recency_weight", 0.15)
    w_base = scoring.get("base_stars_weight", 0.15)

    today = repo.get("today_stars", 0)
    growth = repo.get("_growth_rate", 0.0)
    stars = repo.get("stargazers_count", 0)

    # recency: pushed 距今小时数 → 0~10 分
    recency = 0.0
    pa = repo.get("pushed_at")
    if pa:
        try:
            dt = datetime.fromisoformat(pa.replace("Z", "+00:00"))
            hours_ago = (NOW - dt).total_seconds() / 3600
            recency = max(0, 10 - hours_ago * 0.2)
        except (ValueError, TypeError):
            pass

    s = (
        math.log2(1 + today) * 3.0 * w_today
        + math.log2(1 + growth) * 2.0 * w_growth
        + recency * w_recency
        + math.log2(1 + stars) * w_base
    )
    return round(s, 2)


# ---------------------------------------------------------------------------
# 合并去重
# ---------------------------------------------------------------------------


def _merge(api_repos: list[dict], trending_repos: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for r in api_repos:
        r.setdefault("source", "api")
        seen[r.get("full_name", "").lower()] = r
    for r in trending_repos:
        key = r.get("full_name", "").lower()
        if key in seen:
            # 用 Trending 的 today_stars 补充 (仅当 > 0 时覆盖)
            ts = r.get("today_stars", 0)
            if ts > 0:
                seen[key]["today_stars"] = ts
            seen[key]["source"] = "both"
        else:
            seen[key] = r
    return list(seen.values())


# ---------------------------------------------------------------------------
# README 摘要抓取 (丰富简介)
# ---------------------------------------------------------------------------


def _extract_summary(md_text: str, max_len: int = 200) -> str:
    """从 README Markdown 中提取第一段有意义的文字作为简介."""
    lines = md_text.split("\n")
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        # 跳过空行、标题、徽章行、HTML 标签、图片、分割线
        if not stripped:
            if buf:
                break  # 遇到空行且已有内容, 段落结束
            continue
        if stripped.startswith(("#", "!", "<", "[!", "---", "***", "===")):
            if buf:
                break
            continue
        # 跳过纯链接/徽章行
        if _re.match(r"^\[!\[", stripped) or _re.match(r"^<(img|div|p|br|hr|table)", stripped, _re.I):
            if buf:
                break
            continue
        buf.append(stripped)
    text = " ".join(buf)
    # 清理 Markdown 格式
    text = _re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [text](url) → text
    text = _re.sub(r"[*_`~]", "", text)  # 去掉 bold/italic/code
    text = _re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def _fetch_readme_summary(full_name: str, token: Optional[str] = None) -> str:
    """通过 GitHub API 获取仓库 README 并提取摘要."""
    url = f"https://api.github.com/repos/{full_name}/readme"
    try:
        resp = requests.get(url, headers=_headers(token), timeout=10, verify=SSL_VERIFY)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return _extract_summary(content)
    except Exception:
        return ""


def enrich_descriptions(repos: list[dict], token: Optional[str] = None,
                        top_n: int = 30) -> None:
    """为排名靠前的仓库抓取 README 摘要, 丰富 description 字段."""
    api_cfg = CFG.get("api", {})
    interval = api_cfg.get("request_interval", 2)
    count = 0
    for r in repos[:top_n]:
        name = r.get("full_name", "")
        summary = _fetch_readme_summary(name, token)
        if summary and len(summary) > len(r.get("description") or ""):
            r["_readme_summary"] = summary
            count += 1
        time.sleep(interval * 0.5)  # 适度降速, 避免触发速率限制
    if count:
        console.print(f"    README 摘要: {count}/{min(len(repos), top_n)} 个仓库已丰富")


# ---------------------------------------------------------------------------
# 排名变化计算
# ---------------------------------------------------------------------------


def _compute_rank_changes(ranked: list[dict], prev_data: dict[str, dict],
                          section_key: str) -> list[dict]:
    """与昨日报告对比, 计算排名变化."""
    if not prev_data:
        return ranked

    # 从历史数据重建旧排名
    prev_ranks: dict[str, int] = {}
    # prev_data 只有 repo summary, 需要用 rank 字段
    for key, r in prev_data.items():
        if "rank" in r:
            prev_ranks[key] = r["rank"]

    for r in ranked:
        key = (r.get("full_name") or "").lower()
        if key in prev_ranks:
            old_rank = prev_ranks[key]
            new_rank = r.get("_rank", 0)
            r["_rank_change"] = old_rank - new_rank  # 正数=上升
        else:
            r["_rank_change"] = "new"

    return ranked


# ---------------------------------------------------------------------------
# 格式化 & 输出
# ---------------------------------------------------------------------------

def _fmt(n) -> str:
    n = int(n) if isinstance(n, float) else n
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _print_ranked(title: str, repos: list[dict], top_n: int) -> None:
    table = Table(title=title, title_style="bold cyan", show_lines=False, pad_edge=False)
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Repository", style="bold white", min_width=28, no_wrap=True)
    table.add_column("Lang", style="green", width=11)
    table.add_column("Stars", justify="right", style="yellow", width=7)
    table.add_column("+Today", justify="right", style="bold yellow", width=7)
    table.add_column("Growth/d", justify="right", style="bold magenta", width=9)
    table.add_column("Hot", justify="right", style="bold red", width=5)

    for i, r in enumerate(repos[:top_n], 1):
        today = r.get("today_stars", 0)
        growth = r.get("_growth_rate", 0)
        table.add_row(
            str(i), r.get("full_name", ""),
            (r.get("language", "") or "-")[:10],
            _fmt(r.get("stargazers_count", 0)),
            f"+{_fmt(today)}" if today else "-",
            f"{_fmt(growth)}/d" if growth else "-",
            str(r.get("_score", 0)),
        )
    console.print()
    console.print(table)

    console.print()
    for i, r in enumerate(repos[:top_n], 1):
        desc = (r.get("_readme_summary") or r.get("description") or "N/A")[:72]
        age = ""
        created = r.get("created_at")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                days = (NOW - dt).days
                if days < 7:
                    age = f"  [bold green][NEW {days}d][/]"
                elif days < 90:
                    age = f"  [green][{days}d old][/]"
            except (ValueError, TypeError):
                pass
        url = r.get("html_url") or f"https://github.com/{r.get('full_name', '')}"
        console.print(f"  [dim]{i:>2}.[/dim] {desc}{age}")
        console.print(f"      [blue underline]{url}[/blue underline]")


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def _repo_summary(r: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "full_name": r.get("full_name"),
        "description": r.get("_readme_summary") or r.get("description"),
        "language": r.get("language"),
        "stars": r.get("stargazers_count", 0),
        "forks": r.get("forks_count", 0),
        "issues": r.get("open_issues_count", 0),
        "today_stars": r.get("today_stars", 0),
        "growth_rate_per_day": r.get("_growth_rate", 0),
        "hotness_score": r.get("_score", 0),
        "created_at": r.get("created_at"),
        "topics": r.get("topics", []),
        "url": r.get("html_url") or f"https://github.com/{r.get('full_name', '')}",
        "rank_change": r.get("_rank_change"),
    }


def _report_dir(base: str = "reports") -> tuple[str, str]:
    """返回 (目录路径, 日期字符串), 自动创建 reports/YYYY-MM-DD/ 目录."""
    date_str = NOW.strftime("%Y-%m-%d")
    dir_path = os.path.join(base, date_str)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path, date_str


def save_report(core: list[dict], apps: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    core_n = CFG.get("rankings", {}).get("core_top_n", 10)
    app_n = CFG.get("rankings", {}).get("app_top_n", 20)
    report = {
        "generated_at": NOW.isoformat(),
        "methodology": "Ranked by hotness_score = today_stars({w1}) + growth_rate({w2}) + recency({w3}) + base_stars({w4})".format(
            w1=CFG.get("scoring", {}).get("today_stars_weight", 0.40),
            w2=CFG.get("scoring", {}).get("growth_rate_weight", 0.30),
            w3=CFG.get("scoring", {}).get("recency_weight", 0.15),
            w4=CFG.get("scoring", {}).get("base_stars_weight", 0.15),
        ),
        "ai_llm_core_top10": [_repo_summary(r, i+1) for i, r in enumerate(core[:core_n])],
        "ai_app_top20": [_repo_summary(r, i+1) for i, r in enumerate(apps[:app_n])],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    console.print(f"\n  [green]>>> JSON 报告已保存: {path}[/green]")


MD_STRINGS = {
    "zh": {
        "title": "GitHub AI 热门仓库报告",
        "timestamp": "数据时间",
        "window": "时间窗口: 过去 {hours} 小时",
        "formula": "评分公式",
        "scope": "采集范围: 核心 {core} / 应用 {app} (个人向)",
        "core_section": "AI/LLM 核心仓库 Top {n}",
        "app_section": "AI 个人应用 Top {n}",
        "header": "| # | 仓库 | 语言 | Stars | 今日增 | 日增速 | 热度 | 简介 |",
        "desc_note": "> *注: 「简介」列内容来自仓库作者原始描述，通常为英文。*",
        "footer": "*报告由 [GitHub AI Radar](https://github.com/JuliaYu907/github-ai-radar) 自动生成*",
    },
    "en": {
        "title": "GitHub AI Trending Report",
        "timestamp": "Generated at",
        "window": "Time window: last {hours} hours",
        "formula": "Scoring formula",
        "scope": "Scope: Core {core} / App {app} (personal use)",
        "core_section": "AI/LLM Core Top {n}",
        "app_section": "AI Personal Apps Top {n}",
        "header": "| # | Repo | Lang | Stars | +Today | Growth/d | Hot | Description |",
        "desc_note": "",
        "footer": "*Report generated by [GitHub AI Radar](https://github.com/JuliaYu907/github-ai-radar)*",
    },
}


def _build_md_lines(core: list[dict], apps: list[dict], lang: str,
                    core_count: int = 0, app_count: int = 0) -> list[str]:
    """构建 Markdown 报告内容行."""
    s = MD_STRINGS[lang]
    core_n = CFG.get("rankings", {}).get("core_top_n", 10)
    app_n = CFG.get("rankings", {}).get("app_top_n", 20)
    scoring = CFG.get("scoring", {})
    hours = CFG.get("time_window_hours", 48)
    lines: list[str] = []

    lines.append(f"# {s['title']}")
    lines.append("")
    lines.append(f"> {s['timestamp']}: {NOW.strftime('%Y-%m-%d %H:%M UTC')} | {s['window'].format(hours=hours)}")
    lines.append(">")
    lines.append(f"> {s['formula']}: `today_stars({scoring.get('today_stars_weight', 0.40)}) + growth_rate({scoring.get('growth_rate_weight', 0.30)}) + recency({scoring.get('recency_weight', 0.15)}) + base_stars({scoring.get('base_stars_weight', 0.15)})`")
    if core_count or app_count:
        lines.append(f"> {s['scope'].format(core=core_count, app=app_count)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    if s.get("desc_note"):
        lines.append(s["desc_note"])
        lines.append("")

    def _table(section_title: str, repos: list[dict], top_n: int) -> None:
        lines.append(f"## {section_title}")
        lines.append("")
        lines.append(s["header"])
        lines.append("|--:|------|------|------:|-------:|-------:|-----:|------|")
        for i, r in enumerate(repos[:top_n], 1):
            name = r.get("full_name", "")
            url = r.get("html_url") or f"https://github.com/{name}"
            rlang = (r.get("language") or "-")[:10]
            stars = _fmt(r.get("stargazers_count", 0))
            today = r.get("today_stars", 0)
            today_s = f"+{_fmt(today)}" if today else "-"
            growth = r.get("_growth_rate", 0)
            growth_s = f"{_fmt(growth)}/d" if growth else "-"
            score = r.get("_score", 0)
            desc = (r.get("_readme_summary") or r.get("description") or "")[:120]
            created = r.get("created_at")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if (NOW - dt).days < 7:
                        desc = f"**NEW** {desc}"
                except (ValueError, TypeError):
                    pass
            lines.append(f"| {i} | [{name}]({url}) | {rlang} | {stars} | {today_s} | {growth_s} | {score} | {desc} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    _table(s["core_section"].format(n=core_n), core, core_n)
    _table(s["app_section"].format(n=app_n), apps, app_n)

    lines.append(s["footer"])
    lines.append("")
    return lines


def save_md_report(core: list[dict], apps: list[dict], path_base: str,
                   core_count: int = 0, app_count: int = 0) -> None:
    """生成中英文双语 Markdown 报告."""
    os.makedirs(os.path.dirname(path_base) or ".", exist_ok=True)
    for lang, suffix in [("zh", "_zh.md"), ("en", "_en.md")]:
        lines = _build_md_lines(core, apps, lang, core_count, app_count)
        path = path_base + suffix
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        label = "中文" if lang == "zh" else "English"
        console.print(f"  [green]>>> MD  报告已保存 ({label}): {path}[/green]")


# ---------------------------------------------------------------------------
# GitHub Pages 生成
# ---------------------------------------------------------------------------

def generate_pages(core: list[dict], apps: list[dict], report_json_path: str) -> None:
    """将 HTML 模板复制到 docs/, 将报告数据写入 docs/data/latest.json."""
    output_cfg = CFG.get("output", {})
    pages_dir = Path(output_cfg.get("pages_dir", "docs"))
    template_path = Path(__file__).parent / "templates" / "index.html"

    if not template_path.exists():
        console.print(f"  [yellow]HTML 模板不存在: {template_path}, 跳过 Pages 生成[/yellow]")
        return

    # 创建目录结构
    data_dir = pages_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 复制模板到 docs/index.html
    shutil.copy2(template_path, pages_dir / "index.html")

    # 复制报告 JSON 到 docs/data/latest.json
    if os.path.exists(report_json_path):
        shutil.copy2(report_json_path, data_dir / "latest.json")

    # 生成 .nojekyll (GitHub Pages 需要)
    (pages_dir / ".nojekyll").touch()

    console.print(f"  [green]>>> Pages 已生成: {pages_dir}/[/green]")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    global SSL_VERIFY, NOW, CFG

    NOW = datetime.now(timezone.utc)

    parser = argparse.ArgumentParser(description="GitHub AI Radar — AI 热门仓库追踪器 (增长驱动)")
    parser.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub PAT (可选, 也可通过 GITHUB_TOKEN 环境变量设置)")
    parser.add_argument("--no-verify", action="store_true", help="跳过 SSL 证书验证")
    parser.add_argument("--output", type=str, default=None,
                        help="输出报告基础路径 (不含扩展名); 默认 reports/YYYY-MM-DD/github_hot_repo_YYYY-MM-DD")
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径 (默认 config.yaml)")
    args = parser.parse_args()

    # 加载配置
    CFG = load_config(args.config)

    # 确定报告输出路径
    reports_dir = CFG.get("output", {}).get("reports_dir", "reports")
    if args.output:
        report_base = args.output.rsplit(".", 1)[0]
    else:
        dir_path, date_str = _report_dir(reports_dir)
        report_base = os.path.join(dir_path, f"github_hot_repo_{date_str}")

    if args.no_verify:
        SSL_VERIFY = False
        console.print("[yellow]>>> SSL 证书验证已禁用[/yellow]")

    output_formats = set(CFG.get("output", {}).get("formats", ["json", "markdown", "html"]))

    # 1. 抓取
    console.print("[cyan]>>> [1/6] Search API: AI topic + 新项目爆发查询...[/cyan]")
    api_repos = fetch_ai_repos(token=args.token)
    console.print(f"    API 共获取 {len(api_repos)} 个去重仓库")

    console.print("[cyan]>>> [2/6] GitHub Trending (today_stars)...[/cyan]")
    trending = fetch_trending()
    console.print(f"    Trending 返回 {len(trending)} 条")

    # 2. 加载历史数据
    console.print("[cyan]>>> [3/6] 加载历史数据 & 计算增长速率...[/cyan]")
    prev_data = _load_previous_report()

    # 3. 合并 & 计算增长指标
    all_repos = _merge(api_repos, trending)
    for r in all_repos:
        r["_growth_rate"] = _compute_growth_rate(r, prev_data)
        r["_score"] = hotness_score(r)

    # 4. 分类
    console.print("[cyan]>>> [4/6] 分类 & 排序...[/cyan]")
    kw = _get_sets("classification")
    core_list: list[dict] = []
    app_list: list[dict] = []
    for r in all_repos:
        is_core, is_app = _classify(r, kw)
        if is_core:
            core_list.append(r)
        if is_app:
            app_list.append(r)

    # 应用榜: 过滤掉企业级项目, 只保留个人使用向
    app_list = [r for r in app_list if _is_personal_use(r, kw)]

    core_list.sort(key=lambda x: x["_score"], reverse=True)
    app_list.sort(key=lambda x: x["_score"], reverse=True)

    # 去重: 核心榜出现过的仓库不再出现在应用榜
    if CFG.get("rankings", {}).get("deduplicate", True):
        core_n = CFG.get("rankings", {}).get("core_top_n", 10)
        core_names = {r.get("full_name", "").lower() for r in core_list[:core_n]}
        app_list = [r for r in app_list if r.get("full_name", "").lower() not in core_names]

    # 添加排名信息
    for i, r in enumerate(core_list):
        r["_rank"] = i + 1
    for i, r in enumerate(app_list):
        r["_rank"] = i + 1

    console.print(f"    分类完成: 核心 {len(core_list)} / 应用 {len(app_list)} (个人向, 已去重)")

    if not core_list and not app_list:
        console.print("[red]未获取到任何 AI 仓库数据。[/red]")
        sys.exit(1)

    # 5. 抓取 README 摘要 (丰富简介)
    console.print("[cyan]>>> [5/6] 抓取 README 摘要...[/cyan]")
    core_n = CFG.get("rankings", {}).get("core_top_n", 10)
    app_n = CFG.get("rankings", {}).get("app_top_n", 20)
    enrich_descriptions(core_list, token=args.token, top_n=core_n)
    enrich_descriptions(app_list, token=args.token, top_n=app_n)

    # 6. 输出
    console.print("[cyan]>>> [6/6] 生成报告...[/cyan]")

    _print_ranked(f"AI/LLM Core — Top {core_n} (Hottest)", core_list, core_n)
    console.print()
    _print_ranked(f"AI Apps for Personal Use — Top {app_n} (Hottest)", app_list, app_n)

    report_json = f"{report_base}.json"
    if "json" in output_formats:
        save_report(core_list, app_list, report_json)
    if "markdown" in output_formats:
        save_md_report(core_list, app_list, report_base,
                       core_count=len(core_list), app_count=len(app_list))
    if "html" in output_formats:
        generate_pages(core_list, app_list, report_json)

    console.print(f"\n  [dim]时间窗口: 过去 {CFG.get('time_window_hours', 48)} 小时 | 数据时间: {NOW.strftime('%Y-%m-%d %H:%M UTC')}[/dim]")
    rate = "未认证 (10 req/min)" if not args.token else "已认证 (30 req/min)"
    console.print(f"  [dim]API 速率: {rate}[/dim]")
    scoring = CFG.get("scoring", {})
    console.print(f"  [dim]评分公式: today_stars({scoring.get('today_stars_weight', 0.40)}) + growth_rate({scoring.get('growth_rate_weight', 0.30)}) + recency({scoring.get('recency_weight', 0.15)}) + base_stars({scoring.get('base_stars_weight', 0.15)})[/dim]\n")


if __name__ == "__main__":
    main()
