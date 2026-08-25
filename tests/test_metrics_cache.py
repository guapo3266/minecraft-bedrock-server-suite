# -*- coding: utf-8 -*-
"""Caché TTL de las métricas de disco (gui_backend/metrics.py).

get_hardware_metrics se llama en cada poll de status (~2 s) y pagaba una
syscall psutil.disk_usage cada vez por un valor que cambia despacio. Aquí se
verifica: 1 syscall por ventana TTL, re-muestreo al expirar, redondeo idéntico
al anterior y último-valor-conocido si el muestreo falla con caché previa.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui_backend.metrics as metrics


class _FakeUsage:
    def __init__(self, total, free, percent):
        self.total = total
        self.free = free
        self.percent = percent


GB = 1024 ** 3


@pytest.fixture(autouse=True)
def _cache_limpio():
    metrics._reset_disk_cache_for_tests()
    yield
    metrics._reset_disk_cache_for_tests()


def _parchea_disco(monkeypatch, usages, errores_en=()):
    """Sustituye psutil.disk_usage visto desde metrics; devuelve el registro
    de llamadas (path) para contar syscalls."""
    llamadas = []
    idx = {"n": 0}

    def fake_disk_usage(path):
        n = idx["n"]
        idx["n"] += 1
        llamadas.append(path)
        if n in errores_en:
            raise OSError("volumen no disponible")
        u = usages[min(n, len(usages) - 1)]
        return u

    monkeypatch.setattr(metrics.psutil, "disk_usage", fake_disk_usage)
    return llamadas


def _campos_disco(h):
    """Solo los 3 campos de disco: RAM/CPU varian entre llamadas reales."""
    return (h["disk_total_gb"], h["disk_free_gb"], h["disk_used_pct"])


def test_disco_una_syscall_por_ventana_ttl(monkeypatch):
    llamadas = _parchea_disco(monkeypatch, [_FakeUsage(100 * GB, 25 * GB, 75.0)])
    h1 = metrics.get_hardware_metrics()
    h2 = metrics.get_hardware_metrics()
    assert len(llamadas) == 1  # segunda lectura servida desde caché
    # Redondeo identico al comportamiento anterior (valores crudos -> GB/pct)
    assert _campos_disco(h1) == (100.0, 25.0, 75.0)
    assert _campos_disco(h2) == _campos_disco(h1)


def test_disco_cache_expira_y_remuestrea(monkeypatch):
    llamadas = _parchea_disco(
        monkeypatch,
        [_FakeUsage(100 * GB, 25 * GB, 75.0), _FakeUsage(100 * GB, 10 * GB, 90.0)],
    )
    h1 = metrics.get_hardware_metrics()
    assert h1["disk_free_gb"] == 25.0
    # Forzar expiracion de la ventana TTL sin parchear el reloj global.
    metrics._disk_cache["at"] = 0.0
    h2 = metrics.get_hardware_metrics()
    assert len(llamadas) == 2
    assert h2["disk_free_gb"] == 10.0
    assert h2["disk_used_pct"] == 90.0


def test_disco_fallo_sirve_ultimo_valor_conocido(monkeypatch):
    llamadas = _parchea_disco(
        monkeypatch,
        [_FakeUsage(100 * GB, 25 * GB, 75.0)],
        errores_en=(1,),
    )
    h1 = metrics.get_hardware_metrics()
    metrics._disk_cache["at"] = 0.0  # expirar: el siguiente muestreo fallara
    h2 = metrics.get_hardware_metrics()
    assert len(llamadas) == 2       # se intento remuestrear...
    assert _campos_disco(h2) == _campos_disco(h1)  # ...pero se sirvio el stale, sin lanzar


def test_disco_fallo_sin_cache_previa_propaga(monkeypatch):
    _parchea_disco(monkeypatch, [], errores_en=(0,))
    # Comportamiento previo preservado: sin valor conocido no hay nada que inventar.
    with pytest.raises(OSError):
        metrics.get_hardware_metrics()
