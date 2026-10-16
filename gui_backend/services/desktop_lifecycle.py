"""Cierre de la ventana portable: mantiene op_lock hasta decidir la salida.

No incorpora endpoints ni escribe al stdin del wrapper: reutiliza lifecycle.
Un fallo de backup mantiene la exclusión para impedir un start mientras se
ofrecen Reintentar/Salir. Nunca se fuerza el cierre de un wrapper vivo.
"""

import json
import threading

import auto_backup
import wrapper_state
from console_lang import L
from gui_backend.services import lifecycle, external_probe
from gui_backend.state import manager


def read_final_result(events_file):
    result = None
    if not events_file:
        return result
    try:
        with open(events_file, encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("event") == "final_backup_finished":
                    result = event
    except OSError:
        pass
    return result


class DesktopCloseCoordinator:
    def __init__(self):
        self.holding = False
        self.gate = threading.Lock()
        self.backup_failed = False

    def release(self):
        if self.holding:
            self.holding = False
            manager.op_lock.release()

    def close(self, progress=lambda stage: None, retry=False):
        if not self.gate.acquire(blocking=False):
            return {"state": "busy"}
        try:
            if not self.holding:
                progress("waiting")
                manager.op_lock.acquire()
                self.holding = True
            with manager.lock:
                process = manager.wrapper_process
                events_file = manager.events_file
                running = manager.is_running
            if retry:
                if running or (process is not None and process.poll() is None):
                    raise RuntimeError(L("El wrapper sigue activo; no se puede repetir un backup en frío.", "The wrapper is still active; a cold backup cannot be retried."))
                is_external, _ = external_probe.detect_external_bds()
                if is_external:
                    return self._backup_error(L("Otra instancia está usando esta instalación. Detén ese servidor antes de reintentar el backup.", "Another instance is using this installation. Stop that server before retrying the backup."))
                progress("backup")
                backup = auto_backup.create_backup("cierre_reintento")
                if not backup:
                    return self._backup_error(L("No se pudo crear un ZIP válido. Revisa los registros y el espacio disponible.", "A valid ZIP could not be created. Check the logs and free disk space."))
                self.backup_failed = False
                return {"state": "ready", "zip": str(backup)}
            if running or (process is not None and process.poll() is None):
                # El wrapper puede esperar un worker caliente y un backup final,
                # ambos con topes escalados de hasta BACKUP_TIMEOUT_MAX_SEC.
                maximum = 2 * wrapper_state.BACKUP_TIMEOUT_MAX_SEC + 120
                if not lifecycle.stop_and_wait("[SuiteMinecraft]", on_progress=progress, wrapper_timeout=maximum):
                    self.release()
                    return {"state": "stop_error", "message": L("No se pudo completar el apagado. Revisa el panel y los registros.", "Shutdown could not be completed. Check the dashboard and logs.")}
                if process is not None and process.poll() is None:
                    self.release()
                    return {"state": "stop_error", "message": L("El wrapper todavía está activo. La aplicación permanecerá abierta.", "The wrapper is still active. The application will stay open.")}
                outcome = read_final_result(events_file)
                if not outcome or outcome.get("success") is not True:
                    return self._backup_error((outcome or {}).get("error") or L("No se confirmó un backup final válido.", "A valid final backup was not confirmed."))
                return {"state": "ready", "zip": outcome.get("zip")}
            # También se informa un backup fallido tras un stop manual del panel.
            outcome = read_final_result(events_file)
            if outcome and outcome.get("success") is not True:
                return self._backup_error(outcome.get("error") or L("El último backup final falló.", "The last final backup failed."))
            return {"state": "ready"}
        except Exception as exc:
            if retry:
                return self._backup_error(str(exc))
            self.release()
            return {"state": "stop_error", "message": str(exc)}
        finally:
            self.gate.release()

    def _backup_error(self, message):
        self.backup_failed = True
        manager.add_log("[SuiteMinecraft] " + message, "error")
        return {"state": "backup_error", "message": message}
