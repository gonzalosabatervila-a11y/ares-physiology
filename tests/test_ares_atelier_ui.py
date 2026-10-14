"""ARES Atelier UI v2: regression checks for mobile journal shell, zero new dependencies."""
from __future__ import annotations


def test_shell_delivers_premium_lab_scripts_and_feedback(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'lang="es"' in html
    assert 'viewport-fit=cover' in html
    assert 'id="tabs"' in html
    assert 'id="ares-toast"' in html
    assert 'aria-live="polite"' in html
    assert '/static/lab_ui.js?v=atelier-ui-20261014' in html
    assert '/static/app.js?v=atelier-ui-20261014' in html
    assert '/static/app.css?v=atelier-ui-20261014' in html


def test_one_tap_home_and_diary_tabs_are_present(client):
    app = client.get("/static/app.js")
    lab = client.get("/static/lab_ui.js")
    assert app.status_code == lab.status_code == 200
    js, diary = app.text, lab.text
    assert "function homeQuickCapture" in js
    assert "data-lab-quick" in js and "data-lab-quick" in diary
    assert "syncMode === 'automatic'" in js
    assert 'aria-label="Registro rápido de acontecimientos"' in js
    assert "lab-section-tabs" in diary
    assert "#/laboratorio?ver=analisis" in diary
    assert "lab-diary-panel" in diary and "lab-analysis-panel" in diary
    assert "labToast(" in diary and "aria-label" in diary


def test_chart_and_navigation_use_atelier_palette_not_old_cyan(client):
    app = client.get("/static/app.js").text
    css = client.get("/static/app.css").text
    assert "69,212,229" not in app
    assert "69,212,229" not in css
    assert "#1f7f8b" not in css
    assert "--sig:#D9B782" in css
    assert "--sage:#A6BDA3" in css
    assert "lab-view-diary .lab-analysis-panel" in css
    assert "lab-view-analysis .lab-diary-panel" in css
    assert "env(safe-area-inset-bottom)" in css
    assert "@media (min-width:1180px)" in css


def test_lightweight_frontend_assets_remain_within_budget(client):
    """Uncompressed payload budget, NOT a measured render/network latency."""
    bounds = {
        "/static/app.js": 105_000,
        "/static/lab_ui.js": 25_000,
        "/static/app.css": 45_000,
    }
    for path, max_bytes in bounds.items():
        r = client.get(path)
        assert r.status_code == 200, path
        assert len(r.content) <= max_bytes, (
            f"{path} pesa {len(r.content)} bytes (límite: {max_bytes})"
        )


def test_ui_keeps_diagnostics_and_responds_to_out_of_order_requests(client):
    app = client.get("/static/app.js").text
    assert "else if (tab === 'lab')" in app
    assert "url = '/api/lab'; fn = renderLab" in app
    assert "seq !== routeSeq" in app
    assert "data-route-retry" in app
    assert "prefers-reduced-motion" in app
