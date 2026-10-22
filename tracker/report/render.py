"""Standalone report rendering: a self-contained HTML document, converted to PDF or PNG with headless Chromium."""

from __future__ import annotations

import os
from pathlib import Path

from flask import current_app, render_template
from playwright.sync_api import sync_playwright

from .build import Report

A4_PORTRAIT_WIDTH = 794  # CSS pixels at 96 dpi


def render_print_html(report: Report) -> str:
    """The report as one self-contained document: CSS inlined, charts embedded as data URIs, no scripts."""
    css = (Path(current_app.static_folder) / "tracker.css").read_text(encoding="utf-8")
    return render_template("report/print.html", report=report, css=css, chart_mime="image/svg+xml")


def _launch_args() -> list[str]:
    # Chromium refuses to start its sandbox as root (the Docker build step); a non-root user needs no flag.
    return ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []


def html_to_pdf(html: str) -> bytes:
    """Render ``html`` to an A4 PDF."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=_launch_args())
        try:
            page = browser.new_page(viewport={"width": A4_PORTRAIT_WIDTH, "height": 1123})
            page.set_content(html, wait_until="load")
            return page.pdf(format="A4", print_background=True)
        finally:
            browser.close()


def html_to_png(html: str, width: int = 1100) -> bytes:
    """Render ``html`` to a full-page PNG ``width`` CSS pixels wide."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=_launch_args())
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.set_content(html, wait_until="load")
            return page.screenshot(full_page=True, type="png")
        finally:
            browser.close()
