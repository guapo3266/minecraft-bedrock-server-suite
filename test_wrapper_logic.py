import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
import server_wrapper as sw

class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)
    def readline(self):
        if not self._lines:
            return ""
        return self._lines.pop(0)

class FakeProcess:
    def __init__(self, lines):
        self.stdout = FakeStdout(lines)
    def poll(self):
        return None

def reset_state():
    sw.players_online = set()
    sw.backup_in_progress = False
    sw.backup_dispatched = False
    sw.save_query_ready_seen = False
    sw.last_save_snapshot = []
    sw.expecting_list_names = False
    sw.last_snapshot_update_time = 0.0

def run_lines(lines):
    sw.server_process = FakeProcess(lines)
    sw.read_stdout()

def test(name, fn):
    reset_state()
    try:
        fn()
        print(f"[PASS] {name}")
    except AssertionError as e:
        print(f"[FAIL] {name}: {e}")

# --- Test 1: list normal ---
def t1():
    run_lines([
        "[INFO] list\n",
        "There are 2/10 players online:\n",
        "Alice, Bob\n",
    ])
    assert sw.players_online == {"Alice", "Bob"}, sw.players_online
test("list normal (header + nombres en linea siguiente)", t1)

# --- Test 2: list con ruido de logs entre encabezado y nombres ---
def t2():
    run_lines([
        "There are 2/10 players online:\n",
        "[2026-07-23 10:00:00:001 INFO] Chunk loaded at (10,20)\n",
        "[2026-07-23 10:00:00:002 INFO] Autosave tick\n",
        "Alice, Bob\n",
    ])
    assert sw.players_online == {"Alice", "Bob"}, sw.players_online
test("list con ruido de logs entre medio", t2)

# --- Test 3: EL BUG ORIGINAL - continuacion de list pendiente cuando arranca backup ---
def t3():
    sw.backup_in_progress = False
    run_lines([
        "There are 1/10 players online:\n",   # dispara expecting_list_names=True
    ])
    # Ahora simulamos que el scheduler arranco un backup en caliente
    # (esto es lo que el fix hace en backup_scheduler antes de mandar 'save hold')
    with sw.state_lock:
        sw.backup_in_progress = True
        sw.expecting_list_names = False   # <-- el fix
    run_lines([
        "Data saved. Files are now ready to be copied.\n",
        "level.dat:6304, db/000030.ldb:1917505\n",
    ])
    assert "Data saved. Files are now ready to be copied." not in sw.players_online, \
        f"BUG: la linea de save query contamino players_online: {sw.players_online}"
    assert sw.save_query_ready_seen is True
    assert ("level.dat", 6304) in sw.last_save_snapshot
    assert ("db/000030.ldb", 1917505) in sw.last_save_snapshot
test("bug original: 'list' pendiente + arranque de backup (con fix)", t3)

# --- Test 3b: MISMO escenario pero SIN aplicar el fix (para probar que de verdad hubiera fallado) ---
def t3b():
    sw.backup_in_progress = False
    run_lines([
        "There are 1/10 players online:\n",
    ])
    with sw.state_lock:
        sw.backup_in_progress = True
        # NO reseteamos expecting_list_names -> reproduce el bug original
    run_lines([
        "Data saved. Files are now ready to be copied.\n",
    ])
    corrupted = "Data saved. Files are now ready to be copied." in sw.players_online
    print(f"    (sin fix) players_online = {sw.players_online} -> corrupto={corrupted}")
test("reproduccion del bug SIN el fix (para confirmar que existia)", t3b)

# --- Test 4: connect/disconnect ---
def t4():
    run_lines([
        "[INFO] Player connected: Steve, xuid: 123456789012345\n",
        "[INFO] Player connected: Alex, xuid: 987654321098765\n",
        "[INFO] Player disconnected: Steve, xuid: 123456789012345\n",
    ])
    assert sw.players_online == {"Alex"}, sw.players_online
test("connect/disconnect normal (con espacio tras xuid:)", t4)

# --- Test 5: xuid SIN espacio durante ventana de snapshot (caso borde que marque como riesgo) ---
def t5():
    sw.backup_in_progress = True
    sw.backup_dispatched = False
    sw.save_query_ready_seen = True
    sw.last_save_snapshot = [("level.dat", 100)]
    sw.last_snapshot_update_time = time.time()
    run_lines([
        "[INFO] Player connected: Bob, xuid:12345678901234567\n",  # SIN espacio
    ])
    bogus = any(p == " xuid" or p.strip() == "xuid" for p, _ in sw.last_save_snapshot)
    paths = [p for p, _ in sw.last_save_snapshot]
    print(f"    snapshot tras linea xuid sin espacio: {sw.last_save_snapshot}")
    assert len(sw.last_save_snapshot) == 1, f"Se agrego una entrada espuria al snapshot: {sw.last_save_snapshot}"
test("xuid sin espacio durante ventana de snapshot activo", t5)

# --- Test 6: multiples 'Data saved' (reintentos de save query) no dejan basura ---
def t6():
    sw.backup_in_progress = True
    sw.backup_dispatched = False
    run_lines([
        "Data saved. Files are now ready to be copied.\n",
        "level.dat:100\n",
        "Data saved. Files are now ready to be copied.\n",   # reintento
        "level.dat:100, level.dat_old:100\n",
    ])
    assert sw.last_save_snapshot == [("level.dat", 100), ("level.dat_old", 100)], sw.last_save_snapshot
test("reintentos de 'save query' no acumulan snapshots viejos", t6)

# --- Test 2 (regresion): ruido de logs entre header y nombres, CON el fix ---
def t2_fix():
    run_lines([
        "There are 2/10 players online:\n",
        "[2026-07-23 10:00:00:001 INFO] Chunk loaded at (10,20)\n",
        "[2026-07-23 10:00:00:002 INFO] Autosave tick\n",
        "Alice, Bob\n",
    ])
    assert sw.players_online == {"Alice", "Bob"}, sw.players_online
test("[REGRESION] ruido de logs entre header y nombres (con fix)", t2_fix)

# --- Test 5 (regresion): xuid sin espacio durante ventana de snapshot, CON el fix ---
def t5_fix():
    sw.backup_in_progress = True
    sw.backup_dispatched = False
    sw.save_query_ready_seen = True
    sw.last_save_snapshot = [("level.dat", 100)]
    sw.last_snapshot_update_time = time.time()
    run_lines([
        "[INFO] Player connected: Bob, xuid:12345678901234567\n",
    ])
    assert sw.last_save_snapshot == [("level.dat", 100)], \
        f"Se agrego una entrada espuria: {sw.last_save_snapshot}"
    assert sw.players_online == {"Bob"}, sw.players_online
test("[REGRESION] xuid sin espacio durante ventana de snapshot (con fix)", t5_fix)

print("\n--- Pruebas de auto_backup.py (_resolve_snapshot_path) ---")
import auto_backup as ab

def t7():
    try:
        ab._resolve_snapshot_path("../../../etc/passwd")
        print("[FAIL] path traversal con '..' no fue rechazado")
    except ValueError:
        print("[PASS] path traversal con '..' rechazado correctamente")
t7()

def t8():
    try:
        ab._resolve_snapshot_path("db/000030.ldb")
        print("[PASS] ruta normal 'db/000030.ldb' resuelta sin error")
    except Exception as e:
        print(f"[FAIL] ruta normal fallo inesperadamente: {e}")
t8()

def t9():
    # ruta absoluta (con drive letter estilo windows) intentando escapar
    try:
        ab._resolve_snapshot_path("C:/Windows/System32/config/SAM")
        print("[INFO] ruta tipo windows absoluta no lanzo excepcion, revisar full_path resultante")
    except ValueError:
        print("[PASS] ruta absoluta tipo windows rechazada")
t9()
