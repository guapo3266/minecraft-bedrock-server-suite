"""Ciclo de backup caliente y worker de compresion del wrapper."""

import multiprocessing
import os
import subprocess
import sys
import time

import auto_backup
import wrapper_events
import wrapper_state as wstate

from console_lang import L


_command_sender = None


def set_command_sender(sender):
    """Conecta el worker con send_command sin importar la fachada al cargar."""
    global _command_sender
    _command_sender = sender


def _send_command(cmd):
    """Resuelve el emisor de comandos despues de cargar la fachada."""
    if _command_sender is not None:
        _command_sender(cmd)
        return
    import server_wrapper

    server_wrapper.send_command(cmd)


def mark_corrupt_zip(zip_filepath, reason="CORRUPTO"):
    """Renombra un .zip marcado, de forma idempotente."""
    if zip_filepath and isinstance(zip_filepath, str) and os.path.exists(zip_filepath):
        base = zip_filepath.rsplit(".zip", 1)[0]
        if base.endswith("_" + reason):
            return
        corrupt_name = f"{base}_{reason}.zip"
        try:
            os.rename(zip_filepath, corrupt_name)
            print(L(f"[Worker] Backup marcado por desincronización: {os.path.basename(corrupt_name)}", f"[Worker] Backup flagged for desync: {os.path.basename(corrupt_name)}"))
        except Exception as e:
            print(L(f"[Worker] No se pudo renombrar el backup {zip_filepath}: {e}", f"[Worker] Could not rename backup {zip_filepath}: {e}"))


def _is_snapshot_failure(error_msg):
    """True si el error del worker merece reintento inmediato."""
    msg = (error_msg or "").lower()
    if "snapshot" not in msg:
        return False
    if "cancelled" in msg or "cancelado" in msg:
        return False
    if "exceeds the" in msg or "excede el limite" in msg:
        return False
    return True


def _snapshot_retry_delay(attempt):
    """Backoff exponencial entre reintentos de snapshot."""
    return min(
        wstate.RETRY_BACKOFF_MAX_SEC,
        wstate.RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1)),
    )


class _FileCancelEvent:
    """Sustituto de multiprocessing.Event basado en un archivo marcador."""
    def __init__(self, path):
        self.path = path
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def is_set(self):
        return os.path.exists(self.path)

    def set(self):
        try:
            open(self.path, "w").close()
        except Exception:
            pass

    def clear(self):
        try:
            os.remove(self.path)
        except Exception:
            pass


def _force_kill_compress_process(proc):
    """Mata el proceso de compresion y reemplaza el lock IPC."""
    if not proc or not proc.is_alive():
        return

    with wstate.state_lock:
        if wstate.active_compress_process is not proc:
            return

        try:
            proc.kill()
            proc.join()
        except Exception as e:
            print(L(f"[Wrapper] Error forzando kill del proceso de compresión: {e}", f"[Wrapper] Error forcing kill of compression process: {e}"))

        wstate.backup_ipc_lock = multiprocessing.Lock()
        wstate.active_compress_process = None

        # El worker muerto pudo dejar un .tmp a medias; se limpia ya bajo el lock.
        try:
            import glob as _glob
            for orphan in _glob.glob(os.path.join(auto_backup.BACKUP_DIR, "*.tmp")):
                try:
                    os.remove(orphan)
                    print(L(f"[Wrapper] Limpieza: eliminado {os.path.basename(orphan)} tras kill.", f"[Wrapper] Cleanup: removed {os.path.basename(orphan)} after kill."))
                except Exception:
                    pass
        except Exception:
            pass


def execute_backup_worker(file_snapshot=None, cancel_event=None):
    """Hilo efimero que orquesta el proceso de compresion de Bedrock."""
    outcome = "exception"
    try:
        print(L("[Worker] Iniciando compresion de archivos en proceso separado (subprocess)...", "[Worker] Starting compression in a separate process (subprocess)..."))
        wrapper_events._emit_event(
            "backup_compress_started",
            files=len(file_snapshot) if file_snapshot else 0,
        )

        import json as _json
        _base = os.path.dirname(os.path.abspath(__file__))
        _stamp = int(time.time() * 1000)
        _nonce = os.urandom(4).hex()
        _tmpdir = os.environ.get("TEMP", ".")
        _snap_path = os.path.join(_tmpdir, "bw_snap_%d_%s.json" % (_stamp, _nonce))
        _marker = os.path.join(_tmpdir, "bw_cancel_%d_%s.mark" % (_stamp, _nonce))
        _result = os.path.join(_tmpdir, "bw_result_%d_%s.json" % (_stamp, _nonce))
        _worker = os.path.join(_base, "backup_worker.py")

        try:
            with open(_snap_path, "w", encoding="utf-8") as _f:
                _json.dump(file_snapshot, _f, ensure_ascii=False)
            if cancel_event is not None and hasattr(cancel_event, "path"):
                _marker = cancel_event.path
            comp_proc = subprocess.Popen(
                [sys.executable, "-u", _worker, _snap_path, _marker, _result],
                cwd=_base,
                stdin=subprocess.DEVNULL,
            )
            comp_proc.is_alive = lambda: comp_proc.poll() is None

            def _join(timeout=None):
                try:
                    comp_proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    pass

            comp_proc.join = _join
        except Exception as e:
            print(L(f"[Worker] [WARN] No se pudo lanzar el worker: {e}", f"[Worker] [WARN] Could not launch the worker: {e}"))
            for _p in (_snap_path, _marker, _result):
                try:
                    os.remove(_p)
                except Exception:
                    pass
            with wstate.state_lock:
                wstate.backup_in_progress = False
                wstate.backup_dispatched = False
                wstate.save_query_ready_seen = False
                wstate.backup_cancel_event = None
                wstate.watchdog_fired = True
                wstate.last_backup_completed_time = time.time()
                wstate.snapshot_retry_count = 0
                wstate.snapshot_retry_at = 0.0
            _send_command("save resume")
            outcome = "launch_error"
            return

        with wstate.state_lock:
            wstate.active_compress_process = comp_proc

        comp_proc.join(timeout=wstate.WORKER_COMPRESSION_TIMEOUT_SEC)

        # --- CASO A: Compresion excedio el tiempo maximo ---
        if comp_proc.is_alive():
            print(L(f"[Worker] [WARN] Timeout de compresion ({wstate.WORKER_COMPRESSION_TIMEOUT_SEC}s).", f"[Worker] [WARN] Compression timeout ({wstate.WORKER_COMPRESSION_TIMEOUT_SEC}s)."))
            print(L("[Worker]          Terminando proceso de compresion...", "[Worker]          Terminating compression process..."))

            _force_kill_compress_process(comp_proc)

            with wstate.state_lock:
                was_watchdog = wstate.watchdog_fired
                wstate.watchdog_fired = True

            if cancel_event:
                cancel_event.set()

            if not was_watchdog:
                _send_command("save resume")

            with wstate.state_lock:
                wstate.backup_in_progress = False
                wstate.backup_dispatched = False
                wstate.save_query_ready_seen = False
                wstate.backup_cancel_event = None
                wstate.last_backup_completed_time = time.time()
                wstate.snapshot_retry_count = 0
                wstate.snapshot_retry_at = 0.0

            for _p in (_snap_path, _marker, _result):
                try:
                    os.remove(_p)
                except Exception:
                    pass
            outcome = "timeout"
            return

        # --- CASO B: Compresion termino a tiempo ---
        with wstate.state_lock:
            wstate.active_compress_process = None

        try:
            with open(_result, "r", encoding="utf-8") as _f:
                result = _json.load(_f)
        except Exception:
            result = {"zip": None, "error": L("El proceso termino sin devolver un resultado", "The process exited without returning a result")}
        for _p in (_snap_path, _marker, _result):
            try:
                os.remove(_p)
            except Exception:
                pass
        retry_soon = _is_snapshot_failure(result.get("error"))
        if result["error"]:
            print(L(f"[Worker] [ERROR] Falló la compresión: {result['error']}", f"[Worker] [ERROR] Compression failed: {result['error']}"))
        elif not result["zip"]:
            print(L("[Worker] [ERROR] El backup no produjo un ZIP válido.", "[Worker] [ERROR] The backup did not produce a valid ZIP."))

        with wstate.state_lock:
            was_watchdog = wstate.watchdog_fired

        if was_watchdog:
            print(L("[Worker] El watchdog ya había reanudado escrituras previamente.", "[Worker] The watchdog had already resumed writes earlier."))
            outcome = "watchdog"
            if result["zip"]:
                mark_corrupt_zip(result["zip"], "POSIBLEMENTE_CORRUPTO")
        else:
            if result["zip"]:
                print(L("[Worker] Compresión exitosa. Reanudando escritura (save resume)...", "[Worker] Compression successful. Resuming writes (save resume)..."))
                outcome = "success"
                wrapper_events._emit_event("backup_ok", zip=result["zip"])
            else:
                print(L("[Worker] Reanudando escritura tras fallo de backup (save resume)...", "[Worker] Resuming writes after failed backup (save resume)..."))
                outcome = "failed"
            _send_command("save resume")

        with wstate.state_lock:
            wstate.backup_in_progress = False
            wstate.backup_dispatched = False
            wstate.watchdog_fired = False
            wstate.save_query_ready_seen = False
            wstate.backup_cancel_event = None
            if retry_soon:
                # Snapshot incompleto: reintentar con backoff exponencial.
                wstate.snapshot_retry_count += 1
                if wstate.snapshot_retry_count >= wstate.MAX_CONSECUTIVE_SNAPSHOT_RETRIES:
                    print(L(f"[Worker] {wstate.snapshot_retry_count} reintentos consecutivos de snapshot fallidos; "
                          "se espera el proximo intervalo normal de backup.",
                          f"[Worker] {wstate.snapshot_retry_count} consecutive snapshot retries failed; "
                          "waiting for the next normal backup interval."))
                    wstate.snapshot_retry_count = 0
                    wstate.snapshot_retry_at = 0.0
                else:
                    delay = _snapshot_retry_delay(wstate.snapshot_retry_count)
                    wstate.snapshot_retry_at = time.time() + delay
                    print(L(f"[Worker] Snapshot incompleto: reintento en {delay}s (intento {wstate.snapshot_retry_count}).", f"[Worker] Incomplete snapshot: retrying in {delay}s (attempt {wstate.snapshot_retry_count})."))
                wstate.last_backup_completed_time = time.time()
            else:
                wstate.snapshot_retry_count = 0
                wstate.snapshot_retry_at = 0.0
                wstate.last_backup_completed_time = time.time()

    except Exception as e:
        print(L(f"[Worker] [WARN] Excepcion en worker de backup: {type(e).__name__}: {e}", f"[Worker] [WARN] Exception in backup worker: {type(e).__name__}: {e}"))
        print(L("[Worker]          Limpiando estado del worker...", "[Worker]          Cleaning up worker state..."))
        outcome = "exception"
        with wstate.state_lock:
            wstate.backup_in_progress = False
            wstate.backup_dispatched = False
            wstate.save_query_ready_seen = False
            wstate.backup_cancel_event = None
            wstate.watchdog_fired = True
            wstate.last_backup_completed_time = time.time()
            wstate.snapshot_retry_count = 0
            wstate.snapshot_retry_at = 0.0
        _send_command("save resume")

        with wstate.state_lock:
            wstate.active_compress_process = None
    finally:
        # Marcador de FIN incondicional del ciclo de compresion.
        print(L("[Worker] Backup finalizado", "[Worker] Backup finished"))
        wrapper_events._emit_event("backup_finished", outcome=outcome)


def _begin_manual_hot_backup():
    """Inicia un ciclo de backup en caliente manual."""
    with wstate.state_lock:
        if wstate.backup_in_progress:
            return False
        wstate.backup_in_progress = True
        wstate.backup_dispatched = False
        wstate.watchdog_fired = False
        wstate.save_query_ready_seen = False
        wstate.backup_cancel_event = None
        wstate.save_hold_timestamp = time.time()
        wstate.last_save_snapshot = []
        wstate.expecting_list_names = False
        wstate.snapshot_retry_at = 0.0
    return True
