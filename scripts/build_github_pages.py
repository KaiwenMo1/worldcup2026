#!/usr/bin/env python3
"""Build the static GitHub Pages frontend for the hosted FastAPI backend."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"
DEFAULT_OUTPUT_DIR = ROOT / "site"


def _rewrite_common(html: str, *, static_prefix: str, home_href: str, arena_href: str, lab_href: str) -> str:
    return (
        html.replace('href="/static/', f'href="{static_prefix}')
        .replace('src="/static/', f'src="{static_prefix}')
        .replace('href="/"', f'href="{home_href}"')
        .replace('href="/arena"', f'href="{arena_href}"')
        .replace('href="/model-lab"', f'href="{lab_href}"')
        .replace('href="/dashboard"', f'href="{lab_href}"')
    )


def _write_page(source: Path, destination: Path, *, depth: int, current: str) -> None:
    prefix = "../" * depth
    static_prefix = f"{prefix}static/"
    home_href = f"{prefix}./" if depth else "./"
    arena_href = "./" if current == "arena" else f"{prefix}arena/"
    lab_href = "./" if current in {"model-lab", "dashboard"} else f"{prefix}model-lab/"
    html = _rewrite_common(
        source.read_text(encoding="utf-8"),
        static_prefix=static_prefix,
        home_href=home_href,
        arena_href=arena_href,
        lab_href=lab_href,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")


def build_site(output_dir: Path = DEFAULT_OUTPUT_DIR, api_base_url: str = "") -> Path:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    shutil.copytree(STATIC_DIR, output_dir / "static")

    api_base = api_base_url.strip().rstrip("/")
    (output_dir / "static" / "runtime-config.js").write_text(
        f"window.WC_API_BASE_URL = {json.dumps(api_base)};\n",
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    _write_page(STATIC_DIR / "ai.html", output_dir / "index.html", depth=0, current="home")
    _write_page(STATIC_DIR / "ai.html", output_dir / "ai" / "index.html", depth=1, current="home")
    _write_page(STATIC_DIR / "arena.html", output_dir / "arena" / "index.html", depth=1, current="arena")
    _write_page(STATIC_DIR / "index.html", output_dir / "model-lab" / "index.html", depth=1, current="model-lab")
    _write_page(STATIC_DIR / "index.html", output_dir / "dashboard" / "index.html", depth=1, current="dashboard")
    shutil.copyfile(output_dir / "index.html", output_dir / "404.html")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages static frontend.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("WC_API_BASE_URL") or os.getenv("PAGES_API_BASE_URL") or "",
        help="Hosted FastAPI base URL, for example https://worldcup2026-api.onrender.com",
    )
    args = parser.parse_args()
    output_dir = build_site(args.output_dir, args.api_base_url)
    print(f"Built GitHub Pages site at {output_dir}")


if __name__ == "__main__":
    main()
