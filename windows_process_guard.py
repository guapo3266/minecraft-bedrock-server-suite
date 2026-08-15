# -*- coding: utf-8 -*-
"""windows_process_guard.py — Coordinación de procesos y Job Objects en Windows.

Proporciona utilidades ligeras con ctypes estándar (sin dependencias externas):
1. NamedMutex: Mutex nombrado de Windows para evitar múltiples instancias del
   wrapper o coordinar backups entre procesos independientes.
2. Job Objects: Job Object con JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE para asegurar
   que bedrock_server.exe muera si el wrapper o la GUI son terminados de forma abrupta.
"""
import os
import sys
import hashlib
import ctypes
from ctypes import wintypes

if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    kernel32 = None

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x00000102
WAIT_ABANDONED = 0x00000080
INFINITE = 0xFFFFFFFF

# Constantes de Job Object
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


def get_installation_hash(base_dir: str) -> str:
    """Hash SHA256 corto y determinista de la ruta base de la instalación."""
    norm = os.path.abspath(base_dir).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


class NamedMutex:
    """Mutex nombrado de Windows para exclusión mutua inter-proceso."""

    def __init__(self, name: str):
        self.name = f"Local\\{name}"
        self.handle = None
        self.already_exists = False
        self._owned = False
        if kernel32:
            self.handle = kernel32.CreateMutexW(None, False, self.name)
            if self.handle:
                err = ctypes.get_last_error()
                self.already_exists = (err == ERROR_ALREADY_EXISTS)

    def acquire(self, timeout_ms: int = 0) -> bool:
        """Intenta adquirir el mutex. timeout_ms < 0 espera indefinidamente."""
        if not self.handle or not kernel32:
            self._owned = True
            return True
        timeout = INFINITE if timeout_ms < 0 else int(timeout_ms)
        res = kernel32.WaitForSingleObject(self.handle, wintypes.DWORD(timeout))
        if res in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self._owned = True
            return True
        return False

    def release(self):
        """Libera el mutex si fue adquirido."""
        if self.handle and kernel32 and self._owned:
            try:
                kernel32.ReleaseMutex(self.handle)
            except Exception:
                pass
            finally:
                self._owned = False

    def close(self):
        """Cierra el handle del mutex."""
        self.release()
        if self.handle and kernel32:
            try:
                kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None

    def __enter__(self):
        self.acquire(timeout_ms=-1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def create_job_object_for_process(process_handle_or_pid) -> wintypes.HANDLE:
    """Crea un Job Object con KILL_ON_JOB_CLOSE y le asigna el proceso dado."""
    if not kernel32:
        return None
    h_job = kernel32.CreateJobObjectW(None, None)
    if not h_job:
        return None

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    size = ctypes.sizeof(info)

    ok = kernel32.SetInformationJobObject(
        h_job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        size,
    )
    if not ok:
        kernel32.CloseHandle(h_job)
        return None

    h_proc = None
    close_proc = False
    if isinstance(process_handle_or_pid, int):
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        h_proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, process_handle_or_pid)
        close_proc = True
    else:
        h_proc = getattr(process_handle_or_pid, "_handle", None) or process_handle_or_pid

    if not h_proc:
        kernel32.CloseHandle(h_job)
        return None

    try:
        ok_assign = kernel32.AssignProcessToJobObject(h_job, h_proc)
    finally:
        if close_proc and h_proc:
            kernel32.CloseHandle(h_proc)

    if not ok_assign:
        kernel32.CloseHandle(h_job)
        return None

    return h_job


def close_job_object(h_job):
    """Cierra el handle del Job Object de Windows."""
    if h_job and kernel32:
        try:
            kernel32.CloseHandle(h_job)
        except Exception:
            pass
