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
        cfg = _deep_merge(DEFAULTS, user_cfg)
    else:
        console.print(f"  [dim]未找到配置文件, 使用内置默认值[/dim]")
        cfg = DEFAULTS.copy()
    # CONFIG-14: 校验评分权重之和
    scoring = cfg.get("scoring", {})
    total = sum(scoring.get(k, 0) for k in
                ("today_stars_weight", "growth_rate_weight", "recency_weight", "base_stars_weight"))
    if abs(total - 1.0) > 0.01:
        console.print(f"  [yellow]警告: 评分权重之和 = {total:.2f} (应为 1.0), 结果可能不准确[/yellow]")
    return cfg


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
    """加载前一天的 JSON 报告, 返回 {section:full_name_lower: repo_summary}."""
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
        # ISSUE-10: 兼容新旧两种文件名格式
        json_files = list(d.glob("*.json"))
        for jf in json_files:
            if "details" in jf.name:
                continue
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                prev: dict[str, dict] = {}
                for section in ("ai_llm_core_top10", "ai_app_top20"):
                    for idx, r in enumerate(data.get(section, []), 1):
                        fn = (r.get("full_name") or "").lower()
                        if not fn:
                            continue
                        # ISSUE-10: 旧报告可能没有 rank 字段, 从列表位置重建
                        if "rank" not in r:
                            r["rank"] = idx
                        # BUG-2: 使用 section 前缀区分 core/app 排名
                        prev[f"{section}:{fn}"] = r
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
      3. 回退到 total_stars / age_days (线性日均, 不再用 sqrt 以避免失真)
    """
    stars = repo.get("stargazers_count", 0)
    key = (repo.get("full_name") or "").lower()
    today = repo.get("today_stars", 0)

    # 方法 1: 历史对比 (尝试两个 section 的前缀)
    for section in ("ai_llm_core_top10", "ai_app_top20"):
        lookup = f"{section}:{key}"
        if lookup in prev_data:
            prev_stars = prev_data[lookup].get("stars", 0)
            if prev_stars > 0 and stars > prev_stars:
                return round(stars - prev_stars, 1)
            break

    # 方法 2: Trending 的 today_stars
    if today > 0:
        return float(today)

    # 方法 3: 回退公式 — 线性日均 stars, 避免 sqrt 导致的数值失真
    created = repo.get("created_at")
    if not created or stars == 0:
        return 0.0
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_days = max((NOW - dt).total_seconds() / 86400, 0.5)
        return round(stars / age_days, 1)
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


def _fetch_repo_metadata(full_name: str, token: Optional[str] = None) -> Optional[dict]:
    """通过 GitHub API 获取仓库完整元数据."""
    url = f"https://api.github.com/repos/{full_name}"
    try:
        resp = requests.get(url, headers=_headers(token), timeout=10, verify=SSL_VERIFY)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


def _enrich_trending_metadata(repos: list[dict], token: Optional[str] = None) -> None:
    """BUG-3: 为仅来自 Trending 的仓库补充完整元数据 (created_at, topics, pushed_at 等)."""
    api_cfg = CFG.get("api", {})
    interval = api_cfg.get("request_interval", 2)
    count = 0
    for r in repos:
        if r.get("source") != "trending":
            continue
        # 已有完整元数据则跳过
        if r.get("created_at") and r.get("topics"):
            continue
        name = r.get("full_name", "")
        meta = _fetch_repo_metadata(name, token)
        if meta:
            for key in ("created_at", "pushed_at", "topics", "open_issues_count",
                        "forks_count", "stargazers_count", "language", "html_url",
                        "description"):
                if meta.get(key) is not None and not r.get(key):
                    r[key] = meta[key]
            # 保留 trending 的 today_stars
            r["source"] = "trending"
            count += 1
        time.sleep(interval * 0.5)
    if count:
        console.print(f"    补充 Trending 仓库元数据: {count} 个")


# ---------------------------------------------------------------------------
# README 摘要抓取 (丰富简介)
# ---------------------------------------------------------------------------


def _is_junk_line(line: str) -> bool:
    """判断一行是否为无意义的导航/徽章/链接/翻译列表等, 应跳过."""
    s = line.strip()
    if not s:
        return True
    # 标题、图片、HTML 标签、分割线
    if s.startswith(("#", "!", "<", "[!", "---", "***", "===")):
        return True
    # 徽章/HTML 元素行 (含内嵌 HTML 标签)
    if _re.match(r"^\[!\[", s) or _re.search(
            r"<(img|div|p|br|hr|table|a\s|!--|svg|video|source|picture|iframe)\b", s, _re.I):
        return True
    # BUG-5: 含 src= 属性的行 (HTML 残留, 如 img 标签)
    if _re.search(r'\bsrc\s*=\s*["\']', s, _re.I) and len(s) < 500:
        return True
    # BUG-5: 代码行 — import/from/require/include 语句
    if _re.match(r"^(import |from \S+ import |require\(|#include|using |package )", s):
        return True
    # BUG-5: 代码块标记
    if s.startswith("```"):
        return True
    # 语言/翻译链接列表: "Arabic | Bengali | Chinese ..." 或带 Markdown 链接
    if s.count("|") >= 3 and _re.search(r"[A-Z][a-z]+\s*\|", s):
        return True
    # 导航行: "Features · Get Started · Explore" 或 "Docs | API | Demo"
    if s.count("·") >= 2 or (s.count("|") >= 2 and len(s) < 200
                              and _re.search(r"\[.+?\]\(.+?\)", s)):
        return True
    # 纯链接行 (整行都是 Markdown 链接, 无实质内容)
    cleaned = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    cleaned = _re.sub(r"[*_`~\[\]()|\s·•–—]", "", cleaned)
    if len(cleaned) < 5 and len(s) > 10:
        return True
    # 纯 emoji / 徽标行
    if _re.match(r"^[\s\W]*$", cleaned) and len(s) > 5:
        return True
    # 项目元信息行 (License, Version, Build Status 等)
    if _re.match(r"^(license|version|build|status|downloads?|coverage|stars?)\s*[:：]", s, _re.I):
        return True
    return False


def _clean_md_text(text: str) -> str:
    """清理 Markdown 格式, 提取纯文本."""
    text = _re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # [text](url) → text
    text = _re.sub(r"<[^>]+>", "", text)                      # 去掉 HTML 标签
    text = _re.sub(r"[*_`~]", "", text)                       # 去掉 bold/italic/code
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def _extract_summary(md_text: str, max_len: int = 300,
                     repo_name: str = "") -> str:
    """从 README Markdown 中智能提取项目描述.

    策略 (按优先级):
      1. 找 "{项目名} is a/an ..." 的定义句
      2. 找描述性标题 (About/Overview/Introduction/Description) 后的段落
      3. 找包含描述性关键词 (framework/tool/platform/library...) 的段落
      4. 回退到第一段 >= 30 字符的有意义段落
    """
    lines = md_text.split("\n")

    # --- 第 1 步: 收集所有候选段落, 并记录每段前面的标题 ---
    paragraphs: list[dict] = []  # [{"text": str, "heading": str, "index": int}]
    buf: list[str] = []
    last_heading = ""

    def _flush(idx: int):
        if not buf:
            return
        raw = " ".join(buf)
        cleaned = _clean_md_text(raw)
        if len(cleaned) >= 20:
            paragraphs.append({"text": cleaned, "heading": last_heading, "index": idx})
        buf.clear()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            _flush(i)
            if len(paragraphs) >= 10:
                break
            continue
        if stripped.startswith("#"):
            _flush(i)
            last_heading = _re.sub(r"^#+\s*", "", stripped).strip().lower()
            continue
        if _is_junk_line(stripped):
            _flush(i)
            continue
        buf.append(stripped)

    _flush(len(lines))

    if not paragraphs:
        return ""

    # --- 第 2 步: 为每个候选段落打分 ---
    # 提取短项目名用于匹配 (e.g. "tensorflow/tensorflow" → "tensorflow")
    short_name = repo_name.split("/")[-1].lower().replace("-", " ") if repo_name else ""

    # 描述性标题关键词
    _DESC_HEADINGS = {"about", "overview", "introduction", "description",
                      "what is", "summary", "getting started", "简介", "概述", "介绍"}
    # 定义句式模式
    _DEF_PATTERN = _re.compile(
        r"\b(is an?|are|provides?|enables?|offers?|allows?|helps?)\b", _re.I)
    # 描述性名词关键词
    _DESC_KEYWORDS = _re.compile(
        r"\b(framework|library|toolkit|platform|engine|tool|system|suite|sdk|"
        r"application|app|interface|model|agent|assistant|server|client|runtime|"
        r"solution|service|infrastructure|database|manager|builder|generator|"
        r"compiler|editor|browser|dashboard|monitor|pipeline|gateway|proxy|"
        r"extension|plugin|wrapper|cli|api|gui|ui|ide)\b", _re.I)

    best_score = -1
    best_text = ""

    for p in paragraphs:
        text = p["text"]
        heading = p["heading"]
        score = 0

        # 名称匹配: 段落包含项目名 (强信号)
        if short_name and len(short_name) > 2 and short_name in text.lower():
            score += 30

        # 定义句式: "is a/an", "provides", "enables" (强信号)
        if _DEF_PATTERN.search(text):
            score += 25

        # 描述性标题下: About / Overview / Introduction 等
        if any(kw in heading for kw in _DESC_HEADINGS):
            score += 20

        # 包含描述性名词关键词
        if _DESC_KEYWORDS.search(text):
            score += 10

        # 段落位置: 靠前的段落略有优势
        score -= p["index"] * 0.1

        # 长度适中 (30-200 最佳)
        tlen = len(text)
        if 30 <= tlen <= 200:
            score += 5
        elif tlen < 30:
            score -= 10

        # 排除明显非描述段落
        lower = text.lower()
        if lower.startswith(("install", "pip ", "npm ", "cargo ", "brew ", "docker ",
                             "usage", "prerequisit", "require", "import ", "from ",
                             "mkdir ", "cd ", "git clone", "curl ", "wget ")):
            score -= 50
        # 列表项开头
        if text.startswith(("- ", "* ", "1. ", "1) ")):
            score -= 30

        # BUG-4: 段落以其他项目名开头的 "X is a..." 定义句 → 可能是错误内容
        if _DEF_PATTERN.search(text) and short_name:
            m = _re.match(r"^(.{3,50}?)\s+(is an?|are|provides?)\b", text, _re.I)
            if m:
                subject = m.group(1).lower().strip().replace("-", " ")
                name_parts = [p for p in short_name.split() if len(p) > 2]
                if name_parts and not any(p in subject for p in name_parts):
                    score -= 40

        if score > best_score:
            best_score = score
            best_text = text

    if not best_text:
        best_text = paragraphs[0]["text"]

    if len(best_text) > max_len:
        best_text = best_text[:max_len].rsplit(" ", 1)[0] + "..."
    return best_text


def _fetch_readme_raw(full_name: str, token: Optional[str] = None,
                      max_chars: int = 3000) -> str:
    """通过 GitHub API 获取仓库 README 原始内容 (截断到 max_chars)."""
    url = f"https://api.github.com/repos/{full_name}/readme"
    try:
        resp = requests.get(url, headers=_headers(token), timeout=10, verify=SSL_VERIFY)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return content[:max_chars]
    except Exception:
        return ""


def _fetch_readme_summary(full_name: str, token: Optional[str] = None) -> str:
    """通过 GitHub API 获取仓库 README 并提取摘要 (回退方案, 不走 LLM)."""
    raw = _fetch_readme_raw(full_name, token)
    return _extract_summary(raw, repo_name=full_name) if raw else ""


# ---------------------------------------------------------------------------
# 模板拼接法: README 摘录 + 元数据分析 (无需 LLM)
# ---------------------------------------------------------------------------

# 已知组织 -> 中文显示名
_KNOWN_ORGS: dict[str, str] = {
    "google": "Google", "tensorflow": "Google", "pytorch": "Meta",
    "meta": "Meta", "facebook": "Meta", "facebookresearch": "Meta Research",
    "microsoft": "微软", "azure": "微软", "openai": "OpenAI",
    "huggingface": "Hugging Face", "alibaba": "阿里巴巴", "ant-design": "蚂蚁",
    "tencent": "腾讯", "baidu": "百度", "bytedance": "字节跳动",
    "apple": "Apple", "aws": "AWS", "amazon": "Amazon",
    "nvidia": "NVIDIA", "intel": "Intel", "ibm": "IBM",
    "deepmind": "DeepMind", "anthropic": "Anthropic",
    "ray-project": "Anyscale", "langchain-ai": "LangChain",
    "langgenius": "Dify 团队", "lobehub": "LobeHub 团队",
    "infiniflow": "InfiniFlow", "comfy-org": "ComfyUI 团队",
    "significant-gravitas": "Significant Gravitas",
}

# 主题 -> 中文领域标签 (用于自动归类)
_TOPIC_LABELS: dict[str, str] = {
    "machine-learning": "机器学习", "deep-learning": "深度学习",
    "llm": "大语言模型", "llms": "大语言模型",
    "large-language-model": "大语言模型",
    "transformer": "Transformer", "transformers": "Transformer",
    "nlp": "自然语言处理", "natural-language-processing": "自然语言处理",
    "computer-vision": "计算机视觉", "cv": "计算机视觉",
    "speech-recognition": "语音识别",
    "reinforcement-learning": "强化学习",
    "generative-ai": "生成式 AI", "genai": "生成式 AI",
    "diffusion": "扩散模型", "stable-diffusion": "Stable Diffusion",
    "text-to-image": "文生图",
    "agent": "AI Agent", "ai-agent": "AI Agent",
    "agentic-ai": "Agentic AI", "agentic-workflow": "Agent 工作流",
    "rag": "RAG 检索增强", "retrieval-augmented-generation": "RAG",
    "chatbot": "聊天机器人", "chat": "对话",
    "mcp": "MCP 协议", "function-calling": "函数调用",
    "copilot": "AI 编程助手", "ai-coding": "AI 编程",
    "embedding": "向量嵌入", "vector-database": "向量数据库",
    "inference": "推理引擎", "model-serving": "模型服务",
    "fine-tuning": "微调", "lora": "LoRA 微调",
    "quantization": "量化", "rlhf": "RLHF",
    "multimodal": "多模态", "vlm": "视觉语言模型",
    "automation": "自动化", "workflow": "工作流",
    "low-code": "低代码", "no-code": "无代码",
    "self-hosted": "自托管", "local-llm": "本地大模型",
    "ollama": "Ollama 生态",
}

# 知名模型/产品名 (在 topics 中出现时可提及)
_MODEL_NAMES: set[str] = {
    "chatgpt", "gpt", "gpt-4", "gpt-4o", "claude", "gemini", "gemma",
    "deepseek", "qwen", "llama", "mistral", "phi",
    "stable-diffusion", "flux", "dall-e",
}


def _first_sentence(text: str, max_len: int = 160) -> str:
    """提取第一句话, 在句号处截断."""
    if not text:
        return ""
    # 判断是否主要是英文
    ascii_ratio = sum(1 for c in text if c.isascii()) / max(len(text), 1)
    is_english = ascii_ratio > 0.7
    # 尝试在句号处截断 (含句末无空格的情况)
    seps = [". ", "! ", "? "] if is_english else ["。", ". ", "! ", "！"]
    for sep in seps:
        idx = text.find(sep)
        if 15 < idx < max_len:
            return text[:idx + len(sep)].strip()
    # 检查句号恰好在文末
    if len(text) <= max_len and text.rstrip().endswith((".", "。", "!", "？", "?", "！")):
        return text.strip()
    # 没有句号 → 在 max_len 处按词截断
    if len(text) > max_len:
        cut = text[:max_len].rsplit(" ", 1)[0] if is_english else text[:max_len]
        cut = cut.rstrip("，,;；、")
        return cut + ("..." if is_english else "。")
    # 短文本原样返回, 补句号
    tail = text.rstrip("，,;；、")
    if is_english:
        return tail if tail.endswith((".", "!", "?")) else tail + "."
    return tail if tail.endswith(("。", ".", "!", "！", "?", "？")) else tail + "。"


def _template_summarize(r: dict, readme_extract: str) -> str:
    """基于模板 + 元数据生成分析性总结 (无需 LLM).

    结构: [组织归属 +] 核心描述(来自README) + 技术/领域标签 + 数据洞察(stars/forks/age)
    """
    name = r.get("full_name", "")
    owner = name.split("/")[0].lower() if "/" in name else ""
    desc_raw = readme_extract or r.get("description") or ""
    lang = r.get("language") or ""
    stars = r.get("stargazers_count", 0)
    forks = r.get("forks_count", 0)
    issues = r.get("open_issues_count", 0)
    topics = r.get("topics", [])
    today = r.get("today_stars", 0)
    growth = r.get("_growth_rate", 0)
    created = r.get("created_at", "")

    parts: list[str] = []

    # === 第 1 句: [组织] + 核心定位 ===
    org = _KNOWN_ORGS.get(owner, "")
    core_desc = _first_sentence(desc_raw)

    if org and core_desc:
        # 避免重复: 如果描述已包含组织名则不再前缀
        if org.lower() in core_desc.lower():
            parts.append(core_desc)
        else:
            parts.append(f"{org} 开源的 {core_desc}")
    elif core_desc:
        parts.append(core_desc)

    # === 第 2 句: 技术 / 领域标签 ===
    # 从 topics 中提取有意义的领域标签 (最多 3 个)
    domain_tags: list[str] = []
    model_tags: list[str] = []
    for t in topics:
        tl = t.lower()
        if tl in _TOPIC_LABELS and _TOPIC_LABELS[tl] not in domain_tags:
            domain_tags.append(_TOPIC_LABELS[tl])
        if tl in _MODEL_NAMES:
            model_tags.append(t.capitalize())
    domain_tags = domain_tags[:3]
    model_tags = model_tags[:4]

    tech_parts: list[str] = []
    if domain_tags:
        tech_parts.append("涵盖" + " / ".join(domain_tags) + "等领域")
    if model_tags:
        tech_parts.append("支持 " + " / ".join(model_tags) + " 等模型")

    if tech_parts:
        parts.append("，".join(tech_parts) + "。")

    # === 第 3 句: 数据洞察 (选择最有信息量的 1-2 个事实) ===
    insights: list[str] = []

    # Forks 洞察
    if forks >= 20_000:
        insights.append(f"{_fmt(forks)} forks 表明大量团队基于此项目进行二次开发")
    elif stars > 0 and forks / max(stars, 1) > 0.3:
        insights.append(f"fork 率超过 {forks/stars*100:.0f}%，二次开发需求旺盛")

    # Issues 洞察
    if issues >= 5_000:
        insights.append(f"{_fmt(issues)} open issues 反映了极其活跃的社区需求")

    # 今日 Stars
    if today >= 500:
        insights.append("今日热度爆发，关注度飙升")
    elif today >= 100:
        insights.append("近期关注度持续走高")

    # 年龄 + 增长
    if created:
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (NOW - dt).days
            year = dt.year
            if age_days <= 7:
                insights.append(f"创建仅 {age_days} 天的全新项目，增速惊人")
            elif age_days <= 30:
                insights.append("创建不到一个月即快速崛起，值得关注")
            elif age_days <= 180 and stars >= 5_000:
                insights.append(f"创建于 {year} 年，半年内即快速崛起")
            elif age_days > 365 * 3:
                yrs = age_days // 365
                insights.append(f"创建于 {year} 年，持续维护 {yrs} 年")
        except (ValueError, TypeError):
            pass

    # 取最有信息量的 2 条
    if insights:
        parts.append("。".join(insights[:2]) + "。")

    result = " ".join(parts)
    # 清理多余标点
    result = _re.sub(r"。。", "。", result)
    result = _re.sub(r"\.。", "。", result)
    result = _re.sub(r"\s+", " ", result).strip()
    return result


# ---------------------------------------------------------------------------
# LLM 分析性总结
# ---------------------------------------------------------------------------

def _get_llm_client():
    """创建 OpenAI 兼容的 LLM 客户端. 返回 (client, model) 或 (None, None)."""
    llm_cfg = CFG.get("llm", {})
    if not llm_cfg.get("enabled", False):
        return None, None
    try:
        from openai import OpenAI
    except ImportError:
        console.print("  [yellow]openai 库未安装, 跳过 LLM 总结 (pip install openai)[/yellow]")
        return None, None

    api_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY") or ""
    api_base = llm_cfg.get("api_base") or os.environ.get("LLM_API_BASE") or ""
    model = llm_cfg.get("model") or os.environ.get("LLM_MODEL") or "gpt-4o-mini"

    if not api_key:
        console.print("  [yellow]未设置 LLM_API_KEY, 跳过 LLM 总结[/yellow]")
        return None, None

    kwargs: dict[str, Any] = {"api_key": api_key}
    if api_base:
        kwargs["base_url"] = api_base
    return OpenAI(**kwargs), model


def _build_repo_context(r: dict, readme_text: str) -> str:
    """为单个仓库构建 LLM 输入上下文."""
    name = r.get("full_name", "")
    desc = r.get("description") or ""
    lang = r.get("language") or "N/A"
    stars = r.get("stargazers_count", 0)
    forks = r.get("forks_count", 0)
    issues = r.get("open_issues_count", 0)
    topics = ", ".join(r.get("topics", []))
    today = r.get("today_stars", 0)
    growth = r.get("_growth_rate", 0)
    score = r.get("_score", 0)
    created = r.get("created_at", "")
    readme_snippet = readme_text.strip()[:2000] if readme_text else "(无 README)"

    return (
        f"仓库: {name}\n"
        f"GitHub 简介: {desc}\n"
        f"语言: {lang} | Stars: {stars} | Forks: {forks} | Issues: {issues}\n"
        f"Topics: {topics}\n"
        f"今日 Stars: +{today} | 日增速: {growth:.1f} | 热度分: {score}\n"
        f"创建时间: {created}\n"
        f"README 节选:\n{readme_snippet}"
    )


def _llm_summarize_batch(repos: list[dict], readmes: dict[str, str],
                          client, model: str) -> dict[str, str]:
    """调用 LLM 批量生成分析性总结. 返回 {full_name: summary}."""
    llm_cfg = CFG.get("llm", {})
    temperature = llm_cfg.get("temperature", 0.3)
    max_chars = llm_cfg.get("max_summary_chars", 200)
    batch_size = llm_cfg.get("batch_size", 10)
    results: dict[str, str] = {}

    for start in range(0, len(repos), batch_size):
        batch = repos[start:start + batch_size]
        repo_blocks = []
        for idx, r in enumerate(batch, 1):
            name = r.get("full_name", "")
            readme = readmes.get(name, "")
            ctx = _build_repo_context(r, readme)
            repo_blocks.append(f"--- 仓库 {idx}: ---\n{ctx}")

        prompt = (
            "你是一位 GitHub AI 仓库分析师。请为以下每个仓库撰写一段简洁的中文分析性总结。\n\n"
            "要求:\n"
            f"- 每个总结控制在 {max_chars} 字以内, 1-2 句话\n"
            "- 不要照搬 README 或 GitHub 简介的原话, 要用自己的语言概括\n"
            "- 结合 Stars/Forks/Topics/语言/创建时间等元数据进行分析\n"
            "- 指出项目的核心定位、技术特色、行业影响力\n"
            "- 如果是新项目(创建不久但增长快), 要特别指出\n"
            "- 风格参考: 「Google 的开源机器学习框架，深度学习领域的行业标杆。C++ 为核心、Python 为接口，"
            "涵盖分布式训练、推理部署全链路。75k forks 居全榜最高，反映其作为基础设施级项目被广泛二次开发。」\n\n"
            "输出格式 (严格遵守, 每行一个仓库):\n"
            "1. <总结内容>\n"
            "2. <总结内容>\n"
            "...\n\n"
        )
        prompt += "\n\n".join(repo_blocks)

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=batch_size * 300,
            )
            reply = resp.choices[0].message.content or ""
            # 解析编号输出: "1. xxx\n2. xxx\n..."
            for line in reply.split("\n"):
                line = line.strip()
                m = _re.match(r"^(\d+)\.\s*(.+)", line)
                if m:
                    idx = int(m.group(1)) - 1
                    summary = m.group(2).strip()
                    if 0 <= idx < len(batch):
                        name = batch[idx].get("full_name", "")
                        results[name] = summary
        except Exception as e:
            console.print(f"  [yellow]LLM 批量总结失败: {e}[/yellow]")

        if start + batch_size < len(repos):
            time.sleep(1)

    return results


def enrich_descriptions(repos: list[dict], token: Optional[str] = None,
                        top_n: int = 30) -> None:
    """为排名靠前的仓库丰富描述.

    优先级: LLM 分析性总结 > 模板拼接法 > README 摘录
    """
    api_cfg = CFG.get("api", {})
    interval = api_cfg.get("request_interval", 2)
    llm_cfg = CFG.get("llm", {})
    max_readme = llm_cfg.get("max_readme_chars", 3000)
    targets = repos[:top_n]

    # 1. 抓取 README 原始内容
    readmes: dict[str, str] = {}
    for r in targets:
        name = r.get("full_name", "")
        raw = _fetch_readme_raw(name, token, max_chars=max_readme)
        if raw:
            readmes[name] = raw
        time.sleep(interval * 0.5)
    console.print(f"    README 抓取: {len(readmes)}/{len(targets)} 个仓库")

    # 2. 为所有仓库提取 README 摘录 (后续步骤会用到)
    extracts: dict[str, str] = {}
    for r in targets:
        name = r.get("full_name", "")
        raw = readmes.get(name, "")
        if raw:
            ext = _extract_summary(raw, repo_name=name)
            if ext:
                extracts[name] = ext

    # 3. 尝试 LLM 分析性总结
    client, model = _get_llm_client()
    llm_count = 0
    if client:
        console.print(f"    LLM 总结中 (model={model})...")
        summaries = _llm_summarize_batch(targets, readmes, client, model)
        for r in targets:
            name = r.get("full_name", "")
            if name in summaries and summaries[name]:
                r["_summary"] = summaries[name]
                llm_count += 1
        console.print(f"    LLM 总结: {llm_count}/{len(targets)} 个仓库")

    # 4. 模板拼接法: 用 README 摘录 + 元数据生成分析性总结
    tpl_count = 0
    for r in targets:
        if r.get("_summary"):
            continue
        name = r.get("full_name", "")
        readme_ext = extracts.get(name, "")
        summary = _template_summarize(r, readme_ext)
        if summary and len(summary) > 20:
            r["_summary"] = summary
            tpl_count += 1
    if tpl_count:
        console.print(f"    模板总结: {tpl_count}/{len(targets)} 个仓库")

    # 5. 最终回退: 用 README 摘录替换过短的 description
    fallback_count = 0
    for r in targets:
        if r.get("_summary"):
            continue
        name = r.get("full_name", "")
        ext = extracts.get(name, "")
        if ext and len(ext) > len(r.get("description") or ""):
            r["_readme_summary"] = ext
            fallback_count += 1
    if fallback_count:
        console.print(f"    README 摘录回退: {fallback_count} 个仓库")


# ---------------------------------------------------------------------------
# 排名变化计算
# ---------------------------------------------------------------------------


def _compute_rank_changes(ranked: list[dict], prev_data: dict[str, dict],
                          section_key: str) -> None:
    """与昨日报告对比, 计算排名变化."""
    if not prev_data:
        return

    for r in ranked:
        key = (r.get("full_name") or "").lower()
        # BUG-2: 使用 section_key 前缀查找, 避免 core/app 排名冲突
        lookup = f"{section_key}:{key}"
        if lookup in prev_data:
            old_rank = prev_data[lookup].get("rank", 0)
            new_rank = r.get("_rank", 0)
            r["_rank_change"] = old_rank - new_rank  # 正数=上升
        else:
            r["_rank_change"] = "new"


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
        desc = (r.get("_summary") or r.get("_readme_summary") or r.get("description") or "N/A")[:72]
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
    summary: dict[str, Any] = {
        "rank": rank,
        "full_name": r.get("full_name"),
        "description": r.get("_readme_summary") or r.get("description"),
        "summary": r.get("_summary") or "",
        "language": r.get("language"),
        "stars": r.get("stargazers_count", 0),
        "forks": r.get("forks_count", 0),
        "issues": r.get("open_issues_count", 0),
        "today_stars": r.get("today_stars", 0),
        "growth_score": r.get("_growth_rate", 0),
        "hotness_score": r.get("_score", 0),
        "created_at": r.get("created_at"),
        "topics": r.get("topics", []),
        "url": r.get("html_url") or f"https://github.com/{r.get('full_name', '')}",
        "rank_change": r.get("_rank_change"),
    }
    return summary


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
        "title": "GitHub AI 仓库趋势报告",
        "timestamp": "数据时间",
        "window": "时间窗口: 过去 {hours} 小时",
        "formula": "评分公式",
        "scope": "采集范围: 核心 {core} / 应用 {app} (个人向)",
        "core_section": "AI/LLM 核心仓库 Top {n}",
        "app_section": "AI 个人应用 Top {n}",
        "header": "| # | 仓库 | 语言 | Stars | 今日增 | 日增速 | 热度 | 总结 |",
        "separator": "|--:|------|------|------:|------:|------:|-----:|------|",
        "desc_note": "",
        "footer": "*报告由 [GitHub AI Radar](https://github.com/JuliaYu907/github-ai-radar) 自动生成*",
        "insights_title": "趋势洞察",
    },
    "en": {
        "title": "GitHub AI Repo Trending Report",
        "timestamp": "Generated at",
        "window": "Time window: last {hours} hours",
        "formula": "Scoring formula",
        "scope": "Scope: Core {core} / App {app} (personal use)",
        "core_section": "AI/LLM Core Top {n}",
        "app_section": "AI Personal Apps Top {n}",
        "header": "| # | Repo | Lang | Stars | +Today | Growth | Hot | Summary |",
        "separator": "|--:|------|------|------:|------:|------:|-----:|---------|",
        "desc_note": "",
        "footer": "*Report generated by [GitHub AI Radar](https://github.com/JuliaYu907/github-ai-radar)*",
        "insights_title": "Trend Insights",
    },
}


def _generate_trend_insights(core: list[dict], apps: list[dict], lang: str) -> list[str]:
    """MISSING-7: 自动生成趋势洞察章节."""
    all_repos = list(core) + list(apps)
    if not all_repos:
        return []
    s = MD_STRINGS[lang]
    lines: list[str] = []
    lines.append(f"## {s['insights_title']}")
    lines.append("")

    insight_num = 1

    # 1. 语言分布
    lang_counts: dict[str, int] = {}
    for r in all_repos:
        rl = r.get("language") or "Other"
        lang_counts[rl] = lang_counts.get(rl, 0) + 1
    top_langs = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    if top_langs:
        if lang == "zh":
            lang_str = "、".join(f"{l}({c})" for l, c in top_langs)
            lines.append(f"{insight_num}. **语言分布**: 上榜项目语言前五: {lang_str}")
        else:
            lang_str = ", ".join(f"{l}({c})" for l, c in top_langs)
            lines.append(f"{insight_num}. **Language Distribution**: Top languages: {lang_str}")
        insight_num += 1

    # 2. 主题热度
    topic_counts: dict[str, int] = {}
    for r in all_repos:
        for tp in r.get("topics", []):
            tl = tp.lower()
            if tl in _TOPIC_LABELS:
                label = _TOPIC_LABELS[tl]
                topic_counts[label] = topic_counts.get(label, 0) + 1
    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    if top_topics:
        if lang == "zh":
            topic_str = "、".join(f"{t}({c})" for t, c in top_topics)
            lines.append(f"{insight_num}. **热门领域**: {topic_str}")
        else:
            topic_str = ", ".join(f"{t}({c})" for t, c in top_topics)
            lines.append(f"{insight_num}. **Hot Topics**: {topic_str}")
        insight_num += 1

    # 3. 新项目涌现
    new_repos: list[str] = []
    for r in all_repos:
        created = r.get("created_at")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if (NOW - dt).days <= 7:
                    new_repos.append(r.get("full_name", "").split("/")[-1])
            except (ValueError, TypeError):
                pass
    if new_repos:
        if lang == "zh":
            names = "、".join(new_repos[:5])
            lines.append(f"{insight_num}. **新项目涌现**: 本期有 {len(new_repos)} 个创建不到一周的全新项目上榜 ({names})")
        else:
            names = ", ".join(new_repos[:5])
            lines.append(f"{insight_num}. **New Projects**: {len(new_repos)} projects created within the last week ({names})")
        insight_num += 1

    # 4. 今日最热
    hottest = max(all_repos, key=lambda x: x.get("today_stars", 0), default=None)
    if hottest and hottest.get("today_stars", 0) > 0:
        name = hottest.get("full_name", "")
        today = hottest.get("today_stars", 0)
        if lang == "zh":
            lines.append(f"{insight_num}. **今日最热**: [{name}](https://github.com/{name}) 今日获得 +{_fmt(today)} stars")
        else:
            lines.append(f"{insight_num}. **Hottest Today**: [{name}](https://github.com/{name}) gained +{_fmt(today)} stars today")
        insight_num += 1

    # 5. 大型项目活跃度
    big_active = [r for r in all_repos
                  if r.get("stargazers_count", 0) > 50000 and r.get("today_stars", 0) > 50]
    if big_active:
        if lang == "zh":
            names = "、".join(r.get("full_name", "").split("/")[-1] for r in big_active[:5])
            lines.append(f"{insight_num}. **大型项目活跃**: {names} 等成熟项目持续保持高活跃度")
        else:
            names = ", ".join(r.get("full_name", "").split("/")[-1] for r in big_active[:5])
            lines.append(f"{insight_num}. **Active Established Projects**: {names} continue to maintain high activity")
        insight_num += 1

    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


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
        lines.append(s["separator"])
        for i, r in enumerate(repos[:top_n], 1):
            name = r.get("full_name", "")
            url = r.get("html_url") or f"https://github.com/{name}"
            rlang = (r.get("language") or "-")[:10]
            stars = _fmt(r.get("stargazers_count", 0))
            today = r.get("today_stars", 0)
            today_str = f"+{_fmt(today)}" if today else "-"
            growth = r.get("_growth_rate", 0)
            growth_str = f"{_fmt(growth)}/d" if growth else "-"
            score = r.get("_score", 0)
            summary = r.get("_summary") or r.get("_readme_summary") or r.get("description") or ""
            # MISSING-9: NEW 标签
            new_badge = ""
            created = r.get("created_at")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if (NOW - dt).days <= 7:
                        new_badge = "**NEW** "
                except (ValueError, TypeError):
                    pass
            lines.append(f"| {i} | {new_badge}[{name}]({url}) | {rlang} | {stars} | {today_str} | {growth_str} | {score} | {summary} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    _table(s["core_section"].format(n=core_n), core, core_n)
    _table(s["app_section"].format(n=app_n), apps, app_n)

    # MISSING-7: 趋势洞察
    insight_lines = _generate_trend_insights(core[:core_n], apps[:app_n], lang)
    lines.extend(insight_lines)

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
                        help="输出报告基础路径 (不含扩展名); 默认 reports/YYYY-MM-DD/ai_trending_YYYY-MM-DD")
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
        report_base = os.path.join(dir_path, f"ai_trending_{date_str}")

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

    # BUG-3: 为仅来自 Trending 的仓库补充完整元数据
    _enrich_trending_metadata(all_repos, token=args.token)

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

    # BUG-1: 计算排名变化
    _compute_rank_changes(core_list, prev_data, "ai_llm_core_top10")
    _compute_rank_changes(app_list, prev_data, "ai_app_top20")

    console.print(f"    分类完成: 核心 {len(core_list)} / 应用 {len(app_list)} (个人向, 已去重)")

    if not core_list and not app_list:
        console.print("[red]未获取到任何 AI 仓库数据。[/red]")
        sys.exit(1)

    # 5. 抓取 README & LLM 分析性总结
    console.print("[cyan]>>> [5/6] 抓取 README & 生成分析性总结...[/cyan]")
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
