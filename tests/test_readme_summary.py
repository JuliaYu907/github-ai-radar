import unittest

from github_trending import _compose_project_intro, _extract_summary, _repo_summary


class ReadmeSummaryTests(unittest.TestCase):
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
        }

        result = _repo_summary(repo, 1)

        self.assertEqual(result["description"], "Official GitHub About text.")
        self.assertEqual(result["about"], "Official GitHub About text.")
        self.assertIn("developer tool", result["readme_highlight"])
        self.assertEqual(result["intro_source"], "about+readme")


if __name__ == "__main__":
    unittest.main()
