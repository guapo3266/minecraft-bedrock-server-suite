# -*- coding: utf-8 -*-
"""Lectura acotada de _write_file_chunked (2026-10-19).

En Windows, src.read(n) reserva un bufer de n bytes en cada llamada aunque el
archivo sea chico. Con un read(8 MiB) fijo, los ~12.000 archivos de packs de
una instalacion llevaban el backup a 74-185 s en lugar de ~10 s. Estos tests
fijan que cada lectura se acota al tamano del archivo (con piso y techo), que
el contenido del ZIP no cambia y que la cancelacion sigue siendo por chunk.

Tambien fijan las otras dos optimizaciones del empaquetado de packs: los
formatos ya comprimidos (.png/.ogg/.mp3) van con ZIP_STORED y los nombres de
entrada de _write_server_packs son identicos a los del relpath por archivo.
"""
import io
import os
import zipfile

import pytest

import auto_backup as ab


class _CancelTrasLecturas:
    """cancel_event que se activa despues de `n` lecturas de chunk."""

    def __init__(self, contador, n):
        self._contador = contador
        self._n = n

    def is_set(self):
        return self._contador["lecturas"] >= self._n


def _espiar_lecturas(monkeypatch, registro):
    """Envuelve open() de auto_backup para registrar cada src.read(n)."""
    real_open = open

    class _Envoltorio:
        def __init__(self, f):
            self._f = f

        def read(self, n=-1):
            registro.append(n)
            return self._f.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._f.close()

    def _open(path, mode="r", *a, **k):
        return _Envoltorio(real_open(path, mode, *a, **k))

    monkeypatch.setattr(ab, "open", _open, raising=False)


def _zip_de(tmp_path, nombre, contenido, cancel_event=None):
    origen = tmp_path / nombre
    origen.write_bytes(contenido)
    destino = io.BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        ab._write_file_chunked(zf, str(origen), nombre, cancel_event)
    with zipfile.ZipFile(destino) as zf:
        return zf.read(nombre)


def test_read_size_acotado_entre_piso_y_chunk():
    assert ab._read_size(0) == ab._MIN_READ
    assert ab._read_size(2048) == ab._MIN_READ
    assert ab._read_size(ab._MIN_READ) == ab._MIN_READ + 1
    assert ab._read_size(3 * 1024 * 1024) == 3 * 1024 * 1024 + 1
    assert ab._read_size(ab._CHUNK) == ab._CHUNK
    assert ab._read_size(10 * ab._CHUNK) == ab._CHUNK


@pytest.mark.parametrize("valor", [None, -1, "123", 1.5])
def test_read_size_tolera_tamanos_invalidos(valor):
    assert ab._read_size(valor) == ab._MIN_READ


@pytest.mark.parametrize("tamano", [0, 1, 2048, 64 * 1024, 64 * 1024 + 7, 300 * 1024])
def test_contenido_identico_en_el_zip(tmp_path, tamano):
    contenido = bytes(range(256)) * (tamano // 256) + b"x" * (tamano % 256)
    assert _zip_de(tmp_path, "pack.bin", contenido) == contenido


def test_archivo_chico_no_pide_el_chunk_maximo(tmp_path, monkeypatch):
    registro = []
    _espiar_lecturas(monkeypatch, registro)
    _zip_de(tmp_path, "manifest.json", b"{}" * 1000)
    assert registro, "debio leer el archivo"
    assert max(registro) == ab._MIN_READ < ab._CHUNK


def test_archivo_grande_lee_en_chunks_del_maximo(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "_CHUNK", 128 * 1024)
    registro = []
    _espiar_lecturas(monkeypatch, registro)
    contenido = b"z" * (300 * 1024)
    assert _zip_de(tmp_path, "db.ldb", contenido) == contenido
    assert set(registro) == {128 * 1024}
    assert len(registro) == 4  # 128 + 128 + 44 KiB + EOF


def test_cancelacion_sigue_siendo_por_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "_CHUNK", 128 * 1024)
    contador = {"lecturas": 0}

    class _Contar(list):
        def append(self, n):
            contador["lecturas"] += 1
            super().append(n)

    registro_contado = _Contar()
    _espiar_lecturas(monkeypatch, registro_contado)
    with pytest.raises(RuntimeError):
        _zip_de(tmp_path, "db.ldb", b"z" * (1024 * 1024), _CancelTrasLecturas(contador, 2))
    assert len(registro_contado) == 2, "debe abortar en el chunk siguiente, no al final"


# ── Formatos ya comprimidos: ZIP_STORED ─────────────────────────────

@pytest.mark.parametrize("nombre", ["a.png", "B.PNG", "musica.ogg", "efecto.Mp3"])
def test_formatos_ya_comprimidos_van_stored(tmp_path, nombre):
    contenido = os.urandom(70 * 1024)
    origen = tmp_path / nombre
    origen.write_bytes(contenido)
    destino = io.BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        ab._write_file_chunked(zf, str(origen), nombre, None)
    with zipfile.ZipFile(destino) as zf:
        assert zf.getinfo(nombre).compress_type == zipfile.ZIP_STORED
        assert zf.read(nombre) == contenido
        assert zf.testzip() is None


@pytest.mark.parametrize("nombre", ["manifest.json", "es_ES.lang", "sonido.wav", "level.dat", "sin_extension"])
def test_el_resto_sigue_deflated(tmp_path, nombre):
    contenido = b'{"clave": "valor"}\n' * 500
    assert _zip_de(tmp_path, nombre, contenido) == contenido
    origen = tmp_path / nombre
    destino = io.BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        ab._write_file_chunked(zf, str(origen), nombre, None)
    with zipfile.ZipFile(destino) as zf:
        assert zf.getinfo(nombre).compress_type == zipfile.ZIP_DEFLATED


# ── Nombres de entrada de _write_server_packs (sin relpath por archivo) ──

def test_arcnames_de_packs_identicos_al_relpath_por_archivo(tmp_path, monkeypatch):
    arbol = {
        "resource_packs/PackA/manifest.json": b"{}",
        "resource_packs/PackA/textures/blocks/piedra.png": os.urandom(256),
        "resource_packs/PackA/sub/muy/hondo/x.json": b"[1]",
        "resource_packs/suelto_en_raiz.txt": b"raiz",
        "behavior_packs/PackB/manifest.json": b"{}",
        "behavior_packs/PackB/scripts/main.js": b"//",
        "behavior_packs/PackB/sounds/a.ogg": os.urandom(128),
    }
    for rel, datos in arbol.items():
        destino = tmp_path / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    monkeypatch.setattr(ab, "BASE_DIR", str(tmp_path))

    esperados = set()
    for kind in ab.SERVER_PACK_DIRS:
        src_dir = os.path.join(str(tmp_path), kind)
        for root, _dirs, files in os.walk(src_dir):
            for f in files:
                full = os.path.join(root, f)
                esperados.add(ab._PACK_ZIP_PREFIX + kind + "/" + os.path.relpath(full, src_dir).replace(os.sep, "/"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        total = ab._write_server_packs(zf, 0, None)
    with zipfile.ZipFile(buf) as zf:
        assert set(zf.namelist()) == esperados
        assert total == sum(len(v) for v in arbol.values())
        for rel, datos in arbol.items():
            assert zf.read(ab._PACK_ZIP_PREFIX + rel) == datos
