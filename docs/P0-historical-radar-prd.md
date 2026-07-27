# P0 PRD：GitHub AI Radar 历史趋势与可信度

## 1. 目标

把 GitHub AI Radar 从“当天哪些仓库热门”的日报，升级为能回答下列问题的趋势雷达：

- 一个项目是在持续增长，还是单日爆发？
- 它第一次被发现是什么时候？连续上榜多久？
- 今天的增长数字是 GitHub Trending 的真实日增、历史快照差值，还是估算值？
- 为什么它会排在这个位置？

本期只交付历史趋势与评分可信度，不包含用户账号、订阅通知或外部数据库服务。趋势 UI 在收集到 7 个完整日快照后才启用；在此之前，页面只显示“趋势数据积累中”。

## 2. 非目标

- 不追踪 GitHub 上所有仓库；仅持久化每日发现池 Top 100 和 Watchlist 项目。
- 不改变当前 Core / Personal App 双榜的默认数量和分类规则。
- 不需要部署后端；继续兼容 GitHub Actions + GitHub Pages 的纯静态发布模式。
- 不用 LLM 判断热度或生成投资建议。

## 3. 用户故事与验收结果

| 用户故事 | 验收结果 |
|---|---|
| 作为读者，我想知道项目是否持续走强 | 卡片可显示最近 7 天走势、首次观察日、连续上榜天数和生命周期标签 |
| 作为读者，我想知道“增长”是否可靠 | 每个增长值均有来源和置信度；估算值不会被表述为真实日增 |
| 作为读者，我想理解排名 | 可展开查看 today stars、增长、近期活跃度和基础影响力的评分贡献 |
| 作为维护者，我想以最小成本保留历史 | 每次任务只新增一个 Top 100 + Watchlist 的按日快照文件，日报清理不影响历史趋势数据 |

## 4. 信息架构

```text
GitHub Search + Trending + 前一日历史快照
                 │
                 ▼
         候选池、分类、双层排序
                 │
                 ├─────→ reports/YYYY-MM-DD/（人读日报，保留 30 天）
                 │
                 └─────→ docs/data/history/YYYY-MM-DD.json（Top 100 + Watchlist，保留 365 天）
                                      │
                                      ▼
                           Pages：今日榜单（只携带当前卡片所需的 7 日数据）
```

## 5. 数据契约

### 5.1 每日历史快照

路径：`docs/data/history/YYYY-MM-DD.json`

每个文件只记录当日发现池 Top 100 与 Watchlist 项目。字段设计刻意与 UI 解耦；页面不可依赖原始 GitHub API 响应。

```json
{
  "schema_version": 1,
  "date": "2026-07-28",
  "generated_at": "2026-07-28T08:00:00+00:00",
  "repositories": [
    {
      "id": 123456,
      "full_name": "owner/repo",
      "stars": 12000,
      "forks": 800,
      "issues": 42,
      "pushed_at": "2026-07-28T06:00:00Z",
      "today_stars": 320,
      "today_stars_source": "trending",
      "growth_per_day": 320.0,
      "growth_source": "trending",
      "growth_confidence": "high",
      "hotness_score": 18.42,
      "score_breakdown": {
        "today_stars": 4.01,
        "growth_rate": 3.47,
        "recency": 1.21,
        "base_stars": 2.04
      },
      "categories": ["core"],
      "discovery_status": "verified",
      "rank": {"core": 2}
    }
  ]
}
```

规则：

- `id` 优先采用 GitHub 的不可变 repository id；缺失时可用 `full_name` 作为兼容键。
- `categories` 可同时包含 `core` 与 `app`；排名仍按现有去重规则输出。
- `rank` 只包含实际进入该榜单 Top N 的分类。
- `discovery_status` 为 `verified`（有真实增长信号）或 `provisional`（仅发现分）；后者不能进入主榜。
- `score_breakdown` 的数值之和必须等于 `hotness_score`（允许 0.01 浮点误差）。

### 5.2 Watchlist

路径：`watchlist.yaml`。它由仓库维护者配置，随 Fork 生效；公开站点访客本期不能创建个人 Watchlist。

```yaml
repositories:
  - owner/repo
rules:
  - topic: coding-agent
  - keyword: local-first
```

规则：

- `repositories` 内的固定仓库每天独立通过 GitHub API 采样，即使不属于 AI 分类、当天不在候选池或未上榜。
- `rules` 只筛选已采集候选池，不新增额外搜索请求。
- Watchlist 项目在快照中标记为 `watchlist`；是否进入主榜仍服从主榜资格规则。

### 5.3 历史读取与留存

每日快照是唯一事实来源，保留 365 天。生成任务可维护一个可重建的本地索引以加速计算，但首页绝不请求全量索引；它只从当天 `latest.json` 读取卡片所需的最近 7 个观测点。

超过 365 天的每日快照可删除。本期不实现月度聚合、分片索引或独立历史页面；这些是后续历史浏览页的实现选择，不应阻碍 P0。

### 5.4 今日报告扩展

现有 `latest.json` 的仓库对象新增以下可选字段，旧字段保持不变：

```json
{
  "growth_source": "history_delta",
  "growth_confidence": "high",
  "first_observed_at": "2026-07-02",
  "streak_days": 6,
  "lifecycle": "accelerating",
  "score_breakdown": {"today_stars": 4.01, "growth_rate": 3.47, "recency": 1.21, "base_stars": 2.04},
  "trend_7d": [{"date": "2026-07-22", "stars": 9000}, {"date": "2026-07-28", "stars": 12000}]
}
```

字段缺失时，前端必须隐藏相应 UI，不显示 `0` 或“未知趋势”的误导性状态。`trend_7d` 是每日净增序列，包含日期、净增和置信度，而不是单调上升的累计 Stars 折线。

## 6. 计算口径

### 6.1 增长来源与置信度

| 来源 | 条件 | `growth_source` | 置信度 | UI 文案 |
|---|---|---|---|---|
| GitHub Trending | 当日页面有 `today_stars > 0` | `trending` | 高 | “GitHub Trending 日增” |
| 历史快照差值 | 相隔 1–2 天均有快照，且 star 差值非负 | `history_delta` | 高 | “与上次快照相比” |
| 跨日历史差值 | 间隔 3–7 天 | `history_delta` | 中 | “按 N 天快照均值” |
| 项目生命周期估算 | 没有可用真实差值 | `age_estimate` | 低 | “按项目年龄估算，不代表日增” |
| 数据不足 | 上述条件均不满足 | `unknown` | 低 | 不显示增长数字 |

优先级调整为 Trending → 历史快照差值 → 年龄估算。当前榜单中的 `growth_score` 保持向后兼容，但新代码内部统一使用 `growth_per_day`。

主榜资格与发现池资格必须分离：主榜只接受 `trending` 或 `history_delta` 的真实信号；`age_estimate` 只用于每日发现池的初步排序和第二天的验证，不能贡献主榜增长分或让项目直接上榜。相同不可变 repository id 的负 star 差是高置信度负增长；评分时增长贡献截断为 0，但趋势和标签计算保留真实负值。

### 6.2 生命周期标签

标签优先级为 `new`、`resurfacing`、趋势标签。趋势标签只在至少有 6 个高/中置信度观测点、且最近 7 天没有超过 2 天断档时显示：

- `accelerating`：最近 3 点的平均日增长比此前 3 点高 30% 以上。
- `steady`：最近 3 点平均增长变动在 ±30% 内。
- `cooling`：最近 3 点的平均日增长比此前 3 点低 30% 以上。
- `resurfacing`：最近 7 天前曾出现过、过去 3 天未上榜、今日重新进入 Top N。
- `new`：首次被新快照体系观察到不足 7 天。

不满足条件时显示“趋势数据积累中”。先以规则实现；后续有足够历史数据再评估统计模型。标签必须附带可解释的阈值，不作为热度评分输入。

### 6.3 评分拆解

将 `hotness_score()` 改为同时返回总分与分项：

```python
Score(total: float, contributions: dict[str, float])
```

分项沿用现有公式和配置权重，但主榜不再允许年龄估算的增长分参与竞争。`_repo_summary()` 只消费这个计算结果，不重复评分逻辑。JSON 保存全精度；默认 UI 显示四项对总分的贡献百分比和来源说明，展开“计算详情”才展示公式、权重与精确贡献值。

## 7. 页面设计

不新增框架，保持现有单页面模板与原生 JavaScript。

### 今日卡片

在现有数据行下增加一行紧凑元信息：

```text
  ◔ 连续上榜 6 天   ↗ 加速中   可信度：高
  [查看 7 日趋势与评分依据]
```

点击后展开而非跳页，包含：

- SVG 柱状图：最近 7 天每日净增；无连续真实观测时不补零、不连线，并显式显示数据缺口与置信度。
- 首次观察、最近观测、连续上榜天数，以及累计 Stars 起止值。
- 四项评分的水平条与贡献百分比；计算详情中显示精确值。
- 增长来源与解释。

无障碍要求：按钮使用 `aria-expanded`；图表有文字摘要；颜色不是表达趋势或置信度的唯一方式。

### 历史页面（后续）

第一期先通过卡片展开提供趋势。数据稳定后再增加 `history.html`：可按日期浏览双榜并选择某个项目查看 30 天曲线。届时按项目分片加载，不引入路由或前端构建链。

## 8. 实施切分

| 阶段 | 交付物 | 影响 |
|---|---|---|
| 1. 历史写入 | `history` 模块、Top 100 + Watchlist 快照、schema 校验、完整运行门槛 | 后端数据基础；页面不变 |
| 2. 可信增长 | 主榜/发现池双层资格、`growth_source`、`growth_confidence`、评分拆解 | 现有 JSON 向后兼容 |
| 3. 冷启动发布 | 页面显示来源/置信度与“趋势数据积累中” | 首日可发布 |
| 4. 趋势呈现 | 第 7 个完整快照后启用净增图、连续上榜和生命周期标签 | `templates/index.html` |

## 9. 模块边界

当前主脚本可逐步抽出以下模块；外部调用只需要 `generate_report(config, now, adapters)`，维持较小 interface。

```text
collectors       GitHub Search / Trending / Watchlist adapter，返回原始仓库与运行状态
history          load_snapshot、record_snapshot、select_discovery_pool、build_trend
ranking          classify、measure_growth、score、rank
enrichment       README 与双语介绍
publishers       JSON、Markdown、Pages 输出
```

`history` 的 interface 不暴露文件布局细节；它接收规范化仓库记录，返回观测与趋势。这样未来替换为 SQLite、对象存储或 GitHub API artifact 时，`ranking` 和 `publishers` 无需改变。

## 10. 迁移与兼容

1. 首次发布时可扫描 `reports/*/*.json`，为历史榜单项目补充稀疏累计 Stars 观测；没有保存的字段不臆造。
2. 旧报告只允许显示为稀疏历史；不能参与 `streak_days`、真实增长或生命周期判断。字段统一为 `first_observed_at`，不将它表述为“首次发现”。
3. 旧报告没有 `growth_source`、`trend_7d` 时，前端保持当前卡片表现。
4. `docs/data/history/` 不受现有“清理 30 天 reports”步骤影响，按 365 天独立清理。
5. 现有 `ai_llm_core_top10`、`ai_app_top20` 键名保持不变，避免 Fork 用户或外部脚本失效。

## 11. 运行完整性与部署

- 只有 GitHub Search 与 Trending 均成功，且候选数达到配置下限时，才写入正式日快照、更新趋势字段和部署新的 `latest.json`。
- 不完整运行只写入诊断 `run-status`；它不参与趋势计算，页面继续服务最后一次完整数据并标注最近一次完整更新时间。
- 删除或改为仅 `workflow_dispatch` 触发 `pages.yml`；每日生成与 Pages 部署只由 `daily.yml` 完成，避免同一次提交触发两次部署。

## 12. 测试与验收

- 给定固定 API / Trending / 历史 fixture，榜单顺序与当前公式一致。
- 连续两天相同仓库的快照会产生正确的 `history_delta` 与 `streak_days`。
- 低置信度项目可进入 Top 100 发现池但不能进入主榜；固定 Watchlist 项目即使不在候选池也会被采样。
- 缺一日、改名、无 Trending 数据或不完整运行时不产生伪造高置信度；同 id 的负 star 差被保留为真实负增长。
- `score_breakdown` 的和与 `hotness_score` 一致。
- 旧版 `latest.json` 能被新模板无报错渲染。
- 新版 `latest.json` 在桌面与窄屏下都可展开、收起，语言切换后不丢失趋势信息；首页不请求全量历史索引。
- `python -m unittest` 覆盖 ranking/history/publishers 的纯函数，网络只留在 collector adapter 的集成测试中。

## 13. 成功指标

- 数据：连续 14 天成功生成完整历史快照；每日快照 schema 校验通过率 100%。
- 质量：高/中置信度增长字段都能追溯到 Trending 或历史观测。
- 产品：用户在无需离开榜单的情况下，能判断任一 Top 项目的“持续性、来源与排名原因”。
