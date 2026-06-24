from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_github_pages import build_site


class GitHubPagesBuildTests(unittest.TestCase):
    def test_static_site_rewrites_assets_routes_and_api_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = build_site(Path(tmp) / "site", "https://worldcup2026-api.example.com/")

            home = (output / "index.html").read_text(encoding="utf-8")
            arena = (output / "arena" / "index.html").read_text(encoding="utf-8")
            runtime = (output / "static" / "runtime-config.js").read_text(encoding="utf-8")

        self.assertIn('href="static/ai.css"', home)
        self.assertIn('href="arena/"', home)
        self.assertIn('href="../static/styles.css"', arena)
        self.assertIn('href="../model-lab/"', arena)
        self.assertIn('"https://worldcup2026-api.example.com"', runtime)


if __name__ == "__main__":
    unittest.main()
