# -*- coding: utf-8 -*-
"""Ramas de bds_update sin red: limites de descarga, recuperacion y versiones."""

import itertools
import zipfile

import pytest

import gui_backend.services.bds_update as bu

_MAX = 400 * 1024 * 1024


class _Resp:
    def __init__(self, headers=None, chunks=()):
        self.status_code = 200
        self.headers = headers or {}
        self._chunks = chunks

    def iter_content(self, chunk_size=8192):
        return iter(self._chunks)


def _preparar(tmp_path, monkeypatch, resp):
    monkeypatch.setattr(bu.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(bu, "_fetch_latest_bedrock_download",
                        lambda: ("https://x/bedrock-server-1.2.3.4.zip", "1.2.3.4"))
    monkeypatch.setattr(bu.requests, "get", lambda *a, **k: resp)
    logs = []
    return logs


def _log(logs):
    return lambda msg, tipo=None: logs.append(msg)


def test_download_rechaza_content_length_excesivo(tmp_path, monkeypatch):
    logs = _preparar(tmp_path, monkeypatch,
                     _Resp(headers={"Content-Length": str(_MAX + 1)}))

    ok, version = bu._download_and_install_bds(log_fn=_log(logs))

    assert ok is False and version is None
    assert any("demasiado grande" in m or "too large" in m for m in logs)
    assert not (tmp_path / "bds_update.zip").exists()


def test_download_rechaza_stream_que_excede_el_limite(tmp_path, monkeypatch):
    chunk = b"x" * (1024 * 1024)
    logs = _preparar(tmp_path, monkeypatch,
                     _Resp(chunks=itertools.repeat(chunk, 401)))

    ok, _version = bu._download_and_install_bds(log_fn=_log(logs))

    assert ok is False
    assert any("límite de 400 MB" in m or "400 MB limit" in m for m in logs)
    assert not (tmp_path / "bds_update.zip").exists()


def test_download_sin_content_length_reporta_progreso_y_falla_zip_invalido(tmp_path, monkeypatch):
    chunk = b"x" * (1024 * 1024)
    logs = _preparar(tmp_path, monkeypatch,
                     _Resp(chunks=itertools.repeat(chunk, 12)))

    with pytest.raises(zipfile.BadZipFile):
        bu._download_and_install_bds(log_fn=_log(logs))

    assert any("Descargando..." in m or "Downloading..." in m for m in logs)
    assert not (tmp_path / "bds_update.zip").exists()


def test_recover_update_manifiesto_invalido_conserva_dir(tmp_path):
    prev = tmp_path / "bds_update_prev_x"
    prev.mkdir()
    (prev / bu._UPDATE_MANIFEST_NAME).write_text("{no-json", encoding="utf-8")

    bu.recover_interrupted_updates(str(tmp_path))

    assert prev.exists(), "un resguardo ilegible no debe borrarse"


def test_recover_update_entrada_peligrosa_conserva_dir(tmp_path):
    prev = tmp_path / "bds_update_prev_y"
    prev.mkdir()
    (prev / bu._UPDATE_MANIFEST_NAME).write_text(
        '[{"path": "../evil.dll", "had_previous": false}]', encoding="utf-8")

    bu.recover_interrupted_updates(str(tmp_path))

    assert prev.exists(), "una entrada con traversal no debe aplicarse"


@pytest.mark.parametrize("version,esperado", [
    ("1.21.30.03", (1, 21, 30, 3)),
    ("1.2", (1, 2, 0, 0)),
    ("a.b.c.d", (0, 0, 0, 0)),
    ("1.2.3.4.5", (1, 2, 3, 4)),
])
def test_version_tuple(version, esperado):
    assert bu._version_tuple(version) == esperado


def test_resolve_update_root_zip_plano(tmp_path):
    (tmp_path / "bedrock_server.exe").write_bytes(b"x")
    assert bu._resolve_update_root(str(tmp_path)) == str(tmp_path)


def test_resolve_update_root_carpeta_unica(tmp_path):
    sub = tmp_path / "bedrock-server-1.2.3.4"
    sub.mkdir()
    (sub / "bedrock_server.exe").write_bytes(b"x")
    assert bu._resolve_update_root(str(tmp_path)) == str(sub)


def test_resolve_update_root_estructura_ambigua_falla(tmp_path):
    sub = tmp_path / "x"
    sub.mkdir()
    (sub / "bedrock_server.exe").write_bytes(b"x")
    (tmp_path / "archivo.txt").write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError):
        bu._resolve_update_root(str(tmp_path))


def test_resolve_update_root_sin_exe_falla(tmp_path):
    with pytest.raises(RuntimeError):
        bu._resolve_update_root(str(tmp_path))


def test_download_con_content_length_reporta_porcentaje(tmp_path, monkeypatch):
    chunk = b"x" * (1024 * 1024)
    total = 12 * len(chunk)
    logs = _preparar(tmp_path, monkeypatch, _Resp(
        headers={"Content-Length": str(total)},
        chunks=itertools.repeat(chunk, 12),
    ))

    with pytest.raises(zipfile.BadZipFile):
        bu._download_and_install_bds(log_fn=_log(logs))

    assert any("%" in m for m in logs), logs


def test_download_ignora_entrada_insegura_y_aplica(tmp_path, monkeypatch):
    import io

    logs = []
    monkeypatch.setattr(bu.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(bu, "PREVIOUS_VERSION_DIR", str(tmp_path / "bds_previous"))
    monkeypatch.setattr(bu, "_fetch_latest_bedrock_download",
                        lambda: ("https://x/bedrock-server-1.2.3.4.zip", "1.2.3.4"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", b"malo")
        zf.writestr("bedrock_server.exe", b"exe-binario")
    contenido = buf.getvalue()

    class _RespZip:
        status_code = 200
        headers = {"Content-Length": str(len(contenido))}

        def iter_content(self, chunk_size=8192):
            for i in range(0, len(contenido), chunk_size):
                yield contenido[i:i + chunk_size]

    monkeypatch.setattr(bu.requests, "get", lambda *a, **k: _RespZip())

    ok, version = bu._download_and_install_bds(log_fn=_log(logs))

    assert ok is True and version == "1.2.3.4"
    assert (tmp_path / "bedrock_server.exe").read_bytes() == b"exe-binario"
    assert any("insegura" in m.lower() or "unsafe" in m.lower() for m in logs), logs


def test_read_previous_version_tolera_listdir_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(bu, "PREVIOUS_VERSION_DIR", str(tmp_path))
    (tmp_path / "x.dll").write_text("x", encoding="utf-8")

    def _listdir_falla(*_a, **_k):
        raise OSError("sin acceso")

    monkeypatch.setattr(bu.os, "listdir", _listdir_falla)

    assert bu.read_previous_version() == (False, None)
