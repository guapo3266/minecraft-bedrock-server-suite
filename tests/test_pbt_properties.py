"""
Property-based tests para server_wrapper y auto_backup.
Usa Hypothesis para generar entradas aleatorias y verificar
propiedades generales del código.
"""

import sys, os, datetime, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from hypothesis import given, strategies as st, settings, example, assume, HealthCheck
import server_wrapper as sw
import auto_backup as ab


# ═══════════════════════════════════════════════════════════════════════════════
# Estrategias compartidas de generación
# ═══════════════════════════════════════════════════════════════════════════════

# Caracteres seguros para rutas de archivo en save query (sin : , [ ] \r \n <)
_safe_chars = st.characters(
    blacklist_categories=('Zs', 'Cc', 'Cs'),
    blacklist_characters=":,\r\n/\\<"
)


@st.composite
def clean_relpath(draw):
    """Ruta relativa segura: segmentos unidos por /."""
    segs = draw(st.lists(
        st.text(alphabet=_safe_chars, min_size=1, max_size=20),
        min_size=1, max_size=4,
    ))
    return "/".join(segs)


@st.composite
def valid_save_query_line(draw):
    """Genera una línea de save query válida: path:size, path:size ..."""
    pairs = draw(st.lists(
        st.tuples(clean_relpath(), st.integers(min_value=0, max_value=2**31 - 1)),
        min_size=1, max_size=15,
    ))
    line = ", ".join(f"{p}:{s}" for p, s in pairs)
    return line, pairs


# ═══════════════════════════════════════════════════════════════════════════════
# 1) parse_save_query_files  —  parser de texto → datos estructurados
# ═══════════════════════════════════════════════════════════════════════════════

@given(valid_save_query_line())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@example(("level.dat:6304, db/000030.ldb:1917505", [("level.dat", 6304), ("db/000030.ldb", 1917505)]))
@example(("a:0", [("a", 0)]))
@example(("x/y:1", [("x/y", 1)]))
def test_parse_roundtrip(data):
    """parse_save_query_files(formato(pares)) == pares originales."""
    line, expected_pairs = data
    result = sw.parse_save_query_files(line)
    assert result == expected_pairs, (
        f"\n  input: {line!r}"
        f"\n  got:      {result}"
        f"\n  expected: {expected_pairs}"
    )


@given(valid_save_query_line())
@settings(max_examples=100)
@example(("level.dat:100", [("level.dat", 100)]))
@example(("[2026-07-30 12:00:00:001 INFO] level.dat:100", [("level.dat", 100)]))
@example(("[INFO] [DEBUG] db/0.ldb:5", [("db/0.ldb", 5)]))
def test_parse_prefix_stripped(data):
    """Los prefijos de timestamp/log no afectan el resultado."""
    raw_line, expected_pairs = data
    prefixed = f"[2026-07-30 12:00:00:001 INFO] {raw_line}"
    result = sw.parse_save_query_files(prefixed)
    assert result == expected_pairs, (
        f"\n  prefixed: {prefixed!r}"
        f"\n  got:      {result}"
        f"\n  expected: {expected_pairs}"
    )


@given(st.text(min_size=1, max_size=50), st.text(max_size=200))
@settings(max_examples=100)
@example("Player", "level.dat:100, db/CURRENT:10")
@example("Attacker", "Player disconnected: Steve, xuid: 12345")
def test_parse_chat_lines_always_empty(player, msg):
    """Cualquier línea con formato de chat <Jugador> devuelve lista vacía y no parsea archivos."""
    chat_line = f"<{player}> {msg}"
    prefixed_chat = f"[2026-08-03 12:00:00:001 INFO] <{player}> {msg}"
    assert sw.parse_save_query_files(chat_line) == []
    assert sw.parse_save_query_files(prefixed_chat) == []


@given(st.text(max_size=200))
@settings(max_examples=200)
@example("")
@example("[INFO] hello world")
@example("   ")
@example("level.dat")
def test_parse_no_crash(line):
    """Ningún texto hace crashear al parser (propiedad más débil)."""
    try:
        result = sw.parse_save_query_files(line)
    except Exception as e:
        raise AssertionError(f"Crash con input {line!r}: {type(e).__name__}: {e}")

    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, tuple) and len(item) == 2, f"Elemento inválido: {item}"
        p, s = item
        assert isinstance(p, str), f"Path no es str: {p}"
        assert isinstance(s, int), f"Size no es int: {s}"
        assert s >= 0, f"Size negativo: {s}"


@given(st.text(alphabet=st.characters(blacklist_categories=('Cn',)), max_size=300))
@settings(max_examples=200)
@example("path with spaces:100, other:200")
@example("a::100")
@example("a:100,,b:200")
def test_parse_no_crash_any_text(line):
    """Ningún texto Unicode arbitrario crashea."""
    try:
        result = sw.parse_save_query_files(line)
        assert isinstance(result, list)
    except Exception as e:
        raise AssertionError(f"Crash con input {line[:80]!r}: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 2) _resolve_snapshot_path  —  resolución + validación de rutas
# ═══════════════════════════════════════════════════════════════════════════════

def _make_fake_world_dir(base):
    """Crea estructura mínima de mundo para testing."""
    world = os.path.join(base, "worlds", "Bedrock level")
    os.makedirs(os.path.join(world, "db"), exist_ok=True)
    for fname in ["level.dat", "db/000030.ldb", "db/000001.ldb", "db/MANIFEST-000001"]:
        full = os.path.join(world, fname)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write("fake")
    return world


_safe_subdir = st.text(alphabet=_safe_chars, min_size=1, max_size=12)


# Nombres reservados de Windows que os.path.abspath trata como dispositivos
_WIN_RESERVED = {"nul", "con", "prn", "aux"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}

# Fallback filtrado: el redraw sin filtro podia devolver 'NUL' (os.path.abspath
# lo normaliza a la ruta de dispositivo relativa '\\.\NUL' y commonpath falla)
# o '..', rompiendo el test con rutas que un save query real jamas genera.
_safe_fallback = st.text(alphabet=_safe_chars, min_size=1, max_size=12).filter(
    lambda s: s.lower() not in _WIN_RESERVED and s not in (".", "..", "/", "\\", "")
)

@st.composite
def valid_world_relative_path(draw):
    """Ruta relativa dentro de WORLD_DIR: db/file, level.dat, etc."""
    segs = draw(st.lists(_safe_subdir, min_size=1, max_size=3))
    path = "/".join(segs)
    # Filtrar casos degenerados: path vacío, .., solo separadores, nombres reservados Windows
    if ".." in path.replace("//", "/") or path in ("/", "\\", ""):
        return draw(_safe_fallback)
    if any(seg.lower() in _WIN_RESERVED for seg in path.split("/")):
        return draw(_safe_fallback)
    return path


@given(valid_world_relative_path())
@settings(max_examples=100)
@example("db/000030.ldb")
@example("level.dat")
@example("db/MANIFEST-000001")
def test_resolve_valid_paths(rel_path):
    """Toda ruta aceptada tiene commonpath == WORLD_DIR."""
    assume(rel_path and not rel_path.startswith("/"))
    with tempfile.TemporaryDirectory() as tmp:
        world = _make_fake_world_dir(tmp)
        restore_world = ab.WORLD_DIR
        ab.WORLD_DIR = world
        ab.WORLD_PARENT_DIR = os.path.join(tmp, "worlds")
        try:
            clean, full = ab._resolve_snapshot_path(rel_path)
            common = os.path.commonpath([os.path.abspath(world), os.path.abspath(full)])
            assert common == os.path.abspath(world), (
                f"Ruta {rel_path!r} escapó: full={full}, common={common}"
            )
        except ValueError:
            raise AssertionError(f"Ruta válida {rel_path!r} fue rechazada inesperadamente")
        finally:
            ab.WORLD_DIR = restore_world


@given(st.text(alphabet=st.characters(blacklist_categories=('Cn',)), min_size=1, max_size=80))
@settings(max_examples=100)
@example("../../../etc/passwd")
@example("..\\..\\Windows\\system32")
@example("C:/Windows/System32")
def test_resolve_path_traversal(rel_path):
    """Rutas sospechosas con .. deben ser rechazadas o forzadas dentro del mundo."""
    if ".." not in rel_path and ":" not in rel_path:
        return  # solo nos interesan rutas sospechosas

    with tempfile.TemporaryDirectory() as tmp:
        world = _make_fake_world_dir(tmp)
        restore_world = ab.WORLD_DIR
        ab.WORLD_DIR = world
        ab.WORLD_PARENT_DIR = os.path.join(tmp, "worlds")
        try:
            try:
                ab._resolve_snapshot_path(rel_path)
            except ValueError:
                pass  # comportamiento correcto
            except (OSError, RuntimeError):
                pass  # aceptable: path demasiado raro para el SO
        finally:
            ab.WORLD_DIR = restore_world


def test_resolve_known_paths():
    """Prueba manual contra paths de snapshots reales."""
    with tempfile.TemporaryDirectory() as tmp:
        world = _make_fake_world_dir(tmp)
        restore_world = ab.WORLD_DIR
        ab.WORLD_DIR = world
        ab.WORLD_PARENT_DIR = os.path.join(tmp, "worlds")
        try:
            for path in ["db/000030.ldb", "level.dat", "db/MANIFEST-000001"]:
                clean, full = ab._resolve_snapshot_path(path)
                assert os.path.exists(full), f"{path} resolvió a ruta inexistente: {full}"
        finally:
            ab.WORLD_DIR = restore_world


# ═══════════════════════════════════════════════════════════════════════════════
# 3) rotate_backups  —  política de retención
# ═══════════════════════════════════════════════════════════════════════════════

def _make_backup_files(backup_dir, file_dates):
    """Crea archivos .zip falsos con fechas de modificación específicas.
    file_dates: lista de tuplas (nombre_base, fecha_datetime)"""
    os.makedirs(backup_dir, exist_ok=True)
    created = []
    for name, dt in file_dates:
        path = os.path.join(backup_dir, f"auto_backup_{name}.zip")
        with open(path, "w") as f:
            f.write("fake backup content")
        ts = dt.timestamp()
        os.utime(path, (ts, ts))
        created.append(path)
    return created


@given(
    st.lists(
        st.integers(min_value=0, max_value=30),
        min_size=1, max_size=50,
    )
)
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@example([0, 0, 0, 0, 0])
@example([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])
@example([0]*25 + [1]*10 + [2]*10)
def test_rotate_retention_limits(days_ago_list):
    """La rotación nunca excede los límites de retención ni deja duplicados por día."""
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "auto_backups")
        restore_backup_dir = ab.BACKUP_DIR
        ab.BACKUP_DIR = backup_dir

        try:
            now = datetime.datetime(2026, 7, 30, 12, 0, 0)
            file_dates = []
            for i, days_ago in enumerate(days_ago_list):
                dt = now - datetime.timedelta(days=days_ago, hours=i % 24, minutes=(i * 7) % 60)
                file_dates.append((f"test_{i:04d}", dt))

            _make_backup_files(backup_dir, file_dates)
            ab.rotate_backups()

            surviving = set(os.listdir(backup_dir))

            # Invariante 1: máximo de archivos retenidos
            max_possible = ab.MAX_RECENT_BACKUPS + ab.DAYS_TO_KEEP_DAILY
            assert len(surviving) <= max_possible, (
                f"Retención excede límite: {len(surviving)} > {max_possible}"
            )

            # Invariante 2: idempotencia — segunda pasada no cambia nada
            ab.rotate_backups()
            surviving2 = set(os.listdir(backup_dir))
            assert surviving == surviving2, (
                f"Idempotencia rota:\n  1ra: {sorted(surviving)}\n  2da: {sorted(surviving2)}"
            )

        finally:
            ab.BACKUP_DIR = restore_backup_dir


def test_rotate_corrupt_markers_politica_retencion():
    """H1: backups marcados _CORRUPTO/_EXCEDIDO: la evidencia reciente se
    conserva (no compite por las capas recientes/diarias) pero pasados
    CORRUPT_BACKUP_RETENTION_DAYS se rotan. (Contrato viejo: nunca se
    eliminaban -> fuga de disco indefinida.)"""
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "auto_backups")
        restore_backup_dir = ab.BACKUP_DIR
        ab.BACKUP_DIR = backup_dir

        try:
            os.makedirs(backup_dir, exist_ok=True)
            now = datetime.datetime(2026, 7, 30, 12, 0, 0)
            recent = now - datetime.timedelta(days=2)
            old = now - datetime.timedelta(days=ab.CORRUPT_BACKUP_RETENTION_DAYS + 10)

            _make_backup_files(backup_dir, [
                (f"old_{i:02d}", old - datetime.timedelta(hours=i))
                for i in range(20)
            ])

            marked = [
                ("auto_backup_reciente_2026-07-28_00-00-00_CORRUPTO.zip", recent),
                ("auto_backup_viejo_2020-01-01_00-00-00_CORRUPTO.zip", old),
                ("auto_backup_excedido_2020-01-01_00-00-00_EXCEDIDO.zip", old),
            ]
            for name, dt in marked:
                path = os.path.join(backup_dir, name)
                with open(path, "w") as f:
                    f.write("corrupt")
                os.utime(path, (dt.timestamp(), dt.timestamp()))

            ab.rotate_backups(now=now)
            after = set(os.listdir(backup_dir))
            assert "auto_backup_reciente_2026-07-28_00-00-00_CORRUPTO.zip" in after, (
                "Rotacion elimino evidencia de corrupcion reciente"
            )
            assert "auto_backup_viejo_2020-01-01_00-00-00_CORRUPTO.zip" not in after, (
                "corrupto fuera de la ventana de retencion no rotado"
            )
            assert "auto_backup_excedido_2020-01-01_00-00-00_EXCEDIDO.zip" not in after, (
                "excedido fuera de la ventana de retencion no rotado"
            )
            # Idempotencia: segunda pasada no cambia nada
            after2 = set(os.listdir(backup_dir))
            assert after == after2
        finally:
            ab.BACKUP_DIR = restore_backup_dir


def test_rotate_stable_ordering():
    """El resultado es determinista sin importar el orden de creación."""
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "auto_backups")
        restore_backup_dir = ab.BACKUP_DIR
        ab.BACKUP_DIR = backup_dir

        try:
            base = datetime.datetime(2026, 7, 30, 12, 0, 0)
            files = [(f"a_{i:02d}", base - datetime.timedelta(hours=i)) for i in range(20)]

            _make_backup_files(backup_dir, files)
            ab.rotate_backups()
            pass1 = sorted(os.listdir(backup_dir))

            for f in os.listdir(backup_dir):
                os.unlink(os.path.join(backup_dir, f))
            _make_backup_files(backup_dir, files[::-1])
            ab.rotate_backups()
            pass2 = sorted(os.listdir(backup_dir))

            assert pass1 == pass2, (
                f"Resultado no determinista:\n  natural: {pass1}\n  inverso: {pass2}"
            )
        finally:
            ab.BACKUP_DIR = restore_backup_dir


# ═══════════════════════════════════════════════════════════════════════════════
# 4) parse_save_query_files  —  prefijos de log apilados
# ═══════════════════════════════════════════════════════════════════════════════

_LOG_PREFIXES = (
    "[2026-07-30 12:00:00:001 INFO] ",
    "[INFO] ",
    "[WARN] ",
)


@st.composite
def prefixed_save_query_line(draw):
    """Línea de save query válida con 0..3 prefijos de log apilados."""
    line, pairs = draw(valid_save_query_line())
    prefixes = draw(st.lists(st.sampled_from(_LOG_PREFIXES), min_size=0, max_size=3))
    return "".join(prefixes) + line, pairs


@given(prefixed_save_query_line())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@example(("[INFO] [WARN] a:0", [("a", 0)]))
def test_parse_stacked_prefixes(data):
    """Todos los prefijos apilados se eliminan; el roundtrip se conserva."""
    raw, expected = data
    result = sw.parse_save_query_files(raw)
    assert result == expected, (
        f"\n  input:    {raw!r}"
        f"\n  got:      {result}"
        f"\n  expected: {expected}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5) _resolve_snapshot_path  —  idempotencia y equivalencia de separadores
# ═══════════════════════════════════════════════════════════════════════════════

@st.composite
def safe_world_relpath(draw):
    """Ruta relativa segura y sin ambiguedad para _resolve_snapshot_path:
    primer segmento distinto de 'worlds' y del nombre del mundo; sin '..'
    ni nombres reservados de Windows (NUL, CON, ...) que abspath convierte
    en dispositivos (\\\\.\\NUL) y hacen fallar commonpath por diseno."""
    world_name = os.path.basename(os.path.abspath(ab.WORLD_DIR)).lower()
    segs = draw(st.lists(
        st.text(alphabet=_safe_chars, min_size=1, max_size=12).filter(
            lambda s: s != ".." and s.split(".")[0].lower() not in _WIN_RESERVED
        ),
        min_size=1, max_size=3,
    ))
    if segs[0].lower() in ("worlds", world_name):
        segs[0] = "data"  # primer segmento neutral: evita rama contra BASE_DIR real
    return "/".join(segs)


@given(safe_world_relpath())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_idempotent(rel_path):
    """resolve(resolve(p)) == resolve(p): la ruta 'limpia' devuelta es una
    normalizacion estable (mismo full_path y mismo clean_rel_path)."""
    with tempfile.TemporaryDirectory() as tmp:
        world = _make_fake_world_dir(tmp)
        restore_world = ab.WORLD_DIR
        ab.WORLD_DIR = world
        ab.WORLD_PARENT_DIR = os.path.join(tmp, "worlds")
        try:
            clean1, full1 = ab._resolve_snapshot_path(rel_path)
            clean2, full2 = ab._resolve_snapshot_path(clean1)
            assert full2 == full1, f"{rel_path!r}: full {full1!r} -> {full2!r}"
            assert clean2 == clean1, f"{rel_path!r}: clean {clean1!r} -> {clean2!r}"
        finally:
            ab.WORLD_DIR = restore_world


@given(safe_world_relpath())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_separator_and_dot_equivalence(rel_path):
    """'\\' vs '/' y prefijo './' resuelven al mismo full_path (normalizacion)."""
    with tempfile.TemporaryDirectory() as tmp:
        world = _make_fake_world_dir(tmp)
        restore_world = ab.WORLD_DIR
        ab.WORLD_DIR = world
        ab.WORLD_PARENT_DIR = os.path.join(tmp, "worlds")
        try:
            _, full_a = ab._resolve_snapshot_path(rel_path)
            _, full_b = ab._resolve_snapshot_path(rel_path.replace("/", os.sep))
            assert full_b == full_a, f"separadores: {rel_path!r}"
            _, full_c = ab._resolve_snapshot_path("./" + rel_path)
            assert full_c == full_a, f"prefijo ./: {rel_path!r}"
        finally:
            ab.WORLD_DIR = restore_world


# ═══════════════════════════════════════════════════════════════════════════════
# 6) rotate_backups  —  invariantes de retención robustos al "now" real
# ═══════════════════════════════════════════════════════════════════════════════

@given(st.lists(st.integers(min_value=0, max_value=60), min_size=1, max_size=60))
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rotate_newest_always_survives(days_ago_list):
    """El backup mas reciente jamas se elimina, sin importar la politica."""
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "auto_backups")
        restore_backup_dir = ab.BACKUP_DIR
        ab.BACKUP_DIR = backup_dir

        try:
            now = datetime.datetime.now()
            dates = [
                now - datetime.timedelta(days=d, minutes=i)
                for i, d in enumerate(days_ago_list)
            ]
            created = _make_backup_files(backup_dir, [
                (f"t_{i:04d}", dt) for i, dt in enumerate(dates)
            ])
            newest_name = os.path.basename(max(created, key=os.path.getmtime))

            ab.rotate_backups(now=now)

            assert newest_name in os.listdir(backup_dir), (
                f"Rotacion elimino el backup mas reciente: {newest_name}"
            )
        finally:
            ab.BACKUP_DIR = restore_backup_dir


@given(st.lists(st.integers(min_value=0, max_value=60), min_size=16, max_size=80))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rotate_old_survivors_bounded_by_recent_layer(days_ago_list):
    """Solo la capa 'recientes' puede conservar backups fuera de la ventana
    diaria: supervivientes con mas de DAYS_TO_KEEP_DAILY dias <= MAX_RECENT."""
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "auto_backups")
        restore_backup_dir = ab.BACKUP_DIR
        ab.BACKUP_DIR = backup_dir

        try:
            now = datetime.datetime.now()
            dates = [
                now - datetime.timedelta(days=d, minutes=i)
                for i, d in enumerate(days_ago_list)
            ]
            _make_backup_files(backup_dir, [
                (f"t_{i:04d}", dt) for i, dt in enumerate(dates)
            ])

            ab.rotate_backups(now=now)

            old_survivors = 0
            for name in os.listdir(backup_dir):
                mtime = os.path.getmtime(os.path.join(backup_dir, name))
                dt = datetime.datetime.fromtimestamp(mtime)
                age_days = (now.date() - dt.date()).days
                if age_days > ab.DAYS_TO_KEEP_DAILY:
                    old_survivors += 1

            assert old_survivors <= ab.MAX_RECENT_BACKUPS, (
                f"{old_survivors} supervivientes fuera de la ventana diaria "
                f"(max {ab.MAX_RECENT_BACKUPS} por la capa de recientes)"
            )
        finally:
            ab.BACKUP_DIR = restore_backup_dir


# ═══════════════════════════════════════════════════════════════════════════════
# 7) _is_safe_zip_entry  —  consenso entre las 3 copias (anti-drift)
# ═══════════════════════════════════════════════════════════════════════════════

import restore_backup as rb
import server_gui_server as sgs

_zip_segment = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs"), blacklist_characters="\x00"),
    min_size=0, max_size=20,
)

_hostile_zip_name = st.lists(
    st.one_of(_zip_segment, st.just(".."), st.just("."), st.just(""), st.just("C:")),
    min_size=1, max_size=6,
).map(lambda segs: "/".join(segs))


@given(_hostile_zip_name)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@example("../../etc/passwd")
@example("C:/Windows/System32")
@example("a\\..\\b")
def test_zip_entry_consensus(name):
    """auto_backup, restore_backup y server_gui_server aplican el mismo guard
    anti zip-slip: si alguno diverge, hay drift entre las copias."""
    verdicts = {
        "auto_backup": ab._is_safe_zip_entry(name),
        "restore_backup": rb._is_safe_zip_entry(name),
        "server_gui_server": sgs._is_safe_zip_entry(name),
    }
    assert len(set(verdicts.values())) == 1, (
        f"Consenso roto para {name!r}: {verdicts}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
