from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.research_tools import (
    build_agent_reach_research_tasks,
    build_manager_evidence_template_row,
    collect_public_evidence,
    detect_research_tools,
    import_agent_reach_markdown,
    extract_markdown_from_html,
    research_tool_catalog,
    research_tool_summary,
    write_agent_reach_plan,
    write_research_documents,
)


class ResearchToolRegistryTests(unittest.TestCase):
    def test_catalog_includes_recommended_optional_tools(self) -> None:
        tool_ids = {tool.tool_id for tool in research_tool_catalog()}

        self.assertTrue({"agent_reach", "crawl4ai", "markitdown", "docling", "pydantic_ai", "fastmcp"}.issubset(tool_ids))

    def test_detection_is_non_throwing_without_optional_dependencies(self) -> None:
        detections = detect_research_tools()
        summary = research_tool_summary()

        self.assertEqual(len(detections), 6)
        self.assertIn("runtime_policy", summary)


class FootballResearchScoutTests(unittest.TestCase):
    def test_html_extraction_keeps_readable_tactical_content(self) -> None:
        title, markdown = extract_markdown_from_html(
            """
            <html><head><title>France Pressing Notes</title><script>bad()</script></head>
            <body><h1>Ignored if title exists</h1><h2>Build Up</h2>
            <p>France formed a spare first line and attacked transitions quickly.</p>
            <ul><li>Fullbacks held conservative positions.</li></ul></body></html>
            """
        )

        self.assertEqual(title, "France Pressing Notes")
        self.assertIn("## Build Up", markdown)
        self.assertIn("spare first line", markdown)
        self.assertNotIn("bad()", markdown)

    def test_collect_and_write_public_evidence_from_html(self) -> None:
        result = collect_public_evidence(
            html="<h1>Brazil Match Report</h1><p>Brazil created overloads on the right side.</p>",
            manager_id="brazil_manager",
            team="Brazil",
            category="tactical_reports",
        )

        self.assertTrue(result.ok)
        document = result.documents[0]
        self.assertEqual(document.team, "Brazil")
        self.assertEqual(document.category, "tactical_reports")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            issues = write_research_documents(
                result.documents,
                output_dir=root / "docs",
                index_path=root / "index.csv",
            )

            self.assertFalse(issues)
            self.assertTrue((root / "docs" / f"{document.evidence_id}.md").exists())
            self.assertIn(document.evidence_id, (root / "index.csv").read_text(encoding="utf-8"))

    def test_manager_evidence_template_requires_human_review(self) -> None:
        document = collect_public_evidence(
            html="<h1>England Notes</h1><p>England pressed selectively.</p>",
            manager_id="england_tuchel",
            team="England",
        ).documents[0]

        row = build_manager_evidence_template_row(document)

        self.assertEqual(row["manager_id"], "england_tuchel")
        self.assertEqual(row["reviewed_by_human"], "false")
        self.assertEqual(row["claim_text"], "")


class AgentReachWorkflowTests(unittest.TestCase):
    def test_manager_research_plan_is_specific_and_social_is_opt_in(self) -> None:
        tasks = build_agent_reach_research_tasks(team="France")
        social_tasks = build_agent_reach_research_tasks(team="France", include_social=True)

        self.assertTrue(tasks)
        self.assertTrue(all(task.team == "France" for task in tasks))
        self.assertFalse(any(task.requires_login for task in tasks))
        self.assertTrue(any(task.requires_login for task in social_tasks))
        self.assertIn("manager_id:", tasks[0].agent_prompt)
        self.assertIn("Do not invent tactical claims", tasks[0].agent_prompt)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.csv"
            issues = write_agent_reach_plan(tasks[:2], path)

            self.assertFalse(issues)
            self.assertIn("agent_prompt", path.read_text(encoding="utf-8"))

    def test_import_agent_reach_markdown_creates_review_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            (inbox / "france_note.md").write_text(
                "\n".join(
                    [
                        "manager_id: france_deschamps",
                        "manager_name: Didier Deschamps",
                        "team: France",
                        "category: tactical_reports",
                        "source_url: https://example.com/france",
                        "source_title: France tactical analysis",
                        "source_channel: web_tactical_reports",
                        "",
                        "# France tactical analysis",
                        "France attacked transitions quickly after regains.",
                    ]
                ),
                encoding="utf-8",
            )

            result = import_agent_reach_markdown(
                inbox,
                output_dir=root / "evidence",
                index_path=root / "index.csv",
                review_queue_path=root / "queue.csv",
            )

            self.assertTrue(result.ok)
            self.assertEqual(len(result.documents), 1)
            self.assertEqual(result.documents[0].source_tool, "agent_reach_web_tactical_reports")
            self.assertEqual(result.review_rows[0]["reviewed_by_human"], "false")
            self.assertEqual(result.review_rows[0]["claim_text"], "")
            self.assertIn(result.documents[0].evidence_id, (root / "queue.csv").read_text(encoding="utf-8"))

    def test_import_missing_agent_reach_inbox_is_warning_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = import_agent_reach_markdown(Path(directory) / "missing")

        self.assertEqual(result.documents, [])
        self.assertTrue(result.issues)
        self.assertEqual(result.issues[0].severity.value, "warning")


if __name__ == "__main__":
    unittest.main()
