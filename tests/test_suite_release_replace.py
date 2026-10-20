# -*- coding: utf-8 -*-
"""write_json y _atomic_copy reintentan os.replace ante un lector abierto (2026-10-20).

En Windows, os.replace falla con acceso denegado mientras otro proceso tiene
abierto el destino. La QA de la entrega 2.1.1 lo reprodujo: un sondeo de
progress.json coincidió con una escritura y la actualización terminó en
"error". La GUI lee ese archivo en cada GET /api/suite_update y el antivirus
puede abrir los archivos recién escritos.
"""
import json
import sys
import threading

import pytest

import suite_release as release


def _abrir_y_cerrar_luego(path, segundos=0.3):
    lector = path.open("rb")  # sin FILE_SHARE_DELETE, igual que read_text()
    cerrador = threading.Timer(segundos, lector.close)
    cerrador.start()
    return lector, cerrador


@pytest.mark.skipif(sys.platform != "win32", reason="el bloqueo por lector abierto es propio de Windows")
def test_sin_reintento_un_lector_abierto_bloquea_el_reemplazo(tmp_path, monkeypatch):
    """Fija la premisa: sin reintentos, Windows deniega el reemplazo."""
    monkeypatch.setattr(release, "REPLACE_ATTEMPTS", 1)
    destino = tmp_path / "progress.json"
    release.write_json(destino, {"phase": "downloading"})
    lector = destino.open("rb")
    try:
        with pytest.raises(PermissionError):
            release.write_json(destino, {"phase": "verifying"})
    finally:
        lector.close()
    assert [p.name for p in tmp_path.iterdir()] == ["progress.json"]


def test_write_json_espera_a_que_se_cierre_un_lector(tmp_path):
    destino = tmp_path / "progress.json"
    release.write_json(destino, {"phase": "downloading"})
    lector, cerrador = _abrir_y_cerrar_luego(destino)
    try:
        release.write_json(destino, {"phase": "verifying"})
    finally:
        cerrador.join()
        lector.close()
    assert json.loads(destino.read_text(encoding="utf-8")) == {"phase": "verifying"}
    assert [p.name for p in tmp_path.iterdir()] == ["progress.json"]


def test_atomic_copy_espera_a_un_lector_del_destino(tmp_path):
    origen = tmp_path / "nuevo.py"
    origen.write_bytes(b"nuevo")
    destino = tmp_path / "app" / "modulo.py"
    destino.parent.mkdir()
    destino.write_bytes(b"viejo")
    lector, cerrador = _abrir_y_cerrar_luego(destino)
    try:
        release._atomic_copy(origen, destino)
    finally:
        cerrador.join()
        lector.close()
    assert destino.read_bytes() == b"nuevo"
    assert [p.name for p in destino.parent.iterdir()] == ["modulo.py"]


def test_reintentos_agotados_propagan_el_error_y_limpian_el_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "REPLACE_ATTEMPTS", 3)
    monkeypatch.setattr(release, "REPLACE_DELAY_SEC", 0)
    llamadas = []

    def siempre_denegado(src, dst):
        llamadas.append(dst)
        raise PermissionError(13, "Acceso denegado")

    monkeypatch.setattr(release.os, "replace", siempre_denegado)
    with pytest.raises(PermissionError):
        release.write_json(tmp_path / "progress.json", {"phase": "error"})
    assert len(llamadas) == 3
    assert list(tmp_path.iterdir()) == []


def test_otros_errores_no_se_reintentan(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "REPLACE_DELAY_SEC", 0)
    llamadas = []

    def sin_destino(src, dst):
        llamadas.append(dst)
        raise FileNotFoundError(2, "No existe")

    monkeypatch.setattr(release.os, "replace", sin_destino)
    with pytest.raises(FileNotFoundError):
        release.write_json(tmp_path / "progress.json", {"phase": "error"})
    assert len(llamadas) == 1
