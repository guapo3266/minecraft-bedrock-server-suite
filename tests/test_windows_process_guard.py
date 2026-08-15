# -*- coding: utf-8 -*-
"""Pruebas unitarias de windows_process_guard.py."""
import os
import sys
import subprocess
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import windows_process_guard as wpg


def test_installation_hash_determinista():
    h1 = wpg.get_installation_hash("C:\\MyServer")
    h2 = wpg.get_installation_hash("c:\\myserver")
    assert h1 == h2
    assert len(h1) == 16


import threading
import queue

def test_named_mutex_single_instance():
    name = "Test_Mutex_Suite_1"
    m1 = wpg.NamedMutex(name)
    try:
        assert m1.acquire(timeout_ms=100) is True
        
        # En otro hilo, m2 no debe poder adquirirlo mientras m1 lo mantenga
        q = queue.Queue()
        def thread_worker():
            m2 = wpg.NamedMutex(name)
            try:
                q.put(("already_exists", m2.already_exists))
                res = m2.acquire(timeout_ms=50)
                q.put(("acquire", res))
            finally:
                m2.close()

        t = threading.Thread(target=thread_worker)
        t.start()
        t.join(timeout=2)

        results = dict(q.get_nowait() for _ in range(q.qsize()))
        assert results["already_exists"] is True
        assert results["acquire"] is False
    finally:
        m1.close()


def test_named_mutex_context_manager():
    name = "Test_Mutex_Suite_Ctx"
    with wpg.NamedMutex(name) as m1:
        assert m1.already_exists is False
        q = queue.Queue()
        def thread_worker():
            m2 = wpg.NamedMutex(name)
            try:
                res = m2.acquire(timeout_ms=10)
                q.put(res)
            finally:
                m2.close()
        t = threading.Thread(target=thread_worker)
        t.start()
        t.join(timeout=2)
        assert q.get_nowait() is False

    # Tras salir del contexto, otro hilo sí puede adquirirlo
    q2 = queue.Queue()
    def thread_worker_2():
        m3 = wpg.NamedMutex(name)
        try:
            res = m3.acquire(timeout_ms=100)
            q2.put(res)
        finally:
            m3.close()
    t2 = threading.Thread(target=thread_worker_2)
    t2.start()
    t2.join(timeout=2)
    assert q2.get_nowait() is True


def test_job_object_assigns_to_process():
    if sys.platform != "win32":
        pytest.skip("Solo Windows soporta Job Objects")

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        h_job = wpg.create_job_object_for_process(proc.pid)
        assert h_job is not None
        wpg.close_job_object(h_job)
    finally:
        proc.terminate()
        proc.wait()


def test_job_object_kills_child_process_on_close():
    if sys.platform != "win32":
        pytest.skip("Solo Windows soporta Job Objects")

    import time
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        h_job = wpg.create_job_object_for_process(proc.pid)
        assert h_job is not None
        assert proc.poll() is None, "El proceso debe seguir vivo tras asignarlo"

        # Cerrar el Job Object debe forzar la terminación por JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        wpg.close_job_object(h_job)

        dead = False
        t_end = time.time() + 3.0
        while time.time() < t_end:
            if proc.poll() is not None:
                dead = True
                break
            time.sleep(0.05)

        assert dead is True, "El subproceso debió morir al cerrarse el Job Object"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
