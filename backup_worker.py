# -*- coding: utf-8 -*-
"""Worker de compresion de backups en caliente (proceso separado).

Se lanza con subprocess.Popen desde server_wrapper.execute_backup_worker().
Sustituye al hijo de multiprocessing.spawn: el bootstrap de spawn se colgaba
50-120s+ cuando el padre era el wrapper con BDS corriendo (el hijo quedaba
bloqueado en la lectura del pipe de arranque de spawn). Con subprocess el
arranque es inmediato y la compresion real tarda ~1-3s en un mundo de 50MB.

Uso: python backup_worker.py <snapshot.pkl> <cancel_marker> <result.pkl>
- snapshot.pkl: lista de tuplas (rel_path, byte_length) del save query.
- cancel_marker: si este archivo existe, el backup se aborta de forma
  cooperativa (misma semantica que el cancel_event de multiprocessing).
- result.pkl: diccionario {"zip": ruta_o_False, "error": str|None}.

El worker NO comparte locks con el wrapper: usa el lock interno de
auto_backup (_backup_lock). El wrapper garantiza que no hay backups
concurrentes via backup_in_progress + join antes del backup de cierre.
"""
import os
import sys
import time
import pickle


class _FileCancel:
    """Cancel_event compatible (is_set) basado en un archivo marcador."""

    def __init__(self, path):
        self.path = path

    def is_set(self):
        return os.path.exists(self.path)


def _main():
    snap_path, marker, result_path = sys.argv[1:4]

    with open(snap_path, "rb") as f:
        file_snapshot = pickle.load(f)

    import auto_backup  # import tardio: solo aqui hace falta

    t0 = time.time()
    try:
        zip_path = auto_backup.create_backup(
            "periodico",
            file_snapshot=file_snapshot,
            cancel_event=_FileCancel(marker),
        )
        result = {"zip": zip_path, "error": None}
    except Exception as e:
        # create_backup en modo snapshot SIEMPRE lanza en un fallo (nunca
        # devuelve False); el prefijo "Snapshot:" anota el contexto para que
        # el wrapper distinga (reintento inmediato) de los fallos operativos
        # (cancelacion, limite de tamano) que no merecen reintento.
        result = {"zip": None, "error": "Snapshot: %s" % e}

    try:
        with open(result_path, "wb") as f:
            pickle.dump(result, f)
    except Exception as e:
        result = {"zip": None, "error": "No se pudo escribir el resultado: %s" % e}
        try:
            with open(result_path, "wb") as f:
                pickle.dump(result, f)
        except Exception:
            pass

    if result["zip"]:
        print("[Worker] Compresion OK en %.1fs -> %s" % (time.time() - t0, result["zip"]))
    else:
        print("[Worker] Compresion fallida: %s" % result["error"])


if __name__ == "__main__":
    _main()