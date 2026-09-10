# -*- coding: utf-8 -*-
"""Ramas de metrics._measure_process_tree sin procesos reales."""

import os
import types

import gui_backend.metrics as m


class _ProcBase:
    def __init__(self, pid):
        self.pid = pid

    def children(self, recursive=True):
        return []

    def cpu_percent(self, interval=None):
        return 0.0

    def memory_info(self):
        return types.SimpleNamespace(rss=0)


class _GuiConHijoDesaparecido(_ProcBase):
    def children(self, recursive=True):
        return [_Desaparecido()]

    def cpu_percent(self, interval=None):
        return 1.0

    def memory_info(self):
        return types.SimpleNamespace(rss=1024 * 1024)


class _Desaparecido:
    pid = 424242

    def cpu_percent(self, interval=None):
        raise m.psutil.NoSuchProcess(424242)

    def memory_info(self):
        raise m.psutil.NoSuchProcess(424242)


def test_measure_tree_ignora_proceso_desaparecido(monkeypatch):
    m._process_cache.clear()
    monkeypatch.setattr(
        m.psutil, "Process",
        lambda pid: _Desaparecido() if pid == 424242 else _GuiConHijoDesaparecido(pid),
    )

    ram, cpu = m._measure_process_tree()

    assert ram == 1.0
    assert cpu == 1.0
    assert 424242 not in m._process_cache


def test_measure_tree_limpia_cache_de_pids_ausentes(monkeypatch):
    m._process_cache.clear()
    m._process_cache[999999] = object()
    monkeypatch.setattr(m.psutil, "Process", lambda pid: _ProcBase(pid))

    m._measure_process_tree()

    assert 999999 not in m._process_cache


def test_measure_tree_tolera_children_que_lanzan_nosuchprocess(monkeypatch):
    class _GuiSinHijos(_ProcBase):
        def children(self, recursive=True):
            raise m.psutil.NoSuchProcess(os.getpid())

        def memory_info(self):
            return types.SimpleNamespace(rss=1024 * 1024)

    m._process_cache.clear()
    monkeypatch.setattr(m.psutil, "Process", lambda pid: _GuiSinHijos(pid))

    ram, _cpu = m._measure_process_tree()

    assert ram == 1.0
