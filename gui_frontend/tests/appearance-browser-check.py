"""QA opt-in del frontend compilado, SIN backend real ni procesos BDS.

Requiere Playwright Python + Chrome local (no es parte del runner Vitest).
Ejecutar después de npm run build:
    python gui_frontend/tests/appearance-browser-check.py
API y WebSocket se interceptan en el navegador con datos ficticios.
Las evidencias se escriben fuera del repositorio, en Temp/opencode.
"""
from __future__ import annotations

import base64
import functools
import json
import os
from pathlib import Path
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Temp" / "opencode" / "bedrock-hierarchy-qa"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class Fixtures:
    def __init__(self):
        self.mutations = []
        self.sockets = []
        self.setup_required = False
        self.setup_error = False
        self.addons_error = False
        self.auto_init = True
        self.reply_pings = True
        self.defer_verify = False
        self.verify_routes = []
        self.status = {
            "running": True, "players": ["Alex", "Steve"], "player_count": 2,
            "backup_in_progress": False, "update_in_progress": False, "uptime": 3723,
            "installed_version": "1.21.100.6", "last_backup": "2026-10-12 19:00",
            "hardware": {"ram_mb": 428.5, "ram_pct": 12, "cpu_pct": 7.2, "total_ram_gb": 16,
                         "system_available_gb": 10.4, "disk_free_gb": 210.2,
                         "disk_total_gb": 930, "disk_used_pct": 77.4},
        }

    def ws(self, socket):
        self.sockets.append(socket)
        if self.auto_init:
            self.send_init(socket)
        else:
            socket.send(json.dumps({"type": "log", "data": {
                "id": f"qa-socket-{len(self.sockets)}", "time": "19:00:10",
                "text": "QA esperando init", "type": "system"
            }}))
        socket.on_message(lambda raw: socket.send('{"type":"pong"}')
                          if self.reply_pings and json.loads(raw).get("type") == "ping" else None)

    def send_init(self, socket):
        socket.send(json.dumps({"type": "init", "status": self.status, "logs": [
            {"id": 1, "time": "19:00:01", "text": "Servidor de prueba iniciado", "type": "system"},
            {"id": 2, "time": "19:00:04", "text": "Player connected: Alex", "type": "join"},
            {"id": 3, "time": "19:00:07", "text": "Backup de prueba terminado", "type": "backup"},
            {"id": 4, "time": "19:00:09", "text": "Aviso de prueba", "type": "error"},
        ]}))

    def api(self, route):
        path = urlsplit(route.request.url).path
        code = 200
        if route.request.method == "POST":
            self.mutations.append({"path": path, "body": route.request.post_data})
            if path.startswith("/api/backups/") and path.endswith("/verify") and self.defer_verify:
                self.verify_routes.append(route)
                return
            data = {"status": "ok"}
        elif path == "/api/setup_status":
            data = {"required": self.setup_required, "bds_installed": True}
            if self.setup_error:
                code, data = 503, {"detail": "Fallo de prueba"}
        elif path == "/api/suite_update":
            data = {"state": "no_release", "has_update": False, "current_version": "2.1.0", "progress": {"phase": "idle"}}
        elif path == "/api/suite_update/progress":
            data = {"phase": "idle"}
        elif path == "/api/connectivity":
            data = {"lan_ip": "192.168.1.20", "public_ip": "198.51.100.44", "port": "19132"}
        elif path == "/api/backups":
            data = {"backups": [{"filename": f"auto_backup_demo_manual_20261012_{i}.zip",
                                 "date": f"2026-10-12 {19-i:02}:00:00", "size_mb": 24.6 + i} for i in range(3)]}
        elif path == "/api/players":
            data = {"allow_list_enabled": True, "known": [
                {"name": name, "permission": "operator" if i == 0 else "member", "online": True,
                 "allowlisted": True, "last_seen": "2026-10-12 19:00"} for i, name in enumerate(["Alex", "Steve"])]}
        elif path == "/api/history/metrics":
            data = {"points": [{"ram_pct": 10 + i % 8, "cpu_pct": 3 + i % 12, "disk_used_pct": 76 + i / 100} for i in range(60)]}
        elif path == "/api/history/sessions":
            data = {"totals": [{"player": "Alex", "total_sec": 7200}, {"player": "Steve", "total_sec": 5400}]}
        elif path == "/api/server_properties":
            data = {"server_running": True, "fields": {"server-name": "Mundo de prueba", "gamemode": "survival",
                    "difficulty": "normal", "server-port": "19132", "max-players": "10", "allow-list": "true"}}
        elif path == "/api/schedule":
            data = {"backup_interval_min": 30, "backup_only_with_players": True, "auto_restart_on_crash": False,
                    "daily_backup_time": "03:00", "daily_restart_time": None}
        elif path == "/api/check_update":
            data = {"has_update": True, "current_version": "1.21.100.6", "latest_version": "1.21.110.2",
                    "has_previous": True, "previous_version": "1.21.90.3"}
        elif path == "/api/addons":
            data = json.loads((ROOT.parent / "tests" / "fixtures" / "addons_payload.json").read_text(encoding="utf-8"))
            for pack in data["packs"]:
                for key in ["modules", "pack_dependencies", "script_dependencies", "referenced_by_worlds"]:
                    pack.setdefault(key, [])
                pack.setdefault("name", pack["id"].split("/")[-1])
                pack.setdefault("folder", pack["id"].split("/")[-1])
            for diagnostic in data["diagnostics"]:
                for key, value in {"message_es": "Diagnóstico de prueba", "message_en": "Test diagnostic",
                                   "source_file": "manifest.json", "source": "QA", "determined": True}.items():
                    diagnostic.setdefault(key, value)
            if self.addons_error:
                code, data = 500, {"detail": "Inventario no disponible (QA)"}
        else:
            raise AssertionError(f"API no prevista en QA: {path}")
        route.fulfill(status=code, content_type="application/json", body=json.dumps(data))


def screenshot(page, name):
    # Esperar un estado observable, no capturar a mitad de una transición.
    page.wait_for_function("""() => [...document.querySelectorAll('.dialog,.modal-backdrop,.glass-menu')]
      .filter(el => el.getClientRects().length).every(el => Number(getComputedStyle(el).opacity) > .995)""")
    page.screenshot(path=str(OUT / name))


def range_value(page, name, value, key="transparency"):
    page.get_by_label(name, exact=True).evaluate("""(input, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
      input.dispatchEvent(new Event('input', {bubbles: true}));
    }""", value)
    page.wait_for_function("([key,value]) => JSON.parse(localStorage.getItem('bedrock-appearance'))[key] === value", arg=[key, value])


def open_appearance(page, english=False):
    page.get_by_role("button", name="Customize" if english else "Personalizar", exact=True).click()


def check_console_visible(page):
    # Sin desplazar la página: logs y entrada completos dentro del área útil,
    # por encima del dock. No basta con que existan en el DOM.
    page.locator(".main-content").evaluate("el => { el.scrollTop = 0 }")
    page.wait_for_function("""() => {
      const main = document.querySelector('.main-content').getBoundingClientRect();
      const log = document.querySelector('.terminal-log').getBoundingClientRect();
      const form = document.querySelector('.console-form').getBoundingClientRect();
      return log.top >= main.top && log.height >= 100 && form.bottom <= main.bottom && form.top >= main.top;
    }""")


def check_connection(page, fake):
    before = len(fake.mutations)
    previous_sockets = len(fake.sockets)
    expect(page.locator(".server-latency")).to_be_visible()
    fake.auto_init = False
    fake.reply_pings = False
    fake.sockets[-1].close(code=1011, reason="QA disconnect")
    expect(page.locator(".status-label")).to_have_text("Reconectando GUI…")
    expect(page).to_have_title(re.compile("Reconectando GUI"))
    expect(page.locator(".server-latency")).to_have_count(0)
    expect(page.locator(".server-uptime")).to_have_count(0)
    # No confundir pérdida del canal con apagado de BDS ni enviar un stop.
    expect(page.get_by_role("button", name="Iniciar", exact=True)).to_be_disabled()
    page.get_by_role("button", name="EN", exact=True).click()
    expect(page.locator(".status-label")).to_have_text("Reconnecting GUI…")
    page.get_by_role("button", name="ES", exact=True).click()
    screenshot(page, "connection-reconnecting.png")
    expect(page.get_by_role("log")).to_contain_text("QA esperando init")
    assert len(fake.sockets) == previous_sockets + 1
    # El transporte ya abrió, pero todavía no hay un estado nuevo.
    expect(page.locator(".status-badge")).to_have_attribute("data-connection", "reconnecting")
    fake.status["uptime"] = 42
    fake.send_init(fake.sockets[-1])
    expect(page.locator(".status-label")).to_have_text("En línea")
    expect(page.locator(".server-uptime")).to_have_text("00m 42s")
    expect(page.locator(".server-latency")).to_have_count(0)
    fake.reply_pings = True
    fake.auto_init = True
    fake.sockets[-1].send('{"type":"pong"}')
    expect(page.locator(".server-latency")).to_be_visible()
    fake.status.update(running=False, uptime=0)
    fake.sockets[-1].send(json.dumps({"type": "status", "data": fake.status}))
    expect(page.locator(".status-label")).to_have_text("Detenido")
    expect(page).to_have_title("Servidor • Apagado")
    expect(page.get_by_role("button", name="Iniciar", exact=True)).to_be_enabled()
    fake.status.update(running=True, uptime=3723)
    fake.sockets[-1].send(json.dumps({"type": "status", "data": fake.status}))
    expect(page.locator(".status-label")).to_have_text("En línea")
    assert len(fake.mutations) == before


def check_action_menus(page, fake):
    before = len(fake.mutations)
    quick = page.get_by_role("button", name="Comandos rápidos", exact=True)
    menu = page.get_by_role("menu", name="Comandos rápidos", exact=True)
    day = menu.get_by_role("menuitem", name=re.compile("^Hacer de día"))
    night = menu.get_by_role("menuitem", name=re.compile("^Hacer de noche"))
    coords = menu.get_by_role("menuitem", name=re.compile("^Mostrar coordenadas"))
    quick.focus(); quick.press("Enter")
    expect(quick).to_have_attribute("aria-expanded", "true")
    expect(day).to_be_focused()
    page.locator(".main-content").dispatch_event("scroll")
    expect(day).to_be_focused()
    for key, item in [("ArrowDown", night), ("Home", day), ("ArrowUp", coords),
                      ("ArrowDown", day), ("End", coords)]:
        page.keyboard.press(key)
        expect(item).to_be_focused()
    screenshot(page, "quick-menu-keyboard.png")
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(quick).to_be_focused()
    quick.press("Enter"); page.keyboard.press("Tab")
    expect(menu).to_have_count(0)
    expect(page.get_by_role("button", name="Enviar", exact=True)).to_be_focused()
    quick.focus(); quick.press("Enter"); page.keyboard.press("Shift+Tab")
    expect(menu).to_have_count(0)
    expect(page.get_by_role("textbox", name="Enviar", exact=True)).to_be_focused()
    quick.focus(); quick.press("Enter")
    page.get_by_role("textbox", name="Buscar en logs…", exact=True).focus()
    expect(menu).to_have_count(0)
    assert len(fake.mutations) == before
    # Solo Enter sobre una opción ejecuta; abrir/navegar/cerrar no lo hace.
    quick.focus(); quick.press("Enter")
    menu.get_by_role("menuitem", name=re.compile("^Listar jugadores")).focus()
    page.keyboard.press("Enter")
    expect(menu).to_have_count(0)
    expect(quick).to_be_focused()
    assert len(fake.mutations) == before + 1
    assert fake.mutations[-1]["path"] == "/api/command"
    assert json.loads(fake.mutations[-1]["body"]) == {"command": "list"}

    page.get_by_role("tab", name="Backups", exact=True).click()
    triggers = page.locator("[data-menu-trigger]")
    backup = triggers.nth(1)
    menu = page.get_by_role("menu", name="Acciones", exact=True)
    download = menu.get_by_role("menuitem", name="Descargar", exact=True)
    verify = menu.get_by_role("menuitem", name="Verificar integridad", exact=True)
    delete = menu.get_by_role("menuitem", name="Eliminar", exact=True)
    backup.focus(); backup.press("Enter")
    expect(download).to_be_focused()
    for key, item in [("ArrowDown", verify), ("Home", download), ("ArrowUp", delete),
                      ("ArrowDown", download), ("End", delete)]:
        page.keyboard.press(key)
        expect(item).to_be_focused()
    screenshot(page, "backup-menu-keyboard.png")
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(backup).to_be_focused()
    backup.press("Enter"); page.keyboard.press("Tab")
    expect(menu).to_have_count(0)
    expect(triggers.nth(2)).to_be_focused()
    backup.focus(); backup.press("Enter"); page.keyboard.press("Shift+Tab")
    expect(menu).to_have_count(0)
    expect(triggers.first).to_be_focused()
    backup.focus(); backup.press("Enter"); page.keyboard.press("End"); page.keyboard.press("Enter")
    expect(page.get_by_role("dialog", name="¿Eliminar este backup?", exact=True)).to_be_visible()
    page.get_by_role("button", name="Cancelar", exact=True).click()
    expect(backup).to_be_focused()
    assert len(fake.mutations) == before + 1

    # Una opción ocupada se omite al usar flechas; verificar sí conserva
    # su POST y nunca dispara restauración/eliminación accidentalmente.
    fake.defer_verify = True
    backup.press("Enter"); page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
    expect(menu).to_have_count(0)
    expect(backup).to_be_focused()
    backup.press("Enter")
    expect(verify).to_be_disabled()
    expect(download).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="Reestablecer", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(backup).to_be_focused()
    assert len(fake.mutations) == before + 2
    assert fake.mutations[-1]["path"].endswith("/verify")
    fake.verify_routes.pop().fulfill(status=200, content_type="application/json", body='{"status":"ok"}')
    fake.defer_verify = False
    page.get_by_role("tab", name="Servidor", exact=True).click()


def check_initial_connection(browser, url, errors):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    fake = Fixtures()
    fake.auto_init = False
    context.route("**/api/**", fake.api)
    context.route_web_socket(re.compile(r"ws://127\.0\.0\.1:\d+/ws.*"), fake.ws)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url)
        expect(page.get_by_role("log")).to_contain_text("QA esperando init")
        expect(page.locator(".status-label")).to_have_text("Conectando GUI…")
        # Capturar la instancia ya creada: route_web_socket instala su propio
        # constructor, por lo que envolver WebSocket en init_script sería frágil.
        cdp = context.new_cdp_session(page)
        prototype = cdp.send("Runtime.evaluate", {"expression": "WebSocket.prototype"})["result"]["objectId"]
        sockets = cdp.send("Runtime.queryObjects", {"prototypeObjectId": prototype})["objects"]["objectId"]
        cdp.send("Runtime.callFunctionOn", {"objectId": sockets,
                 "functionDeclaration": "function() { window.__qaSockets = Array.from(this); }"})
        cdp.send("Runtime.releaseObject", {"objectId": sockets})
        cdp.send("Runtime.releaseObject", {"objectId": prototype})
        cdp.detach()
        assert page.evaluate("window.__qaSockets.length") == 1
        screenshot(page, "connection-initial.png")
        fake.sockets[-1].send('{"type":"init","logs":[]}')
        expect(page.locator(".status-badge")).to_have_attribute("data-connection", "connecting")
        # Ni un pong ni un init sin status confirman que BDS esté encendido.
        fake.sockets[-1].send('{"type":"pong"}')
        expect(page.locator(".status-label")).to_have_text("Conectando GUI…")
        expect(page.locator(".server-latency")).to_have_count(0)
        fake.status["running"] = False
        fake.sockets[-1].send(json.dumps({"type": "status", "data": fake.status}))
        expect(page.locator(".status-label")).to_have_text("Detenido")
        page.evaluate("window.__qaSockets[0].dispatchEvent(new Event('error'))")
        expect(page.locator(".status-label")).to_have_text("Reconectando GUI…")
        fake.sockets[-1].close(code=1011, reason="QA error then close")
        expect(page.get_by_role("log")).to_contain_text("QA esperando init")
        assert len(fake.sockets) == 2
        fake.status["running"] = True
        fake.send_init(fake.sockets[-1])
        expect(page.locator(".status-label")).to_have_text("En línea")
        page.evaluate("""() => {
          const old = window.__qaSockets[0];
          old.dispatchEvent(new Event('error'));
          old.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({
            type: 'status', data: { running: false, players: [], player_count: 0 }
          }) }));
          old.dispatchEvent(new Event('close'));
        }""")
        expect(page.locator(".status-label")).to_have_text("En línea")
        expect(page.locator(".status-badge")).to_have_attribute("data-connection", "connected")
        assert not fake.mutations
    finally:
        context.close()


def check_small_viewport_menus(browser, url, errors):
    # Reflujo equivalente a 1280×800 al 200 % y móvil con menor altura útil.
    # No es zoom nativo de Chrome ni un teclado virtual en un teléfono real.
    for name, options in [
        ("reflow-200", {"viewport": {"width": 640, "height": 400}, "device_scale_factor": 2}),
        ("mobile-short", {"viewport": {"width": 320, "height": 440}, "is_mobile": True, "has_touch": True}),
    ]:
        context = browser.new_context(**options)
        fake = Fixtures()
        context.route("**/api/**", fake.api)
        context.route_web_socket(re.compile(r"ws://127\.0\.0\.1:\d+/ws.*"), fake.ws)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(url)
            expect(page.get_by_role("tab", name="Servidor", exact=True)).to_be_visible()
            # El consejo inicial ocupa parte de esta ventana tan corta.
            # Descartarlo antes de ejercitar los menús, como en el uso normal.
            if page.get_by_role("note").count():
                page.get_by_role("button", name="Descartar consejo", exact=True).click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            for kind in ["quick", "backup", "nav"]:
                if kind == "quick":
                    trigger = page.get_by_role("button", name="Comandos rápidos", exact=True)
                    menu = page.get_by_role("menu", name="Comandos rápidos", exact=True)
                elif kind == "backup":
                    page.get_by_role("tab", name="Backups", exact=True).click()
                    trigger = page.locator("[data-menu-trigger]").nth(1)
                    menu = page.get_by_role("menu", name="Acciones", exact=True)
                else:
                    trigger = page.get_by_role("button", name="Más acciones", exact=True)
                    menu = page.get_by_role("menu", name="Más acciones", exact=True)
                trigger.click()
                page.keyboard.press("End")
                expect(menu.get_by_role("menuitem").last).to_be_focused()
                expect(menu.get_by_role("menuitem").last).to_be_in_viewport()
                screenshot(page, f"{name}-{kind}-menu.png")
                assert menu.evaluate("""el => {
                  const r = el.getBoundingClientRect();
                  return r.top >= 0 && r.left >= 0 && r.right <= innerWidth && r.bottom <= innerHeight;
                }""")
                page.keyboard.press("Escape")
                expect(menu).to_have_count(0)
                expect(trigger).to_be_focused()
            assert not fake.mutations
        finally:
            context.close()


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(ROOT / "dist")))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    errors, results = [], {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            fake = Fixtures()
            context.route("**/api/**", fake.api)
            context.route_web_socket(re.compile(r"ws://127\.0\.0\.1:\d+/ws.*"), fake.ws)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.get_by_role("tab", name="Servidor", exact=True)).to_be_visible()
            expect(page.locator(".controls-context")).to_contain_text("2 jugadores")
            page.wait_for_function("['ready','fallback','reduced'].includes(document.querySelector('.app-shell').dataset.glass)")
            results["glass"] = page.locator(".app-shell").get_attribute("data-glass")
            page.evaluate("document.fonts.ready")
            assert page.evaluate("document.fonts.check('14px Inter') && document.fonts.check('12px \\\"JetBrains Mono\\\"')")
            screenshot(page, "desktop-dark.png")
            for width, height in [(1440, 1000), (1280, 800), (1024, 768)]:
                page.set_viewport_size({"width": width, "height": height})
                check_console_visible(page)
                screenshot(page, f"console-{width}x{height}.png")
            page.set_viewport_size({"width": 1440, "height": 1000})
            assert page.locator(".status-badge").count() == 1
            expect(page.get_by_role("button", name="Configuración", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="Apariencia", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Iniciar", exact=True)).to_be_disabled()
            fake.status.update(running=False, players=[], player_count=0)
            fake.sockets[-1].send(json.dumps({"type": "status", "data": fake.status}))
            expect(page.get_by_role("button", name="Iniciar", exact=True)).to_be_enabled()
            expect(page.locator(".control-start")).to_have_css("background-color", "rgb(183, 243, 250)")
            expect(page.get_by_role("button", name="Detener", exact=True)).to_be_disabled()
            screenshot(page, "server-stopped.png")
            fake.status.update(running=True, players=["Alex", "Steve"], player_count=2)
            fake.sockets[-1].send(json.dumps({"type": "status", "data": fake.status}))
            expect(page.get_by_role("button", name="Detener", exact=True)).to_be_enabled()
            results["hierarchy_command_visible_desktop"] = "passed"
            check_connection(page, fake)
            results["websocket_disconnect_resync_latency_i18n"] = "passed"
            check_action_menus(page, fake)
            results["quick_backup_menus_keyboard_focus_disabled_no_accidental_actions"] = "passed"

            # Consola conserva su entrada e historial al navegar.
            page.get_by_role("textbox", name="Enviar", exact=True).fill("list")
            page.get_by_role("tab", name="Jugadores", exact=True).click()
            expect(page.get_by_text("Jugadores Conocidos", exact=True)).to_be_visible()
            screenshot(page, "players.png")
            page.get_by_role("tab", name="Backups", exact=True).click()
            expect(page.get_by_text("Historial de Backups", exact=True)).to_be_visible()
            screenshot(page, "backups.png")
            page.get_by_role("tab", name="Addons", exact=True).click()
            expect(page.get_by_text("Compartido BP", exact=True)).to_be_visible()
            screenshot(page, "addons.png")
            page.get_by_role("combobox", name="Mundo", exact=True).click()
            page.get_by_role("option", name="Beta", exact=True).click()
            expect(page.get_by_text("Alfa BP", exact=True)).not_to_be_visible()
            page.get_by_role("combobox", name="Tipo", exact=True).click()
            page.get_by_role("option", name="Recursos", exact=True).click()
            expect(page.get_by_text("Compartido Res", exact=True)).to_be_visible()
            expect(page.get_by_text("Beta BP", exact=True)).not_to_be_visible()
            page.get_by_role("tab", name="Servidor", exact=True).click()
            expect(page.get_by_role("textbox", name="Enviar", exact=True)).to_have_value("list")
            page.get_by_role("tab", name="Addons", exact=True).click()
            expect(page.get_by_role("combobox", name="Mundo", exact=True)).to_have_text("Beta")
            expect(page.get_by_role("combobox", name="Tipo", exact=True)).to_have_text("Recursos")
            page.get_by_role("tab", name="Servidor", exact=True).click()
            page.get_by_role("button", name="Enviar", exact=True).click()
            assert any(item["path"] == "/api/command" for item in fake.mutations)
            page.get_by_role("textbox", name="Enviar", exact=True).press("ArrowUp")
            expect(page.get_by_role("textbox", name="Enviar", exact=True)).to_have_value("list")
            page.get_by_role("button", name="Errores", exact=True).click()
            expect(page.get_by_role("log")).to_contain_text("Aviso de prueba")
            expect(page.get_by_role("log")).not_to_contain_text("Player connected")
            page.get_by_role("button", name="Todos", exact=True).click()
            results["navigation_console"] = "passed"

            # Una confirmación no envía la acción si el usuario la cancela.
            before = len(fake.mutations)
            page.get_by_role("button", name="Detener", exact=True).click()
            expect(page.get_by_role("dialog", name="¿Detener el servidor?", exact=True)).to_be_visible()
            page.get_by_role("button", name="Cancelar", exact=True).click()
            assert len(fake.mutations) == before
            page.get_by_role("button", name="Reiniciar", exact=True).click()
            expect(page.get_by_role("dialog", name="¿Reiniciar el servidor?", exact=True)).to_be_visible()
            page.get_by_role("button", name="Cancelar", exact=True).click()
            assert len(fake.mutations) == before
            for action, title in [("Configuración", "Configuración del Servidor"), ("Programación", "Programación"),
                                  ("Actualización BDS", "Actualizador de BDS (Descarga Oficial de Mojang)")]:
                if action == "Configuración":
                    page.get_by_role("button", name=action, exact=True).click()
                else:
                    page.get_by_role("button", name="Más acciones", exact=True).click()
                    page.get_by_role("menuitem", name=action, exact=True).click()
                expect(page.get_by_role("dialog")).to_be_visible()
                assert page.get_by_role("dialog").evaluate("el => el.scrollWidth <= el.clientWidth")
                screenshot(page, f"modal-{action.split()[0]}.png")
                page.get_by_role("button", name="Cerrar", exact=True).click()
                expect(page.get_by_role("button", name="Configuración" if action == "Configuración" else "Más acciones", exact=True)).to_be_focused()
            results["confirmations_modals"] = "passed"
            page.get_by_role("button", name="Más acciones", exact=True).click()
            expect(page.get_by_role("menuitem", name="Programación", exact=True)).to_be_focused()
            page.keyboard.press("End")
            expect(page.get_by_role("menuitem", name="Acerca de", exact=True)).to_be_focused()
            screenshot(page, "secondary-menu.png")
            page.keyboard.press("Escape")
            expect(page.get_by_role("button", name="Más acciones", exact=True)).to_be_focused()
            results["settings_direct_secondary_menu_keyboard"] = "passed"

            open_appearance(page)
            page.keyboard.press("Shift+Tab")
            expect(page.get_by_role("button", name="Listo", exact=True)).to_be_focused()
            screenshot(page, "appearance.png")
            for transparency in [0, 80, 100]:
                range_value(page, "Transparencia del vidrio", transparency)
                assert page.locator(".appearance-dialog h2").evaluate("el => getComputedStyle(el).opacity") == "1"
            for name, key, value in [("Zoom", "zoom", 25), ("Zoom", "zoom", 180),
                                     ("Encuadre horizontal", "x", 0), ("Encuadre vertical", "y", 100),
                                     ("Oscurecimiento", "darkShade", 0)]:
                range_value(page, name, value, key)
            # Cambiar efectos y tema con el combobox real, por teclado.
            page.get_by_role("combobox", name="Efectos", exact=True).focus()
            page.keyboard.press("End"); page.keyboard.press("Enter")
            page.wait_for_function("document.documentElement.dataset.effects === 'reduced'")
            page.get_by_role("combobox", name="Tema", exact=True).focus()
            page.keyboard.press("End"); page.keyboard.press("Enter")
            page.wait_for_function("document.documentElement.dataset.theme === 'light'")
            screenshot(page, "appearance-light.png")
            page.get_by_role("button", name="Listo", exact=True).click()
            screenshot(page, "desktop-light.png")
            page.reload()
            page.wait_for_function("document.documentElement.dataset.theme === 'light' && document.documentElement.dataset.effects === 'reduced'")
            results["themes_transparency_persistence"] = "passed"

            # Subida real desde el input, IndexedDB, recarga y restablecimiento.
            image = page.evaluate("""() => { const c=document.createElement('canvas'); c.width=1600; c.height=900;
              const ctx=c.getContext('2d'), g=ctx.createLinearGradient(0,0,1600,900);
              g.addColorStop(0,'#fdfdfd'); g.addColorStop(.5,'#91bcca'); g.addColorStop(1,'#132138');
              ctx.fillStyle=g; ctx.fillRect(0,0,1600,900); return c.toDataURL('image/png').split(',')[1]; }""")
            wallpaper = OUT / "wallpaper.png"
            wallpaper.write_bytes(base64.b64decode(image))
            open_appearance(page)
            page.locator("#background-file").set_input_files(str(wallpaper))
            expect(page.get_by_text("Fondo guardado en este navegador.", exact=True)).to_be_visible()
            expect(page.locator(".appearance-preview img")).to_be_visible()
            page.get_by_role("button", name="Libre", exact=True).click()
            page.get_by_role("button", name="Listo", exact=True).click()
            page.reload()
            open_appearance(page)
            expect(page.locator(".appearance-preview img")).to_be_visible()
            screenshot(page, "custom-wallpaper.png")
            page.locator("#background-file").set_input_files({"name": "unsafe.svg", "mimeType": "image/svg+xml", "buffer": b"<svg/>"})
            expect(page.get_by_text("Elige una imagen JPEG, PNG o WebP.", exact=True)).to_be_visible()
            page.get_by_role("button", name="Restablecer fondo", exact=True).click()
            expect(page.locator(".appearance-preview img")).to_have_count(0)
            page.get_by_role("button", name="Listo", exact=True).click()
            results["wallpaper_upload_reload_reset_validation"] = "passed"

            page.get_by_role("button", name="EN", exact=True).click()
            expect(page.get_by_role("tab", name="Server", exact=True)).to_be_visible()
            open_appearance(page, english=True)
            expect(page.get_by_role("slider", name="Glass transparency", exact=True)).to_be_visible()
            page.get_by_role("button", name="Done", exact=True).click()
            page.get_by_role("button", name="ES", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_role("tab", name="Servidor", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            screenshot(page, "mobile-light.png")
            open_appearance(page)
            expect(page.get_by_role("button", name="Listo", exact=True)).to_be_in_viewport()
            screenshot(page, "mobile-appearance.png")
            page.get_by_role("button", name="Listo", exact=True).click()
            page.get_by_role("tab", name="Servidor", exact=True).focus()
            page.keyboard.press("ArrowRight")
            expect(page.get_by_role("tab", name="Jugadores", exact=True)).to_be_focused()
            open_appearance(page)
            page.get_by_role("button", name="Listo", exact=True).focus()
            page.keyboard.press("Tab")
            expect(page.get_by_role("dialog").get_by_role("button", name="Cerrar", exact=True)).to_be_focused()
            page.keyboard.press("Escape")
            expect(page.get_by_role("button", name="Personalizar", exact=True)).to_be_focused()
            page.set_viewport_size({"width": 320, "height": 720})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            results["i18n_mobile_keyboard"] = "passed"

            fake.setup_required = True
            page.reload()
            expect(page.locator(".setup-panel")).to_be_visible()
            screenshot(page, "wizard.png")
            fake.setup_error = True
            page.reload()
            expect(page.get_by_role("button", name="Reintentar", exact=True)).to_be_visible()
            results["wizard_loading_error"] = "passed"

            reduced = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            reduced_fake = Fixtures()
            reduced.route("**/api/**", reduced_fake.api)
            reduced.route_web_socket(re.compile(r"ws://127\.0\.0\.1:\d+/ws.*"), reduced_fake.ws)
            reduced_page = reduced.new_page()
            reduced_page.on("pageerror", lambda error: errors.append(str(error)))
            reduced_page.goto(url)
            reduced_page.wait_for_function("document.querySelector('.app-shell').dataset.glass === 'reduced'")
            assert reduced_page.locator(".glass-surface canvas").count() == 0
            results["system_reduced_motion"] = "passed"
            reduced.close()
            fallback_browser = pw.chromium.launch(channel="chrome", headless=True, args=["--disable-webgl"])
            fallback = fallback_browser.new_context()
            fallback_fake = Fixtures()
            fallback.route("**/api/**", fallback_fake.api)
            fallback.route_web_socket(re.compile(r"ws://127\.0\.0\.1:\d+/ws.*"), fallback_fake.ws)
            fallback_page = fallback.new_page()
            fallback_page.on("pageerror", lambda error: errors.append(str(error)))
            fallback_page.goto(url)
            fallback_page.wait_for_function("document.querySelector('.app-shell').dataset.glass === 'fallback'")
            expect(fallback_page.get_by_role("tab", name="Servidor", exact=True)).to_be_visible()
            results["webgl_disabled_fallback"] = "passed"
            fallback_browser.close()
            quota = browser.new_context()
            quota.add_init_script("""const original = Storage.prototype.setItem;
              Storage.prototype.setItem = function(key,value) {
                if(key === 'bedrock-appearance') throw new DOMException('QA quota', 'QuotaExceededError');
                return original.call(this,key,value);
              };
              Object.defineProperty(window,'indexedDB',{get(){throw new DOMException('QA blocked', 'SecurityError')}});""")
            quota_fake = Fixtures()
            quota.route("**/api/**", quota_fake.api)
            quota.route_web_socket(re.compile(r"ws://127\.0\.0\.1:\d+/ws.*"), quota_fake.ws)
            quota_page = quota.new_page()
            quota_page.on("pageerror", lambda error: errors.append(str(error)))
            quota_page.goto(url)
            open_appearance(quota_page)
            quota_page.locator("#background-file").set_input_files(str(wallpaper))
            expect(quota_page.get_by_text("El fondo se aplicó, pero solo estará disponible durante esta sesión.", exact=True)).to_be_visible()
            expect(quota_page.locator(".appearance-preview img")).to_be_visible()
            results["storage_unavailable_session_warning"] = "passed"
            quota.close()
            check_initial_connection(browser, url, errors)
            results["websocket_initial_error_stale_session_callbacks"] = "passed"
            check_small_viewport_menus(browser, url, errors)
            results["menus_small_viewport_reflow_and_short_mobile_emulation"] = "passed"
            context.close()
            browser.close()
        assert not errors, errors
        results["page_errors"] = errors
        results["scope"] = "Frontend dist real; API y WebSocket simulados. Sin operaciones Minecraft reales."
        (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"Evidencias: {OUT}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    run()
