"""Regresiones de la revision manual; datos temporales y red simulada.

No ejecutadas durante la ronda original, por pedido del usuario.
"""

import asyncio
import json
import os
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import auto_backup
import restore_backup
import restore_core
import server_properties
import zip_safety
from gui_backend.routers import setup
from gui_backend.services import bds_update as bu


URL = "https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-1.2.3.4.zip"


def _manifest(prev, entries):
    prev.mkdir(exist_ok=True)
    (prev / bu._UPDATE_MANIFEST_NAME).write_text(json.dumps(entries), encoding="utf-8")


@pytest.mark.parametrize("movidos", [0, 1, 2])
def test_recuperacion_bds_antes_o_durante_resguardo_conserva_originales(tmp_path, movidos):
    prev = tmp_path / "bds_update_prev_interrumpido"
    prev.mkdir()
    for i, name in enumerate(("a.dll", "b.dll")):
        parent = prev if i < movidos else tmp_path
        (parent / name).write_bytes(name.encode())
    _manifest(prev, [{"path": n, "had_previous": True} for n in ("a.dll", "b.dll")])

    bu.recover_interrupted_updates(str(tmp_path))

    assert (tmp_path / "a.dll").read_bytes() == b"a.dll"
    assert (tmp_path / "b.dll").read_bytes() == b"b.dll"
    assert not prev.exists()


def test_recuperacion_bds_puede_reintentarse_tras_fallo_parcial(tmp_path, monkeypatch):
    prev = tmp_path / "bds_update_prev_interrumpido"
    prev.mkdir()
    for name in ("a.dll", "b.dll"):
        (prev / name).write_bytes(b"original")
        (tmp_path / name).write_bytes(b"nuevo")
    (tmp_path / "nuevo.dll").write_bytes(b"nuevo")
    _manifest(prev, [
        {"path": "a.dll", "had_previous": True},
        {"path": "b.dll", "had_previous": True},
        {"path": "nuevo.dll", "had_previous": False},
    ])
    real_replace = bu.os.replace

    def _bloquear_b(src, dst):
        if os.fspath(src) == str(prev / "b.dll"):
            raise PermissionError("bloqueado")
        return real_replace(src, dst)

    with monkeypatch.context() as mp:
        mp.setattr(bu.os, "replace", _bloquear_b)
        bu.recover_interrupted_updates(str(tmp_path))
    assert prev.exists()
    assert not (prev / "a.dll").exists()

    bu.recover_interrupted_updates(str(tmp_path))
    bu.recover_interrupted_updates(str(tmp_path))

    assert (tmp_path / "a.dll").read_bytes() == b"original"
    assert (tmp_path / "b.dll").read_bytes() == b"original"
    assert not (tmp_path / "nuevo.dll").exists()
    assert not prev.exists()


def test_manifiesto_invalido_no_consume_entradas_previas(tmp_path):
    prev = tmp_path / "bds_update_prev_invalido"
    (tmp_path / "nuevo.dll").write_bytes(b"intacto")
    _manifest(prev, [
        {"path": "nuevo.dll", "had_previous": False},
        {"path": "../fuera.dll", "had_previous": False},
    ])

    bu.recover_interrupted_updates(str(tmp_path))

    assert (tmp_path / "nuevo.dll").read_bytes() == b"intacto"
    assert prev.exists()


def test_original_y_resguardo_ausentes_conservan_manifiesto(tmp_path):
    prev = tmp_path / "bds_update_prev_incompleto"
    _manifest(prev, [{"path": "ausente.dll", "had_previous": True}])

    bu.recover_interrupted_updates(str(tmp_path))

    assert (prev / bu._UPDATE_MANIFEST_NAME).is_file()


def test_rollback_bds_fallido_conserva_resguardo_recuperable(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    for name in ("a.dll", "b.dll"):
        (tmp_path / name).write_bytes(b"original")
        (staging / name).write_bytes(b"nuevo")
    real_replace = bu.os.replace

    def _fallar_aplicacion_y_rollback(src, dst):
        src = os.fspath(src)
        if src == str(staging / "b.dll") or ("bds_update_prev_" in src and src.endswith(".dll")):
            raise PermissionError("bloqueado")
        return real_replace(src, dst)

    with monkeypatch.context() as mp:
        mp.setattr(bu.os, "replace", _fallar_aplicacion_y_rollback)
        with pytest.raises(PermissionError):
            bu._apply_staged_update(str(staging), str(tmp_path), set(), set())
    prevs = list(tmp_path.glob("bds_update_prev_*"))
    assert len(prevs) == 1
    assert (prevs[0] / "a.dll").read_bytes() == b"original"
    assert (prevs[0] / "b.dll").read_bytes() == b"original"

    bu.recover_interrupted_updates(str(tmp_path))
    assert (tmp_path / "a.dll").read_bytes() == b"original"
    assert (tmp_path / "b.dll").read_bytes() == b"original"


@pytest.mark.parametrize("url", [
    URL.replace("www.minecraft.net", "evil.example"),
    URL.replace("www.minecraft.net", "www.minecraft.net.evil.example"),
    URL.replace("https://", "http://"),
    URL.replace("www.minecraft.net", "127.0.0.1"),
    URL.replace("www.minecraft.net", "www.minecraft.net:8443"),
    URL.replace("www.minecraft.net", "user@www.minecraft.net"),
    URL + "#fragmento", URL + "\n", "https://www.minecraft.net/otro.zip",
])
def test_descarga_rechaza_urls_ajenas_o_ambiguas(url):
    assert not bu._is_official_bds_url(url)


@pytest.mark.parametrize("url", [URL, URL + "?token=abc", URL.replace("www.minecraft.net", "minecraft.net:443")])
def test_descarga_admite_hosts_oficiales(url):
    assert bu._is_official_bds_url(url)


class _Response:
    def __init__(self, status=200, location=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.closed = False

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size=8192):
        return iter([b"zip invalido"])


def test_redireccion_ajena_no_se_contacta_y_cierra_respuesta(monkeypatch):
    response = _Response(302, URL.replace("www.minecraft.net", "evil.example"))
    contacted = []

    def _get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        contacted.append(url)
        return response

    monkeypatch.setattr(bu.requests, "get", _get)
    with pytest.raises(ValueError):
        bu._open_bds_download(URL)

    assert contacted == [URL]
    assert response.closed


def test_redireccion_relativa_oficial_se_valida_y_cierra(monkeypatch):
    redirect = _Response(302, "bedrock-server-1.2.3.4.zip?token=abc")
    final = _Response()
    responses = iter([redirect, final])
    contacted = []

    def _get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        contacted.append(url)
        return next(responses)

    monkeypatch.setattr(bu.requests, "get", _get)
    assert bu._open_bds_download(URL) is final
    assert contacted == [URL, URL + "?token=abc"]
    assert redirect.closed
    assert not final.closed  # el consumidor es quien cierra el stream final


def test_url_ajena_se_rechaza_antes_de_contactar_red(monkeypatch):
    contacted = []
    monkeypatch.setattr(bu.requests, "get", lambda *a, **k: contacted.append(a))

    with pytest.raises(ValueError):
        bu._open_bds_download(URL.replace("www.minecraft.net", "evil.example"))

    assert contacted == []


def test_redirecciones_ciclicas_tienen_tope_y_cierran_respuestas(monkeypatch):
    responses = []

    def _get(*a, **k):
        response = _Response(302, URL)
        responses.append(response)
        return response

    monkeypatch.setattr(bu.requests, "get", _get)
    with pytest.raises(ValueError):
        bu._open_bds_download(URL)

    assert len(responses) == 6
    assert all(r.closed for r in responses)


def test_descarga_invalida_cierra_stream_y_limpia_temporales(tmp_path, monkeypatch):
    import zipfile

    response = _Response()
    monkeypatch.setattr(bu.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(bu, "_fetch_latest_bedrock_download", lambda: (URL, "1.2.3.4"))
    monkeypatch.setattr(bu.requests, "get", lambda *a, **k: response)

    with pytest.raises(zipfile.BadZipFile):
        bu._download_and_install_bds(log_fn=lambda *a: None)

    assert response.closed
    assert not (tmp_path / "bds_update.zip").exists()
    assert not (tmp_path / "bds_update_staging").exists()


@pytest.mark.parametrize("name", ["../fuera", r"..\fuera", r"C:\fuera", "..", ".", "NUL", "Mundo.", "db:stream"])
def test_gui_y_cli_rechazan_level_name_inseguro(tmp_path, name):
    (tmp_path / "server.properties").write_text(f"level-name={name}\n", encoding="utf-8")
    for resolver in (auto_backup.get_world_dir, restore_backup.get_world_dir):
        with pytest.raises(ValueError):
            resolver(str(tmp_path))


def test_resolver_admite_nombre_con_espacios_y_unicode(tmp_path):
    (tmp_path / "server.properties").write_text("level-name=Mi mundo ñ\n", encoding="utf-8")
    assert server_properties.resolve_world_dir(str(tmp_path)) == str(tmp_path / "worlds" / "Mi mundo ñ")


@pytest.mark.parametrize("redirigir_raiz", [False, True])
def test_resolver_rechaza_junction_del_mundo_o_de_worlds(tmp_path, monkeypatch, redirigir_raiz):
    (tmp_path / "server.properties").write_text("level-name=Mundo\n", encoding="utf-8")
    redirected = tmp_path / "worlds" if redirigir_raiz else tmp_path / "worlds" / "Mundo"
    realpath = server_properties.os.path.realpath

    def _junction(path):
        if os.fspath(path) == str(redirected):
            return str(tmp_path / "fuera")
        return realpath(path)

    monkeypatch.setattr(server_properties.os.path, "realpath", _junction)
    with pytest.raises(ValueError):
        server_properties.resolve_world_dir(str(tmp_path))


def test_core_rechaza_destino_externo_antes_de_abrir_zip(tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "level.dat").write_bytes(b"intacto")

    with pytest.raises(ValueError):
        restore_core.restore_from_zip(str(tmp_path / "no-existe.zip"), str(tmp_path), str(fuera))

    assert (fuera / "level.dat").read_bytes() == b"intacto"
    assert list(tmp_path.iterdir()) == [fuera]


def test_fallback_con_archivos_sobrantes_conserva_resguardo(tmp_path, monkeypatch):
    active = tmp_path / "pack"
    bak = tmp_path / "pack.bak_abcdef12"
    active.mkdir()
    bak.mkdir()
    (active / "sobrante.json").write_bytes(b"intento fallido")
    (active / "manifest.json").write_bytes(b"nuevo")
    (bak / "manifest.json").write_bytes(b"original")

    def _bloquear(*a):
        raise PermissionError("bloqueado")

    monkeypatch.setattr(zip_safety.os, "rename", _bloquear)
    zip_safety._quarantine_and_restore(str(active), str(bak))

    assert (active / "manifest.json").read_bytes() == b"original"
    assert (active / "sobrante.json").exists()
    assert (bak / "manifest.json").read_bytes() == b"original"
    assert not (bak / "sobrante.json").exists()


def _setup_request(monkeypatch):
    monkeypatch.setattr(setup.manager, "is_running", False)
    monkeypatch.setattr(setup.manager, "op_lock", threading.Lock())
    monkeypatch.setattr(setup, "_check_origin", lambda request: None)
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def test_setup_rechaza_instancia_externa_y_libera_lock(monkeypatch):
    request = _setup_request(monkeypatch)
    monkeypatch.setattr(setup.external_probe, "detect_external_bds", lambda: (True, "wrapper_mutex"))
    dispatched = []
    monkeypatch.setattr(setup.threading, "Thread", lambda **k: dispatched.append(k))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(setup.setup_install_bds(request))

    assert exc.value.status_code == 409
    assert dispatched == []
    assert not setup.manager.op_lock.locked()


def test_setup_rechequea_estado_despues_de_adquirir_lock(monkeypatch):
    request = _setup_request(monkeypatch)

    class _LockConStart:
        released = False

        def acquire(self, blocking=False):
            setup.manager.is_running = True
            return True

        def release(self):
            self.released = True

    lock = _LockConStart()
    monkeypatch.setattr(setup.manager, "op_lock", lock)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(setup.setup_install_bds(request))
    assert exc.value.status_code == 409
    assert lock.released


def test_setup_error_de_despacho_libera_lock(monkeypatch):
    request = _setup_request(monkeypatch)
    monkeypatch.setattr(setup.external_probe, "detect_external_bds", lambda: (False, None))

    class _ThreadRoto:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("sin recursos")

    monkeypatch.setattr(setup.threading, "Thread", _ThreadRoto)
    with pytest.raises(RuntimeError, match="sin recursos"):
        asyncio.run(setup.setup_install_bds(request))
    assert not setup.manager.op_lock.locked()
