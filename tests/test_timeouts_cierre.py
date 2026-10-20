# -*- coding: utf-8 -*-
"""Coherencia entre los timeouts de cierre del wrapper y la espera de la GUI.

Desde la ronda 2026-09-25 el timeout del worker de compresion y el del backup
final ESCALAN con el tamano del mundo (`wrapper_state.scaled_backup_timeout_sec`),
pero dos esperas seguian fijas (revision 2026-10-19):

- el join de cierre del worker caliente (135 s): vencia antes que el propio
  timeout del worker con snapshots de mas de 128 MiB, y el cierre maestro mataba
  al worker que debia "suicidarse" primero;
- la fase 2 de la GUI (`WRAPPER_EXIT_TIMEOUT_SEC`, 450 s): vencia mientras el
  wrapper seguia dentro de su backup final escalado (desde 1,75 GB de mundo
  sin worker caliente; desde 0,63 GB con uno, con el join fijo de 135 s),
  abortando restart/actualizaciones.

Estos tests fijan la jerarquia: BDS (60) < stop GUI (75) < espera del wrapper,
y que esa espera cubra siempre el peor caso del wrapper para cualquier tamano.
"""
import os
import types
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

import wrapper_backup as wb
import wrapper_state as wstate
from gui_backend import config
from gui_backend.services import lifecycle
from gui_backend.state import manager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GB = 1024 ** 3


def _peor_caso_wrapper_sec(total_bytes):
    """Tiempo maximo del wrapper tras la muerte de BDS: join del worker caliente
    (con su timeout escalado) + backup final escalado."""
    worker = wstate.scaled_backup_timeout_sec(total_bytes, wstate.WORKER_COMPRESSION_TIMEOUT_SEC)
    final = wstate.scaled_backup_timeout_sec(total_bytes, wstate.FINAL_BACKUP_TIMEOUT_SEC)
    return wstate.worker_join_timeout_sec(worker) + final


# ── Jerarquia y pisos ───────────────────────────────────────────────

def test_jerarquia_de_timeouts_base():
    assert wstate.BDS_STOP_TIMEOUT_SEC < config.SERVER_STOP_TIMEOUT_SEC
    assert config.SERVER_STOP_TIMEOUT_SEC < config.WRAPPER_EXIT_TIMEOUT_SEC


def test_pisos_historicos_intactos():
    """Los pisos no bajan: 135 (join), 120 (worker) y 240 (backup final)."""
    assert wstate.WORKER_COMPRESSION_TIMEOUT_SEC == 120
    assert wstate.FINAL_BACKUP_TIMEOUT_SEC == 240
    assert wstate.WORKER_JOIN_ON_SHUTDOWN_SEC == 135
    assert config.WRAPPER_EXIT_TIMEOUT_SEC == 450


def test_piso_de_la_gui_cubre_el_peor_caso_sin_mundo():
    assert config.WRAPPER_EXIT_TIMEOUT_SEC >= _peor_caso_wrapper_sec(0)


# ── worker_join_timeout_sec ─────────────────────────────────────────

def test_worker_join_timeout_piso_sin_worker_o_dato_invalido():
    piso = wstate.WORKER_JOIN_ON_SHUTDOWN_SEC
    for invalido in (None, 0, -1, "240", True):
        assert wstate.worker_join_timeout_sec(invalido) == piso, invalido


def test_worker_join_timeout_nunca_baja_del_piso():
    assert wstate.worker_join_timeout_sec(wstate.WORKER_COMPRESSION_TIMEOUT_SEC) == (
        wstate.WORKER_JOIN_ON_SHUTDOWN_SEC)
    assert wstate.worker_join_timeout_sec(30) == wstate.WORKER_JOIN_ON_SHUTDOWN_SEC


def test_worker_join_timeout_supera_al_timeout_escalado_del_worker():
    """El caso del informe: un snapshot de 1 GB da 240 s al worker; el join
    fijo de 135 s lo mataba a mitad de su plazo."""
    worker = wstate.scaled_backup_timeout_sec(1 * GB, wstate.WORKER_COMPRESSION_TIMEOUT_SEC)
    assert worker == 240
    assert wstate.worker_join_timeout_sec(worker) == worker + wstate.WORKER_JOIN_MARGIN_SEC
    assert wstate.WORKER_JOIN_ON_SHUTDOWN_SEC < worker  # el fijo antiguo ya no alcanzaba


@given(st.integers(min_value=0, max_value=10 ** 13))
@settings(max_examples=300, deadline=None)
def test_pbt_el_worker_se_suicida_antes_que_el_cierre_maestro(total_bytes):
    """Invariante de DOCUMENTACION_ARQUITECTURA_V5 §3 para cualquier tamano."""
    worker = wstate.scaled_backup_timeout_sec(total_bytes, wstate.WORKER_COMPRESSION_TIMEOUT_SEC)
    assert wstate.worker_join_timeout_sec(worker) > worker


# ── shutdown_extra_sec ──────────────────────────────────────────────

def test_shutdown_extra_cero_con_mundo_desconocido_o_chico():
    assert wstate.shutdown_extra_sec(0) == 0
    assert wstate.shutdown_extra_sec(None) == 0
    assert wstate.shutdown_extra_sec(-1) == 0
    assert wstate.shutdown_extra_sec(100) == 0  # < 1 s de escala: queda en los pisos
    # La escala es lineal desde el piso: 10 MiB suman 1 s al join y 1 s al final.
    assert wstate.shutdown_extra_sec(10 * 1024 * 1024) == 2


def test_shutdown_extra_valores_concretos():
    # 1 GB: join 255 (+120 sobre 135) y final 360 (+120 sobre 240).
    assert wstate.shutdown_extra_sec(1 * GB) == 240
    # 2 GB: join 375 (+240) y final 480 (+240).
    assert wstate.shutdown_extra_sec(2 * GB) == 480
    # Tope: join 3615 y final 3600.
    assert wstate.shutdown_extra_sec(1000 * GB) == (
        (wstate.BACKUP_TIMEOUT_MAX_SEC + wstate.WORKER_JOIN_MARGIN_SEC - wstate.WORKER_JOIN_ON_SHUTDOWN_SEC)
        + (wstate.BACKUP_TIMEOUT_MAX_SEC - wstate.FINAL_BACKUP_TIMEOUT_SEC))


@given(st.integers(min_value=0, max_value=10 ** 13))
@settings(max_examples=300, deadline=None)
def test_pbt_la_espera_de_la_gui_cubre_el_peor_caso_del_wrapper(total_bytes):
    """Para CUALQUIER tamano de mundo, piso + extra >= join del worker + backup
    final: la GUI no aborta mientras el wrapper sigue dentro de sus timeouts."""
    espera_gui = config.WRAPPER_EXIT_TIMEOUT_SEC + wstate.shutdown_extra_sec(total_bytes)
    assert espera_gui >= _peor_caso_wrapper_sec(total_bytes)


@given(st.integers(min_value=0, max_value=10 ** 13), st.integers(min_value=0, max_value=10 ** 13))
@settings(max_examples=200, deadline=None)
def test_pbt_shutdown_extra_es_monotono(a, b):
    lo, hi = sorted((a, b))
    assert wstate.shutdown_extra_sec(lo) <= wstate.shutdown_extra_sec(hi)


def test_los_tamanos_donde_fallaba_el_tope_fijo_de_450():
    """Modelo anterior: join fijo de 135 s + backup final escalado contra un
    tope fijo de 450 s. Fallaba desde 1,75 GB sin worker caliente (final de
    450 s) y desde 0,625 GB con uno (135 + 240 + 120 s/GB). Hoy la espera de la
    GUI cubre el peor caso en ambos tamanos."""
    def final(gb):
        return wstate.scaled_backup_timeout_sec(int(gb * GB), wstate.FINAL_BACKUP_TIMEOUT_SEC)

    assert final(1.7) <= 450 < final(1.8)
    assert wstate.WORKER_JOIN_ON_SHUTDOWN_SEC + final(0.6) <= 450 < wstate.WORKER_JOIN_ON_SHUTDOWN_SEC + final(0.7)
    for gb in (0.7, 1.8, 2):
        espera_gui = config.WRAPPER_EXIT_TIMEOUT_SEC + wstate.shutdown_extra_sec(int(gb * GB))
        assert espera_gui >= _peor_caso_wrapper_sec(int(gb * GB)), gb
        assert espera_gui > 450, gb


# ── GUI: wrapper_exit_timeout_sec y las dos esperas de la fase 2 ────────

def test_wrapper_exit_timeout_sec_piso_con_mundo_chico(monkeypatch):
    monkeypatch.setattr(lifecycle, "_estimate_world_bytes", lambda: 0)
    assert lifecycle.wrapper_exit_timeout_sec() == config.WRAPPER_EXIT_TIMEOUT_SEC


def test_wrapper_exit_timeout_sec_escala_con_el_mundo(monkeypatch):
    monkeypatch.setattr(lifecycle, "_estimate_world_bytes", lambda: 2 * GB)
    assert lifecycle.wrapper_exit_timeout_sec() == config.WRAPPER_EXIT_TIMEOUT_SEC + 480
    assert lifecycle.wrapper_exit_timeout_sec() >= _peor_caso_wrapper_sec(2 * GB)


def test_wrapper_exit_timeout_sec_respeta_el_piso_configurado(monkeypatch):
    """Los tests (y quien afine config) pueden bajar/subir el piso."""
    monkeypatch.setattr(config, "WRAPPER_EXIT_TIMEOUT_SEC", 7)
    monkeypatch.setattr(lifecycle, "_estimate_world_bytes", lambda: 0)
    assert lifecycle.wrapper_exit_timeout_sec() == 7


def test_wrapper_exit_timeout_sec_tolera_fallo_al_estimar(monkeypatch):
    def _boom():
        raise OSError("sin acceso")

    monkeypatch.setattr(lifecycle, "_estimate_world_bytes", _boom)
    assert lifecycle.wrapper_exit_timeout_sec() == config.WRAPPER_EXIT_TIMEOUT_SEC


class _StdinOk:
    @staticmethod
    def write(_s):
        pass

    @staticmethod
    def flush():
        pass


class _ProcOk:
    stdin = _StdinOk()

    def poll(self):
        return None


def _espiar_fase2(monkeypatch, mundo_bytes):
    """Prepara un wrapper falso cuya fase 1 pasa y registra el timeout de la fase 2."""
    visto = {}
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_process", _ProcOk())
    monkeypatch.setattr(manager, "stop_requested", False)
    monkeypatch.setattr(manager.server_stopped_event, "wait", lambda timeout=None: True)

    def _wait(timeout=None):
        visto["timeout"] = timeout
        return False  # el wrapper "no termina": basta con ver el tope usado

    monkeypatch.setattr(manager, "wrapper_exit_event", types.SimpleNamespace(wait=_wait))
    monkeypatch.setattr(lifecycle, "_estimate_world_bytes", lambda: mundo_bytes)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))
    return visto, logs


def test_stop_and_wait_usa_el_tope_escalado(monkeypatch):
    visto, logs = _espiar_fase2(monkeypatch, 2 * GB)

    assert lifecycle.stop_and_wait("[T]") is False

    esperado = config.WRAPPER_EXIT_TIMEOUT_SEC + wstate.shutdown_extra_sec(2 * GB)
    assert visto["timeout"] == esperado
    assert visto["timeout"] > config.WRAPPER_EXIT_TIMEOUT_SEC
    # El mensaje de aborto informa el tope REAL, no el piso.
    assert any(f"{esperado}s" in x for x in logs), logs


def test_stop_and_wait_mundo_chico_conserva_el_piso(monkeypatch):
    visto, _ = _espiar_fase2(monkeypatch, 0)

    assert lifecycle.stop_and_wait("[T]") is False

    assert visto["timeout"] == config.WRAPPER_EXIT_TIMEOUT_SEC


def test_restart_wrapper_usa_el_tope_escalado(monkeypatch):
    visto, logs = _espiar_fase2(monkeypatch, 2 * GB)
    lanzados = []
    monkeypatch.setattr(lifecycle, "_launch_wrapper", lambda: lanzados.append(1) or ("starting", ""))

    lifecycle.restart_wrapper()

    esperado = config.WRAPPER_EXIT_TIMEOUT_SEC + wstate.shutdown_extra_sec(2 * GB)
    assert visto["timeout"] == esperado
    assert not lanzados, "no debe relanzar con el wrapper anterior aun vivo"
    assert any(f"{esperado}s" in x for x in logs), logs


def test_las_esperas_de_fase2_no_usan_el_piso_suelto():
    """Anti-drift: ninguna espera de fase 2 puede volver a leer
    config.WRAPPER_EXIT_TIMEOUT_SEC directamente (perderia la escala)."""
    src = Path(BASE_DIR, "gui_backend", "services", "lifecycle.py").read_text(encoding="utf-8")
    tras_helper = src.split("def wrapper_exit_timeout_sec")[1].split("def _launch_wrapper")[1]
    assert "config.WRAPPER_EXIT_TIMEOUT_SEC" not in tras_helper, (
        "una espera de fase 2 volvio a usar el piso fijo en lugar de wrapper_exit_timeout_sec()")
    assert tras_helper.count("wrapper_exit_timeout_sec()") == 2  # restart_wrapper + stop_and_wait


# ── Wrapper: publicacion del timeout del worker y join de cierre ───────

@pytest.fixture
def wstate_aislado(monkeypatch):
    """execute_backup_worker deja huellas en wstate; se restauran al terminar."""
    for nombre, valor in (
        ("active_worker_timeout_sec", 0), ("active_compress_process", None),
        ("backup_in_progress", False), ("backup_dispatched", False),
        ("watchdog_fired", False), ("save_query_ready_seen", False),
        ("backup_cancel_event", None), ("snapshot_retry_count", 0),
        ("snapshot_retry_at", 0.0), ("last_backup_completed_time", 0),
    ):
        monkeypatch.setattr(wstate, nombre, valor)
    monkeypatch.setattr(wb, "_send_command", lambda *a, **k: None)


class _FakeCompProc:
    def __init__(self, visto):
        self._visto = visto

    def is_alive(self):
        return False

    def join(self, timeout=None):
        self._visto["timeout"] = timeout
        self._visto["publicado"] = wstate.active_worker_timeout_sec

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def test_worker_publica_su_timeout_y_lo_limpia_al_terminar(monkeypatch, wstate_aislado):
    visto = {}
    fake = _FakeCompProc(visto)
    monkeypatch.setattr(wb.subprocess, "Popen", lambda *a, **k: object())
    monkeypatch.setattr(wb, "_WorkerProcess", lambda proc: fake)

    wb.execute_backup_worker(file_snapshot=[("db/a.ldb", 4 * GB)], cancel_event=None)

    esperado = wstate.scaled_backup_timeout_sec(4 * GB, wstate.WORKER_COMPRESSION_TIMEOUT_SEC)
    assert visto["timeout"] == esperado
    # Mientras el worker corre, el cierre puede leer su timeout real...
    assert visto["publicado"] == esperado
    assert wstate.worker_join_timeout_sec(visto["publicado"]) > esperado
    # ...y al terminar no queda un timeout ajeno para el siguiente cierre.
    assert wstate.active_worker_timeout_sec == 0


def test_worker_limpia_el_timeout_si_no_pudo_lanzarse(monkeypatch, wstate_aislado):
    def _popen_falla(*a, **k):
        raise OSError("no se pudo lanzar")

    monkeypatch.setattr(wb.subprocess, "Popen", _popen_falla)

    wb.execute_backup_worker(file_snapshot=[("db/a.ldb", 4 * GB)], cancel_event=None)

    assert wstate.active_worker_timeout_sec == 0


def test_cierre_del_wrapper_usa_el_join_escalado():
    """Anti-drift textual del `finally` de __main__ (no es invocable en un test):
    el join del worker caliente usa wstate.worker_join_timeout_sec con el
    timeout publicado, no la constante fija."""
    src = Path(BASE_DIR, "server_wrapper.py").read_text(encoding="utf-8")
    hasta_paso2 = src.split('if __name__ == "__main__":')[1].split("Paso 2")[0]
    assert "worker_timeout = wstate.active_worker_timeout_sec" in hasta_paso2
    assert "wstate.worker_join_timeout_sec(worker_timeout)" in hasta_paso2
    assert "current_worker.join(timeout=worker_join_timeout)" in hasta_paso2
    assert "join(timeout=wstate.WORKER_JOIN_ON_SHUTDOWN_SEC)" not in hasta_paso2
