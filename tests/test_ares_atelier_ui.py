"""ARES Atelier UI v2: regression checks for mobile journal shell, zero new dependencies."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ares.app.server import create_app


@pytest.fixture
def client(conn, settings):
    """Cliente HTTP de prueba aislado: DuckDB temporal y llave real bloqueada."""
    with TestClient(create_app(lambda: conn, settings)) as test_client:
        yield test_client



def test_shell_delivers_premium_lab_scripts_and_feedback(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'lang="es"' in html
    assert 'viewport-fit=cover' in html
    assert 'id="tabs"' in html
    assert 'id="ares-toast"' in html
    assert 'aria-live="polite"' in html
    assert '/static/lab_ui.js?v=ares-design-system-20261014' in html
    assert '/static/app.js?v=ares-design-system-20261014' in html
    assert '/static/app.css?v=ares-design-system-20261014' in html
    assert '/static/atelier_views.css?v=ares-design-system-20261014' in html


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
        "/static/atelier_views.css": 17_000,
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


def test_fisiologia_atelier_usa_tiempo_real_y_no_interpola_mediciones(client):
    js = client.get("/static/app.js").text
    css = client.get("/static/app.css").text
    assert "function renderFisiologia(d)" in js
    assert "Date.parse(p.date)" in js  # eje X = fecha, no índice del array
    assert "t-previous>86400000*1.5" in js  # interrumpe trazo por días ausentes
    assert "p.v===null||p.v===undefined" in js
    assert "PHYS_SERIES.set(id" in js
    assert "role=\"slider\"" in js
    assert "document.addEventListener('keydown',e=>" in js
    assert "function physCursor(svg, index)" in js
    assert ".phys-path" in css and ".phys-cursor-dot" in css


def test_fisiologia_prioriza_dos_senales_y_separa_modelo_whoop(client):
    js = client.get("/static/app.js").text
    assert "['hrv','rhr']" in js
    assert "phys-feature-grid" in js
    assert "phys-secondary-list" in js
    assert "MODELO · WHOOP" in js
    assert "m.key==='recovery'?'MODELO · WHOOP':'MED · WHOOP'" in js
    assert "Noches válidas / procesadas" in js
    assert "Calidad utilizable*" in js
    assert "Cambios estadísticos" not in js  # no atribuir un diagnóstico inexistente


def test_fisiologia_scientific_atelier_typographic_design(client):
    js = client.get("/static/app.js").text
    css = client.get("/static/app.css").text
    assert "function physNumber(value, unit)" in js
    assert 'class="phys-data"' in js
    assert "phys-record-count" in js and "phys-feature-grid" in js
    assert "font-variation-settings:'wdth' 74" in css
    assert "font-family:'Iowan Old Style'" in css
    assert ".phys-secondary{border:0" in css
    assert ".phys-overview{padding:" in css
    assert "ARES Fisiología / Scientific Atelier" in css
    assert "Fisiología · estudio longitudinal" not in css


def test_scientific_atelier_navigation_and_progressive_detail(client):
    js = client.get("/static/app.js").text
    css = client.get("/static/atelier_views.css").text
    assert "atelier-intro home-intro" in js
    assert 'class="atelier-extras"' in js
    assert "Explorar mediciones y fuentes" in js
    assert 'class="atelier-row-list workout-list"' in js
    assert "Entrenar. <em>Recuperar.</em>" in js
    assert "plan-day" in js and "plan-today" in js
    assert ".atelier-extras>summary" in css
    assert ".workout-list .workout-tile" in css
    assert ".plan-today::before" in css
    assert ".lab-cohort" in css and ".lab-capture" in css


def test_scientific_atelier_remains_data_neutral_and_mobile_accessible(client):
    js = client.get("/static/app.js").text
    css = client.get("/static/atelier_views.css").text
    shell = client.get("/").text
    assert "#/laboratorio" in js and "#/fisiologia" in js
    assert "renderPlanExecution(d.execution?.days?.[s.date],s)" in js
    assert "renderPlanPreview(d.plan_preview)" in js
    assert "nativeWhoop(d.whoop)" in js
    assert "pairedMetrics(d.fusion)" in js
    assert "lab-ui" not in shell  # no shadow/duplicate bundle
    assert "@media(max-width:370px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert ".lab-action:last-child" in css
    assert ".plan-exec-stats" in css
    assert "fetch(" not in css


def test_plan_weekdays_use_native_accessible_details(client):
    js=client.get("/static/app.js").text
    css=client.get("/static/atelier_views.css").text
    assert '<details class="plan-day' in js
    assert '<summary class="plan-day-summary">' in js
    assert "isToday?'open':''" in js
    assert 'renderPlanExecution(d.execution?.days?.[s.date],s)' in js
    assert 'function renderPlan(d)' in js
    assert ".plan-day-summary:focus-visible" in css
    assert ".plan-day[open] .plan-day-arrow" in css
