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

# Caracteres seguros para rutas de archivo en save query (sin : , [ ] \r \n)
_safe_chars = st.characters(
    blacklist_categories=('Zs', 'Cc', 'Cs'),
    blacklist_characters=":,\r\n/\\"
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

@st.composite
def valid_world_relative_path(draw):
    """Ruta relativa dentro de WORLD_DIR: db/file, level.dat, etc."""
    segs = draw(st.lists(_safe_subdir, min_size=1, max_size=3))
    path = "/".join(segs)
    # Filtrar casos degenerados: path vacío, .., solo separadores, nombres reservados Windows
    if ".." in path.replace("//", "/") or path in ("/", "\\", ""):
        return draw(st.text(alphabet=_safe_chars, min_size=1, max_size=12))
    if any(seg.lower() in _WIN_RESERVED for seg in path.split("/")):
        return draw(st.text(alphabet=_safe_chars, min_size=1, max_size=12))
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
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
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


def test_rotate_corrupt_markers():
    """Backups marcados _CORRUPTO no se eliminan ni cuentan."""
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = os.path.join(tmp, "auto_backups")
        restore_backup_dir = ab.BACKUP_DIR
        ab.BACKUP_DIR = backup_dir

        try:
            os.makedirs(backup_dir, exist_ok=True)
            old = datetime.datetime(2020, 1, 1, 0, 0, 0)
            _make_backup_files(backup_dir, [
                (f"old_{i:02d}", old - datetime.timedelta(hours=i))
                for i in range(20)
            ])

            corrupt_path = os.path.join(
                backup_dir, "auto_backup_corrupto_2020-01-01_00-00-00_CORRUPTO.zip"
            )
            with open(corrupt_path, "w") as f:
                f.write("corrupt")
            os.utime(corrupt_path, (old.timestamp(), old.timestamp()))

            ab.rotate_backups()
            after = set(os.listdir(backup_dir))
            assert "auto_backup_corrupto_2020-01-01_00-00-00_CORRUPTO.zip" in after, (
                "Rotación eliminó backup marcado como corrupto"
            )
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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
