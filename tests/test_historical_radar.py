import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from github_trending import RadarAdapters, generate_report


def repo(name: str, stars: int, *, today_stars: int = 0, topics=None) -> dict:
    return {
        "id": abs(hash(name)) % 1_000_000,
        "full_name": name,
        "stargazers_count": stars,
        "forks_count": 1,
        "open_issues_count": 0,
        "description": "An AI coding agent.",
        "topics": topics or ["ai-agent"],
        "created_at": "2026-07-01T00:00:00Z",
        "pushed_at": "2026-07-28T07:00:00Z",
        "language": "Python",
        "html_url": f"https://github.com/{name}",
        "today_stars": today_stars,
    }


class HistoricalRadarTests(unittest.TestCase):
    def config(self, root: Path) -> dict:
        return {
            "rankings": {"core_top_n": 10, "app_top_n": 20, "deduplicate": True},
            "scoring": {
                "today_stars_weight": 0.40,
                "growth_rate_weight": 0.30,
                "recency_weight": 0.15,
                "base_stars_weight": 0.15,
            },
            "classification": {
                "core_topics": [], "core_keywords_in_desc": [], "core_keywords_in_name": [],
                "app_topics": ["ai-agent"], "app_keywords_in_desc": ["ai coding agent"],
                "app_keywords_in_name": [], "enterprise_topics": [],
                "enterprise_keywords_in_desc": [], "personal_boost_keywords": [],
            },
            "history": {
                "directory": str(root / "history"),
                "watchlist_path": str(root / "watchlist.yaml"),
                "discovery_pool_size": 100,
                "retention_days": 365,
                "min_api_repos": 1,
                "min_trending_repos": 1,
                "min_candidates": 1,
            },
        }

    def adapters(self, api, trending, watched=None) -> RadarAdapters:
        return RadarAdapters(
            fetch_api=lambda: api,
            fetch_trending=lambda: trending,
            fetch_watchlist=lambda names: watched or [],
        )

    def test_complete_run_records_discovery_pool_and_watchlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "watchlist.yaml").write_text("repositories:\n  - owner/watched\n", encoding="utf-8")
            result = generate_report(
                self.config(root),
                datetime(2026, 7, 28, tzinfo=timezone.utc),
                self.adapters([repo("owner/candidate", 50)], [repo("owner/candidate", 50, today_stars=12)], [repo("owner/watched", 9, topics=[])]),
            )

            snapshot = json.loads((root / "history" / "2026-07-28.json").read_text(encoding="utf-8"))
            names = {item["full_name"] for item in snapshot["repositories"]}
            self.assertTrue(result.complete)
            self.assertEqual(names, {"owner/candidate", "owner/watched"})
            candidate = next(item for item in snapshot["repositories"] if item["full_name"] == "owner/candidate")
            watched = next(item for item in snapshot["repositories"] if item["full_name"] == "owner/watched")
            self.assertEqual(candidate["growth_source"], "trending")
            self.assertEqual(candidate["growth_confidence"], "high")
            self.assertEqual(watched["discovery_status"], "provisional")
            self.assertTrue(watched["watchlist"])

    def test_estimated_growth_enters_discovery_pool_but_not_main_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_report(
                self.config(root),
                datetime(2026, 7, 28, tzinfo=timezone.utc),
                self.adapters([repo("owner/unverified", 50)], [repo("owner/other", 10, today_stars=1)]),
            )

            self.assertTrue(result.complete)
            self.assertEqual([item["full_name"] for item in result.report["ai_app_top20"]], ["owner/other"])
            snapshot = json.loads((root / "history" / "2026-07-28.json").read_text(encoding="utf-8"))
            candidate = next(item for item in snapshot["repositories"] if item["full_name"] == "owner/unverified")
            self.assertEqual(candidate["discovery_status"], "provisional")

    def test_incomplete_run_writes_status_without_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_report(
                self.config(root),
                datetime(2026, 7, 28, tzinfo=timezone.utc),
                self.adapters([repo("owner/candidate", 50)], []),
            )

            self.assertFalse(result.complete)
            self.assertFalse((root / "history" / "2026-07-28.json").exists())
            status = json.loads((root / "history" / "run-status" / "2026-07-28.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "incomplete")

    def test_watchlist_rule_matching_allows_missing_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "watchlist.yaml").write_text("rules:\n  - topic: ai-agent\n", encoding="utf-8")
            candidate = repo("owner/no-description", 50)
            candidate["description"] = None
            result = generate_report(
                self.config(root),
                datetime(2026, 7, 28, tzinfo=timezone.utc),
                self.adapters([candidate], [repo("owner/no-description", 50, today_stars=4)]),
            )

            self.assertTrue(result.complete)

    def test_second_complete_observation_uses_history_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            first = datetime(2026, 7, 27, tzinfo=timezone.utc)
            second = datetime(2026, 7, 28, tzinfo=timezone.utc)
            generate_report(config, first, self.adapters([repo("owner/project", 100)], [repo("owner/project", 100, today_stars=5)]))
            result = generate_report(config, second, self.adapters([repo("owner/project", 125)], [repo("owner/other", 10, today_stars=1)]))

            item = result.report["ai_app_top20"][0]
            self.assertEqual(item["full_name"], "owner/project")
            self.assertEqual(item["growth_source"], "history_delta")
            self.assertEqual(item["growth_confidence"], "high")
            self.assertEqual(item["growth_score"], 25.0)

    def test_seven_complete_observations_enable_a_seven_day_trend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config = Path(tmp), None
            config = self.config(root)
            for day in range(21, 28):
                generate_report(config, datetime(2026, 7, day, tzinfo=timezone.utc), self.adapters([repo("owner/project", 100 + day)], [repo("owner/project", 100 + day, today_stars=3)]))
            result = generate_report(config, datetime(2026, 7, 28, tzinfo=timezone.utc), self.adapters([repo("owner/project", 130)], [repo("owner/project", 130, today_stars=3)]))

            item = result.report["ai_app_top20"][0]
            self.assertTrue(item["trend_ready"])
            self.assertEqual(len(item["trend_7d"]), 7)


if __name__ == "__main__":
    unittest.main()
