"""Test E2E de la GUI (webapp-testing): carga, consola, WS, métricas, backups."""
import json, sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000/"
results = []
console_errors = []
failed_requests = []
ws_messages = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + str(detail) if detail else ""))

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})

    pg.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: failed_requests.append(f"{r.method} {r.url} :: {r.failure}"))
    pg.on("websocket", lambda ws: ws.on("framereceived", lambda data: ws_messages.append(data) if len(ws_messages) < 5 else None))

    # 1. Carga
    pg.goto(BASE, timeout=20000, wait_until="networkidle")
    check("Carga de la página", "gui" in pg.title().lower() or "minecraft" in pg.title().lower(), f"title={pg.title()}")
    time.sleep(2.5)

    # 2. Errores de consola / red
    time.sleep(1)
    check("Sin errores de consola JS", len(console_errors) == 0, console_errors[:3])
    check("Sin peticiones fallidas", len(failed_requests) == 0, failed_requests[:3])

    # 3. Estado del WebSocket
    check("WebSocket recibe mensajes", len(ws_messages) > 0, ws_messages[:2])

    # 4. Elementos clave en el DOM (texto visible)
    body_text = pg.inner_text("body")
    for token in ["Iniciar", "Detener", "Reiniciar", "Backup", "Consola", "Jugadores", "RAM", "CPU"]:
        check(f"Texto visible: '{token}'", token.lower() in body_text.lower())

    # 5. Botonera presente
    buttons = [bt.strip() for bt in pg.eval_on_selector_all("button", "els => els.map(e => e.innerText.trim()).filter(t => t.length > 0 && t.length < 30)")]
    print("  Botones encontrados:", buttons)
    check("Hay botones de control", len(buttons) >= 3, buttons)

    # 6. Screenshot
    pg.screenshot(path="tools/gui_e2e_home.png", full_page=False)
    check("Screenshot generado", True)

    # 7. Interacción: escribir en la consola y enviar (comando seguro 'list' puede fallar si el servidor no corre)
    # Buscar input/textarea de consola
    inputs = pg.eval_on_selector_all("input, textarea", "els => els.map(e => ({tag: e.tagName, ph: e.placeholder || '', type: e.type}))")
    print("  Inputs:", inputs)
    console_input = pg.locator("textarea, input[type='text'], input:not([type])").first
    if console_input.count() > 0:
        try:
            console_input.fill("say prueba-e2e")
            console_input.press("Enter")
            time.sleep(1.5)
            check("Envío de comando aceptado", True, "say prueba-e2e enviado")
        except Exception as e:
            check("Envío de comando", False, str(e)[:120])
    else:
        check("Input de consola presente", False, "no se encontró input/textarea")

    # 8. Ver métricas actualizadas tras espera
    time.sleep(2)
    body_text2 = pg.inner_text("body")
    check("UI sigue viva tras interacción", "Iniciar" in body_text2 or "Detener" in body_text2)

    b.close()

fails = [r for r in results if not r[1]]
print("\n===== RESUMEN =====")
print(f"TOTAL: {len(results)}  PASS: {len(results)-len(fails)}  FAIL: {len(fails)}")
for r in fails:
    print("FAIL ->", r)
sys.exit(1 if fails else 0)
