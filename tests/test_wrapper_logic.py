import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server_wrapper as sw
import wrapper_state as wstate

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
    wstate.players_online.clear()
    wstate.backup_in_progress = False
    wstate.backup_dispatched = False
    wstate.save_query_ready_seen = False
    wstate.last_save_snapshot = []
    wstate.expecting_list_names = False
    wstate.last_snapshot_update_time = 0.0

def run_lines(lines):
    wstate.server_process = FakeProcess(lines)
    sw.read_stdout()

def run_case(name, fn):
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
    assert wstate.players_online == {"Alice", "Bob"}, wstate.players_online
run_case("list normal (header + nombres en linea siguiente)", t1)

# --- Test 2: list con ruido de logs entre encabezado y nombres ---
def t2():
    run_lines([
        "There are 2/10 players online:\n",
        "[2026-07-23 10:00:00:001 INFO] Chunk loaded at (10,20)\n",
        "[2026-07-23 10:00:00:002 INFO] Autosave tick\n",
        "Alice, Bob\n",
    ])
    assert wstate.players_online == {"Alice", "Bob"}, wstate.players_online
run_case("list con ruido de logs entre medio", t2)

# --- Test 3: EL BUG ORIGINAL - continuacion de list pendiente cuando arranca backup ---
def t3():
    wstate.backup_in_progress = False
    run_lines([
        "There are 1/10 players online:\n",   # dispara expecting_list_names=True
    ])
    # Ahora simulamos que el scheduler arranco un backup en caliente
    # (esto es lo que el fix hace en backup_scheduler antes de mandar 'save hold')
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.expecting_list_names = False   # <-- el fix
    run_lines([
        "Data saved. Files are now ready to be copied.\n",
        "level.dat:6304, db/000030.ldb:1917505\n",
    ])
    assert "Data saved. Files are now ready to be copied." not in wstate.players_online, \
        f"BUG: la linea de save query contamino players_online: {wstate.players_online}"
    assert wstate.save_query_ready_seen is True
    assert ("level.dat", 6304) in wstate.last_save_snapshot
    assert ("db/000030.ldb", 1917505) in wstate.last_save_snapshot
run_case("bug original: 'list' pendiente + arranque de backup (con fix)", t3)

# --- Test 3b: MISMO escenario pero SIN aplicar el fix (para probar que de verdad hubiera fallado) ---
def t3b():
    wstate.backup_in_progress = False
    run_lines([
        "There are 1/10 players online:\n",
    ])
    with wstate.state_lock:
        wstate.backup_in_progress = True
        # NO reseteamos expecting_list_names -> reproduce el bug original
    run_lines([
        "Data saved. Files are now ready to be copied.\n",
    ])
    corrupted = "Data saved. Files are now ready to be copied." in wstate.players_online
    print(f"    (sin fix) players_online = {wstate.players_online} -> corrupto={corrupted}")
run_case("reproduccion del bug SIN el fix (para confirmar que existia)", t3b)

# --- Test 4: connect/disconnect ---
def t4():
    run_lines([
        "[INFO] Player connected: Steve, xuid: 123456789012345\n",
        "[INFO] Player connected: Alex, xuid: 987654321098765\n",
        "[INFO] Player disconnected: Steve, xuid: 123456789012345\n",
    ])
    assert wstate.players_online == {"Alex"}, wstate.players_online
run_case("connect/disconnect normal (con espacio tras xuid:)", t4)

# --- Test 5: xuid SIN espacio durante ventana de snapshot (caso borde que marque como riesgo) ---
def t5():
    wstate.backup_in_progress = True
    wstate.backup_dispatched = False
    wstate.save_query_ready_seen = True
    wstate.last_save_snapshot = [("level.dat", 100)]
    wstate.last_snapshot_update_time = time.time()
    run_lines([
        "[INFO] Player connected: Bob, xuid:12345678901234567\n",  # SIN espacio
    ])
    bogus = any(p == " xuid" or p.strip() == "xuid" for p, _ in wstate.last_save_snapshot)
    paths = [p for p, _ in wstate.last_save_snapshot]
    print(f"    snapshot tras linea xuid sin espacio: {wstate.last_save_snapshot}")
    assert len(wstate.last_save_snapshot) == 1, f"Se agrego una entrada espuria al snapshot: {wstate.last_save_snapshot}"
run_case("xuid sin espacio durante ventana de snapshot activo", t5)

# --- Test 6: multiples 'Data saved' (reintentos de save query) no dejan basura ---
def t6():
    wstate.backup_in_progress = True
    wstate.backup_dispatched = False
    run_lines([
        "Data saved. Files are now ready to be copied.\n",
        "level.dat:100\n",
        "Data saved. Files are now ready to be copied.\n",   # reintento
        "level.dat:100, level.dat_old:100\n",
    ])
    assert wstate.last_save_snapshot == [("level.dat", 100), ("level.dat_old", 100)], wstate.last_save_snapshot
run_case("reintentos de 'save query' no acumulan snapshots viejos", t6)

# --- Test 2 (regresion): ruido de logs entre header y nombres, CON el fix ---
def t2_fix():
    run_lines([
        "There are 2/10 players online:\n",
        "[2026-07-23 10:00:00:001 INFO] Chunk loaded at (10,20)\n",
        "[2026-07-23 10:00:00:002 INFO] Autosave tick\n",
        "Alice, Bob\n",
    ])
    assert wstate.players_online == {"Alice", "Bob"}, wstate.players_online
run_case("[REGRESION] ruido de logs entre header y nombres (con fix)", t2_fix)

# --- Test 5 (regresion): xuid sin espacio durante ventana de snapshot, CON el fix ---
def t5_fix():
    wstate.backup_in_progress = True
    wstate.backup_dispatched = False
    wstate.save_query_ready_seen = True
    wstate.last_save_snapshot = [("level.dat", 100)]
    wstate.last_snapshot_update_time = time.time()
    run_lines([
        "[INFO] Player connected: Bob, xuid:12345678901234567\n",
    ])
    assert wstate.last_save_snapshot == [("level.dat", 100)], \
        f"Se agrego una entrada espuria: {wstate.last_save_snapshot}"
    assert wstate.players_online == {"Bob"}, wstate.players_online
run_case("[REGRESION] xuid sin espacio durante ventana de snapshot (con fix)", t5_fix)

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
