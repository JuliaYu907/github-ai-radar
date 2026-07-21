import unittest
from types import SimpleNamespace

from github_trending import (
    _build_repo_context,
    _compose_project_intro,
    _extract_summary,
    _llm_summarize_batch,
    _repo_summary,
    ctx,
)


class ReadmeSummaryTests(unittest.TestCase):
    def test_llm_batch_uses_global_config_without_shadowing_context(self):
        class FakeCompletions:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content="1. 这是一个代码分析工具。")
                    )]
                )

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        previous_cfg = ctx.cfg
        ctx.cfg = {
            "llm": {
                "batch_size": 10,
                "max_summary_chars": 220,
                "temperature": 0.1,
            }
        }
        try:
            summaries = _llm_summarize_batch(
                [{
                    "full_name": "owner/project",
                    "description": "A repository analysis tool.",
                    "topics": ["code-analysis"],
                }],
                {"owner/project": "The tool builds a persistent code graph."},
                client,
                "test-model",
            )
        finally:
            ctx.cfg = previous_cfg

        self.assertEqual(summaries["owner/project"], "这是一个代码分析工具。")

    def test_finds_description_after_large_badge_header(self):
        badges = (
            '<p align="center">\n'
            '  <a href="https://example.com"><img alt="badge" '
            'src="https://img.shields.io/badge/test.svg"></a>\n'
            '</p>\n'
        ) * 120
        readme = badges + (
            "\nDify is an open-source LLM app development platform. "
            "It combines AI workflows, RAG pipelines, agent capabilities, "
            "model management, and observability.\n"
        )

        summary = _extract_summary(readme, repo_name="langgenius/dify")

        self.assertTrue(summary.startswith("Dify is an open-source"))
        self.assertNotIn("badge", summary)

    def test_rejects_install_command_before_project_description(self):
        readme = """
# jcode

irm https://jcode.sh/install.ps1 | iex

## Overview

jcode is a coding-agent harness for coordinating agents across complex
codebases while preserving project context between tasks.
"""

        summary = _extract_summary(readme, repo_name="1jehuang/jcode")

        self.assertIn("coding-agent harness", summary)
        self.assertNotIn("install.ps1", summary)

    def test_rejects_warning_release_and_sponsorship_notices(self):
        readme = """
> [!WARNING]
> Official sources only. Do not trust unofficial token contracts.

> Want to support this project? Sponsor the next release.

## About

OpenMontage is an open-source agentic video production system that combines
specialized pipelines, media tools, and reusable agent skills.
"""

        summary = _extract_summary(readme, repo_name="calesthio/OpenMontage")

        self.assertTrue(summary.startswith("OpenMontage is"))
        self.assertNotIn("Official sources", summary)
        self.assertNotIn("Sponsor", summary)

    def test_uses_about_concepts_to_avoid_unrelated_plugin_details(self):
        readme = """
This is intentional. Plugin installs use a canonical identifier for strict
Desktop and API validators. Older posts use a former marketplace identifier.

Not just configs. A complete performance system with skills, instincts,
memory optimization, continuous learning, security scanning, and
research-first development across multiple coding-agent harnesses.
"""

        summary = _extract_summary(
            readme,
            repo_name="affaan-m/ECC",
            about=("The agent harness performance optimization system. Skills, "
                   "instincts, memory, security, and research-first development."),
        )

        self.assertIn("memory optimization", summary)
        self.assertNotIn("canonical identifier", summary)

    def test_uses_about_anchor_for_project_capability_paragraph(self):
        readme = """
## Sponsors
Want to support OpenMontage? Sponsor the next release.

Turn your AI coding assistant into a full video production studio. Describe
what you want in plain language and the agent handles research, scripting,
asset generation, editing, and final composition.

## Agent Compatibility
OpenMontage works with any AI coding assistant that can read files and execute Python.
"""

        summary = _extract_summary(
            readme,
            repo_name="calesthio/OpenMontage",
            about="Open-source agentic video production system with pipelines and tools.",
        )

        self.assertIn("video production studio", summary)
        self.assertNotIn("execute Python", summary)

    def test_ignores_fenced_code(self):
        readme = """
```powershell
irm https://example.com/install.ps1 | iex
```

## Introduction

Example Agent is a local assistant that searches project files and restores
relevant context across coding sessions.
"""

        summary = _extract_summary(readme, repo_name="owner/example-agent")

        self.assertTrue(summary.startswith("Example Agent is"))

    def test_intro_keeps_about_and_adds_distinct_readme_evidence(self):
        intro, source = _compose_project_intro(
            "An open-source LLM application platform.",
            "Dify combines visual workflows, RAG pipelines, agent tools, and model management.",
        )

        self.assertEqual(source, "about+readme")
        self.assertIn("open-source LLM application platform", intro)
        self.assertIn("visual workflows", intro)

    def test_report_keeps_official_about_separate_from_readme(self):
        repo = {
            "full_name": "owner/project",
            "description": "Official GitHub About text.",
            "_readme_summary": "Project is a developer tool for reliable repository analysis.",
            "_intro_zh": "这是一个用于可靠分析代码仓库的开发者工具。",
        }

        result = _repo_summary(repo, 1)

        self.assertEqual(result["description"], "Official GitHub About text.")
        self.assertEqual(result["about"], "Official GitHub About text.")
        self.assertIn("developer tool", result["readme_highlight"])
        self.assertEqual(result["intro_source"], "about+readme")
        self.assertIn("Official GitHub About", result["intro_en"])
        self.assertEqual(result["intro_zh"], "这是一个用于可靠分析代码仓库的开发者工具。")

    def test_translation_context_excludes_popularity_metrics(self):
        context = _build_repo_context(
            {
                "full_name": "owner/project",
                "description": "An agent tool for repository analysis.",
                "topics": ["ai-agent", "code-analysis"],
                "stargazers_count": 999999,
                "today_stars": 5000,
                "_score": 42,
            },
            "The tool builds a persistent code graph for focused retrieval.",
        )

        self.assertIn("官方 GitHub About", context)
        self.assertIn("README 核心段落", context)
        self.assertNotIn("Stars", context)
        self.assertNotIn("热度", context)


if __name__ == "__main__":
    unittest.main()
