"""The sign-in page in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_eye_button_shows_and_hides_the_password(page, live_server):
    page.add_init_script(RECORDER)
    page.goto(f"{live_server}/login")
    expect(page.locator(".signin-logo img")).to_be_visible()
    field = page.locator("#password")
    eye = page.locator("[data-password-toggle='password']")
    expect(eye).to_be_visible()
    page.fill("#email", "nobody@example.com")  # both fields are required, or the form never submits
    field.fill("not a real password")
    eye.click()
    expect(field).to_have_attribute("type", "text")
    expect(eye).to_have_attribute("aria-pressed", "true")
    eye.click()
    expect(field).to_have_attribute("type", "password")
    eye.click()
    # Submitting hides it again first: a listener added after the page's own sees the field as it is sent.
    sent_as = page.evaluate(
        "() => new Promise(done => {"
        " const form = document.querySelector('.signin-form');"
        " form.addEventListener('submit', e => {"
        "  e.preventDefault(); done(document.querySelector('#password').type); });"
        " form.requestSubmit(); })"
    )
    assert sent_as == "password"
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
