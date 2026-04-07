"""
GitHub 过去 48 小时真正热门的 AI 仓库抓取工具

核心理念: 用 star 增量 / 增长速率排序, 而非总 star 数
  - today_stars  : 来自 GitHub Trending 页面 (当日 star 增量, 最准确)
  - growth_rate  : stars / 仓库年龄天数 (平均日增速, 新项目天然优势)
  - 新创建查询   : created:>48h 捕获刚爆发的全新项目

榜单:
  1. AI/LLM 核心仓库 Top 10
  2. AI 应用类仓库 Top 20

用法:
  python github_trending.py [--token GITHUB_TOKEN] [--no-verify] [--output FILE]
"""

import argparse
import io
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import urllib3
import requests
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

SSL_VERIFY: bool = True
NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# 分类关键词 (不变)
# ---------------------------------------------------------------------------

AI_CORE_TOPICS = {
    "machine-learning", "deep-learning", "neural-network", "deep-neural-networks",
    "llm", "llms", "large-language-model", "transformer", "transformers",
    "nlp", "natural-language-processing", "computer-vision", "cv",
    "speech-recognition", "reinforcement-learning",
    "pytorch", "tensorflow", "jax", "mxnet", "onnx", "triton",
    "diffusion", "stable-diffusion", "text-to-image",
    "embedding", "embeddings", "vector-database", "faiss",
    "inference", "model-serving", "model-hub", "pretrained-models",
    "fine-tuning", "rlhf", "lora", "quantization",
    "cuda", "gpu", "tpu", "distributed-training",
    "multimodal", "vlm", "vision-language-model",
}

AI_CORE_KW_IN_DESC = [
    "machine learning", "deep learning", "neural network",
    "large language model", "llm framework", "model training",
    "inference engine", "serving engine", "model hub",
    "transformer", "diffusion model", "embedding",
    "pre-trained", "pretrained", "fine-tun",
]

AI_APP_TOPICS = {
    "ai", "artificial-intelligence", "generative-ai", "genai",
    "agent", "ai-agent", "agentic-ai", "agentic-workflow", "agentic-framework",
    "chatbot", "chat", "conversational-ai",
    "rag", "retrieval-augmented-generation",
    "copilot", "ai-assistant", "ai-coding", "code-generation",
    "openai", "gpt", "gpt-4", "gpt-4o", "chatgpt",
    "claude", "gemini", "deepseek", "qwen", "llama",
    "langchain", "llamaindex", "autogen",
    "prompt-engineering", "prompt",
    "text-generation", "image-generation",
    "automation", "workflow", "orchestration",
    "low-code", "no-code",
    "mcp", "function-calling", "tool-use",
    "ollama", "local-llm",
}

AI_APP_KW_IN_DESC = [
    "ai assistant", "ai agent", "coding agent", "chatbot",
    "gpt", "openai", "claude", "gemini", "deepseek", "llama",
    "copilot", "ai-powered", "ai tool",
    "rag", "retrieval augmented", "agentic",
    "prompt", "workflow", "orchestrat",
    "local llm", "run llm", "ollama",
    "text generat", "image generat", "voice",
]

# ---------------------------------------------------------------------------
# 企业级排除 — 用于 AI 应用榜, 只保留个人使用向的项目
# ---------------------------------------------------------------------------

ENTERPRISE_TOPICS = {
    "enterprise", "saas", "mlops", "devops", "infrastructure",
    "data-pipeline", "etl", "monitoring", "observability",
    "cloud-native", "microservices", "kubernetes", "k8s",
    "ci-cd", "api-gateway", "service-mesh",
}

ENTERPRISE_KW_IN_DESC = [
    "enterprise", "production-ready platform", "saas platform",
    "b2b", "for teams", "for organizations", "for companies",
    "mlops", "devops", "data pipeline", "etl pipeline",
    "monitoring platform", "observability platform",
    "api platform", "api for ai", "cloud platform",
    "deployment platform", "infrastructure platform",
    "team collaboration platform", "organization management",
    "customer support platform", "customer service platform",
    "crm", "erp",
]

PERSONAL_BOOST_KW = [
    "personal", "local", "self-hosted", "cli", "terminal",
    "desktop", "browser extension", "private", "offline",
    "your own", "on your machine", "run locally",
    "note", "productivity", "bookmark", "journal",
]


def _is_personal_use(repo: dict) -> bool:
    """过滤: 排除企业级平台, 保留个人使用向的 AI 应用."""
    desc = (repo.get("description") or "").lower()
    topics = set(t.lower() for t in repo.get("topics", []))

    # 明确命中企业关键词 → 排除
    if topics & ENTERPRISE_TOPICS:
        return False
    if any(kw in desc for kw in ENTERPRISE_KW_IN_DESC):
        return False

    return True


def _classify(repo: dict) -> tuple[bool, bool]:
    topics = set(t.lower() for t in repo.get("topics", []))
    desc = (repo.get("description") or "").lower()
    name = (repo.get("full_name") or "").lower()

    is_core = bool(topics & AI_CORE_TOPICS) or any(kw in desc for kw in AI_CORE_KW_IN_DESC)
    is_app = bool(topics & AI_APP_TOPICS) or any(kw in desc for kw in AI_APP_KW_IN_DESC)

    for kw in ("llm", "transformer", "diffusion", "neural", "torch", "tensor"):
        if kw in name:
            is_core = True
    for kw in ("agent", "chat", "copilot", "gpt", "ai-", "ollama"):
        if kw in name:
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


def _search(query: str, token: Optional[str] = None, pages: int = 2, per_page: int = 100) -> list[dict]:
    headers = _headers(token)
    repos: list[dict] = []
    for page in range(1, pages + 1):
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": per_page, "page": page}
        try:
            resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=15, verify=SSL_VERIFY)
            if resp.status_code == 403:
                console.print(f"  [yellow]速率受限, 等待 12s...[/yellow]")
                time.sleep(12)
                resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=15, verify=SSL_VERIFY)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if not items:
                break
            repos.extend(items)
        except requests.RequestException as exc:
            console.print(f"  [red]请求失败 (page {page}): {exc}[/red]")
            break
        time.sleep(2)
    return repos


def fetch_ai_repos(token: Optional[str] = None) -> list[dict]:
    """
    多维度搜索策略:
      A) pushed:>48h + topic:X  → 活跃的已有项目
      B) created:>48h + AI 关键词 → 新创建且快速增长的项目
    """
    d2 = (NOW - timedelta(hours=48)).strftime("%Y-%m-%d")

    # A: 主力查询 — 各 AI topic 下最近有 push 的项目
    topic_queries = [
        f"pushed:>{d2} topic:llm",
        f"pushed:>{d2} topic:machine-learning",
        f"pushed:>{d2} topic:deep-learning",
        f"pushed:>{d2} topic:ai-agent",
        f"pushed:>{d2} topic:generative-ai",
        f"pushed:>{d2} topic:chatbot",
        f"pushed:>{d2} topic:rag",
        f"pushed:>{d2} topic:langchain",
        f"pushed:>{d2} topic:transformer",
        f"pushed:>{d2} topic:diffusion",
        f"pushed:>{d2} topic:nlp",
        f"pushed:>{d2} topic:computer-vision",
        f"pushed:>{d2} topic:openai",
        f"pushed:>{d2} topic:agent",
    ]

    # B: 新项目爆发查询 — 48h 内创建、带 AI 关键词、已获得一定 star
    new_queries = [
        f"created:>{d2} stars:>50 topic:ai",
        f"created:>{d2} stars:>50 topic:llm",
        f"created:>{d2} stars:>20 topic:agent",
        f"created:>{d2} stars:>50 machine learning",
        f"created:>{d2} stars:>50 deep learning",
    ]

    all_queries = topic_queries + new_queries
    seen: dict[str, dict] = {}
    total = len(all_queries)

    for idx, q in enumerate(all_queries, 1):
        label = q.split("topic:")[-1] if "topic:" in q else q.split(f">{d2} ")[-1]
        console.print(f"  [dim][{idx}/{total}] {label[:40]}...[/dim]")
        items = _search(q, token=token, pages=2, per_page=100)
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


def fetch_trending() -> list[dict]:
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
    for row in soup.select("article.Box-row"):
        h2 = row.select_one("h2 a")
        if not h2:
            continue
        full_name = h2.get("href", "").strip("/")
        desc_tag = row.select_one("p")
        lang_tag = row.select_one("[itemprop='programmingLanguage']")

        stars_total = forks_total = today_stars = 0
        for link in row.select("a.Link--muted"):
            href = link.get("href", "")
            text = link.get_text(strip=True).replace(",", "")
            num = _parse_int(text)
            if "/stargazers" in href:
                stars_total = num
            elif "/forks" in href:
                forks_total = num
        ts = row.select_one("span.d-inline-block.float-sm-right")
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
    return repos


def _parse_int(text: str) -> int:
    cleaned = "".join(ch for ch in text if ch.isdigit())
    return int(cleaned) if cleaned else 0


# ---------------------------------------------------------------------------
# 增长速率 & 热度评分 (核心改造)
# ---------------------------------------------------------------------------


def _compute_growth_rate(repo: dict) -> float:
    """平均日增 star 数 = total_stars / 仓库年龄天数. 新项目天然高."""
    stars = repo.get("stargazers_count", 0)
    created = repo.get("created_at")
    if not created or stars == 0:
        return 0.0
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_days = max((NOW - dt).total_seconds() / 86400, 0.5)  # 至少半天
        return round(stars / age_days, 1)
    except (ValueError, TypeError):
        return 0.0


def hotness_score(repo: dict) -> float:
    """
    热度评分 (增长导向):
      - today_stars          * 0.40  (最直接的近期热度, 来自 Trending)
      - growth_rate          * 0.30  (日均增速, 新项目高)
      - recency_bonus        * 0.15  (push 时间越近越高)
      - log2(total_stars)    * 0.15  (基础影响力, 权重压低)
    """
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
            recency = max(0, 10 - hours_ago * 0.2)  # 48h → 0.4, 0h → 10
        except (ValueError, TypeError):
            pass

    s = (
        math.log2(1 + today) * 3.0 * 0.40       # today_stars 高权重
        + math.log2(1 + growth) * 2.0 * 0.30     # 增长速率
        + recency * 0.15                          # push 时间新鲜度
        + math.log2(1 + stars) * 0.15             # 基础影响力 (低权重)
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
            seen[key]["today_stars"] = r.get("today_stars", 0)
            seen[key]["source"] = "both"
        else:
            seen[key] = r
    return list(seen.values())


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
        desc = (r.get("description") or "N/A")[:72]
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

def _repo_summary(r: dict) -> dict:
    return {
        "full_name": r.get("full_name"),
        "description": r.get("description"),
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
    }


def _report_dir(base: str = "reports") -> tuple[str, str]:
    """返回 (目录路径, 日期字符串), 自动创建 reports/YYYY-MM-DD/ 目录."""
    date_str = NOW.strftime("%Y-%m-%d")
    dir_path = os.path.join(base, date_str)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path, date_str


def save_report(core: list[dict], apps: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    report = {
        "generated_at": NOW.isoformat(),
        "methodology": "Ranked by hotness_score = today_stars(0.40) + growth_rate(0.30) + recency(0.15) + base_stars(0.15)",
        "ai_llm_core_top10": [_repo_summary(r) for r in core[:10]],
        "ai_app_top20": [_repo_summary(r) for r in apps[:20]],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    console.print(f"\n  [green]>>> JSON 报告已保存: {path}[/green]")


def save_md_report(core: list[dict], apps: list[dict], path: str,
                   core_count: int = 0, app_count: int = 0) -> None:
    """生成 Markdown 格式的报告."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines: list[str] = []

    lines.append("# GitHub AI 热门仓库报告")
    lines.append("")
    lines.append(f"> 数据时间: {NOW.strftime('%Y-%m-%d %H:%M UTC')} | 时间窗口: 过去 48 小时")
    lines.append(">")
    lines.append("> 评分公式: `today_stars(40%) + growth_rate(30%) + recency(15%) + base_stars(15%)`")
    if core_count or app_count:
        lines.append(f"> 采集范围: 核心 {core_count} / 应用 {app_count} (个人向)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- 核心榜 ---
    lines.append("## AI/LLM 核心仓库 Top 10")
    lines.append("")
    lines.append("| # | 仓库 | 语言 | Stars | 日增速 | 热度 | 简介 |")
    lines.append("|--:|------|------|------:|-------:|-----:|------|")
    for i, r in enumerate(core[:10], 1):
        name = r.get("full_name", "")
        url = r.get("html_url") or f"https://github.com/{name}"
        lang = (r.get("language") or "-")[:10]
        stars = _fmt(r.get("stargazers_count", 0))
        growth = r.get("_growth_rate", 0)
        growth_s = f"{_fmt(growth)}/d" if growth else "-"
        score = r.get("_score", 0)
        desc = (r.get("description") or "")[:60]
        # 标记新项目
        created = r.get("created_at")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if (NOW - dt).days < 7:
                    desc = f"**NEW** {desc}"
            except (ValueError, TypeError):
                pass
        lines.append(f"| {i} | [{name}]({url}) | {lang} | {stars} | {growth_s} | {score} | {desc} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- 应用榜 ---
    lines.append("## AI 个人应用 Top 20")
    lines.append("")
    lines.append("| # | 仓库 | 语言 | Stars | 日增速 | 热度 | 简介 |")
    lines.append("|--:|------|------|------:|-------:|-----:|------|")
    for i, r in enumerate(apps[:20], 1):
        name = r.get("full_name", "")
        url = r.get("html_url") or f"https://github.com/{name}"
        lang = (r.get("language") or "-")[:10]
        stars = _fmt(r.get("stargazers_count", 0))
        growth = r.get("_growth_rate", 0)
        growth_s = f"{_fmt(growth)}/d" if growth else "-"
        score = r.get("_score", 0)
        desc = (r.get("description") or "")[:60]
        created = r.get("created_at")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if (NOW - dt).days < 7:
                    desc = f"**NEW** {desc}"
            except (ValueError, TypeError):
                pass
        lines.append(f"| {i} | [{name}]({url}) | {lang} | {stars} | {growth_s} | {score} | {desc} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 `github_trending.py` 自动生成*")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    console.print(f"  [green]>>> MD  报告已保存: {path}[/green]")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    global SSL_VERIFY

    parser = argparse.ArgumentParser(description="GitHub 48h AI 热门仓库排行榜 (增长驱动)")
    parser.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub PAT (可选, 也可通过 GITHUB_TOKEN 环境变量设置)")
    parser.add_argument("--no-verify", action="store_true", help="跳过 SSL 证书验证")
    parser.add_argument("--output", type=str, default=None,
                        help="输出报告基础路径 (不含扩展名); 默认 reports/YYYY-MM-DD/github_hot_repo_YYYY-MM-DD")
    args = parser.parse_args()

    # 确定报告输出路径
    if args.output:
        report_base = args.output.rsplit(".", 1)[0]  # 去掉扩展名
    else:
        dir_path, date_str = _report_dir()
        report_base = os.path.join(dir_path, f"github_hot_repo_{date_str}")

    if args.no_verify:
        SSL_VERIFY = False
        console.print("[yellow]>>> SSL 证书验证已禁用[/yellow]")

    # 1. 抓取
    console.print("[cyan]>>> [1/4] Search API: AI topic + 新项目爆发查询...[/cyan]")
    api_repos = fetch_ai_repos(token=args.token)
    console.print(f"    API 共获取 {len(api_repos)} 个去重仓库")

    console.print("[cyan]>>> [2/4] GitHub Trending (today_stars)...[/cyan]")
    trending = fetch_trending()
    console.print(f"    Trending 返回 {len(trending)} 条")

    # 2. 合并 & 计算增长指标
    all_repos = _merge(api_repos, trending)
    console.print(f"[cyan]>>> [3/4] 计算增长速率 & 热度评分...[/cyan]")
    for r in all_repos:
        r["_growth_rate"] = _compute_growth_rate(r)
        r["_score"] = hotness_score(r)

    # 3. 分类
    core_list: list[dict] = []
    app_list: list[dict] = []
    for r in all_repos:
        is_core, is_app = _classify(r)
        if is_core:
            core_list.append(r)
        if is_app:
            app_list.append(r)

    # 应用榜: 过滤掉企业级项目, 只保留个人使用向
    app_list = [r for r in app_list if _is_personal_use(r)]

    core_list.sort(key=lambda x: x["_score"], reverse=True)
    app_list.sort(key=lambda x: x["_score"], reverse=True)

    console.print(f"[cyan]>>> [4/4] 分类完成: 核心 {len(core_list)} / 应用 {len(app_list)} (个人向)[/cyan]")

    if not core_list and not app_list:
        console.print("[red]未获取到任何 AI 仓库数据。[/red]")
        sys.exit(1)

    _print_ranked("AI/LLM Core — Top 10 (48h Hottest)", core_list, 10)
    console.print()
    _print_ranked("AI Apps for Personal Use — Top 20 (48h Hottest)", app_list, 20)

    save_report(core_list, app_list, f"{report_base}.json")
    save_md_report(core_list, app_list, f"{report_base}.md",
                   core_count=len(core_list), app_count=len(app_list))

    console.print(f"\n  [dim]时间窗口: 过去 48 小时 | 数据时间: {NOW.strftime('%Y-%m-%d %H:%M UTC')}[/dim]")
    rate = "未认证 (10 req/min)" if not args.token else "已认证 (30 req/min)"
    console.print(f"  [dim]API 速率: {rate}[/dim]")
    console.print(f"  [dim]评分公式: today_stars(40%) + growth_rate(30%) + recency(15%) + base_stars(15%)[/dim]\n")


if __name__ == "__main__":
    main()
