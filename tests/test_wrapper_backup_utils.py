# -*- coding: utf-8 -*-
"""mark_corrupt_zip: renombre idempotente y tolerante a bloqueos."""

import wrapper_backup as wb


def test_mark_corrupt_zip_renombra_e_es_idempotente(tmp_path):
    original = tmp_path / "auto_backup_x.zip"
    original.write_bytes(b"x")

    wb.mark_corrupt_zip(str(original), "CORRUPTO")

    marcado = tmp_path / "auto_backup_x_CORRUPTO.zip"
    assert marcado.exists()
    assert not original.exists()

    wb.mark_corrupt_zip(str(marcado), "CORRUPTO")  # mismo motivo: no-op
    assert marcado.exists()


def test_mark_corrupt_zip_tolera_error_de_rename(tmp_path, monkeypatch):
    original = tmp_path / "auto_backup_y.zip"
    original.write_bytes(b"x")

    def _rename_falla(*_a, **_k):
        raise OSError("bloqueado por antivirus")

    monkeypatch.setattr(wb.os, "rename", _rename_falla)

    wb.mark_corrupt_zip(str(original), "CORRUPTO")  # no debe lanzar

    assert original.exists(), "el archivo no debe perderse si el rename falla"


def test_mark_corrupt_zip_ignora_entradas_invalidas(tmp_path):
    wb.mark_corrupt_zip(None)
    wb.mark_corrupt_zip("")
    wb.mark_corrupt_zip(str(tmp_path / "no_existe.zip"))


def test_send_command_fallback_usa_server_wrapper(monkeypatch):
    """Sin emisor inyectado (worker standalone), _send_command cae a
    server_wrapper.send_command."""
    import server_wrapper

    previo = wb._command_sender
    wb._command_sender = None
    try:
        llamadas = []
        monkeypatch.setattr(server_wrapper, "send_command", llamadas.append)
        wb._send_command("save resume")
        assert llamadas == ["save resume"]
    finally:
        wb._command_sender = previo


def test_send_command_usa_el_emisor_inyectado():
    previo = wb._command_sender
    llamadas = []
    try:
        wb.set_command_sender(llamadas.append)
        wb._send_command("list")
        assert llamadas == ["list"]
    finally:
        wb._command_sender = previo


def test_snapshot_retry_delay_crece_y_capea():
    import wrapper_state as wstate

    assert wb._snapshot_retry_delay(1) == wstate.RETRY_BACKOFF_BASE_SEC
    assert wb._snapshot_retry_delay(2) == wstate.RETRY_BACKOFF_BASE_SEC * 2
    assert wb._snapshot_retry_delay(99) == wstate.RETRY_BACKOFF_MAX_SEC
