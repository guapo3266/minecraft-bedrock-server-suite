# -*- coding: utf-8 -*-
"""Tests para el autodiagnóstico del backup inicial, exclusiones de Defender y backup-inicio."""
import io
import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server_wrapper as sw
import wrapper_state as wstate
import gui_backend.supervisor as supervisor
import console_lang as cl


def test_should_run_initial_backup_default_true(monkeypatch, tmp_path):
    """Por defecto (sin server.properties o sin clave), el backup inicial se ejecuta."""
    monkeypatch.setattr(wstate, "BASE_DIR", str(tmp_path))
    assert sw.should_run_initial_backup() is True

    # Con server.properties sin backup-inicio
    props = tmp_path / "server.properties"
    props.write_text("server-name=TestServer\ngamemode=survival\n", encoding="utf-8")
    assert sw.should_run_initial_backup() is True


def test_should_run_initial_backup_configuraciones(monkeypatch, tmp_path):
    """backup-inicio=false/0/no/off lo desactiva; true/1/yes/on lo mantiene activo."""
    monkeypatch.setattr(wstate, "BASE_DIR", str(tmp_path))
    props = tmp_path / "server.properties"

    for val in ("false", "0", "no", "off", "FALSE", "False"):
        props.write_text(f"server-name=TestServer\nbackup-inicio={val}\n", encoding="utf-8")
        assert sw.should_run_initial_backup() is False

    for val in ("true", "1", "yes", "on", "TRUE", "True"):
        props.write_text(f"server-name=TestServer\nbackup-inicio={val}\n", encoding="utf-8")
        assert sw.should_run_initial_backup() is True


def test_aviso_no_clasifica_como_error_en_gui():
    """El mensaje de aviso no debe clasificarse como 'error' por el supervisor de la GUI."""
    for lang in ("es", "en"):
        cl.set_lang(lang)
        dur = 35.5
        msg = cl.L(
            f"[Wrapper] [AVISO] El backup inicial tardó {dur:.1f} s (lo normal son ~6 s).\n"
            "          Posible firma de antivirus (Defender MAPS) en el primer acceso tras descargar o sincronizar archivos.\n"
            "          Para optimizarlo, ejecuta como Administrador:\n"
            "          powershell -ExecutionPolicy Bypass -File tools\\setup_defender_exclusions.ps1\n"
            "          (o ejecuta configurar_antivirus.bat / configura backup-inicio=false en server.properties)",
            f"[Wrapper] [ADVISORY] Initial backup took {dur:.1f} s (~6 s is normal).\n"
            "          Possible antivirus real-time scan overhead (Defender MAPS) on first access after sync/download.\n"
            "          To optimize, run as Administrator:\n"
            "          powershell -ExecutionPolicy Bypass -File tools\\setup_defender_exclusions.ps1\n"
            "          (or run configurar_antivirus.bat / set backup-inicio=false in server.properties)",
        )
        lines = msg.splitlines()
        for line in lines:
            line_str = line.strip()
            # Invocar la función real de clasificación del supervisor
            classified_type = supervisor.classify_log_line(line_str)
            assert classified_type != "error", f"La línea genera falso error en la GUI ({lang}): {line_str}"
        # La primera línea menciona el backup: debe colorearse como "backup"
        assert supervisor.classify_log_line(lines[0].strip()) == "backup"


def test_setup_defender_exclusions_script_existe_y_es_valido():
    """El script tools/setup_defender_exclusions.ps1 y el lanzador existen y contienen las rutas esperadas."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ps1_path = os.path.join(base_dir, "tools", "setup_defender_exclusions.ps1")
    bat_path = os.path.join(base_dir, "configurar_antivirus.bat")

    assert os.path.isfile(ps1_path), "Falta tools/setup_defender_exclusions.ps1"
    assert os.path.isfile(bat_path), "Falta configurar_antivirus.bat"

    ps1_content = open(ps1_path, encoding="utf-8").read()
    bat_content = open(bat_path, encoding="utf-8").read()

    # Verificar componentes críticos en ps1
    assert "Add-MpPreference" in ps1_content
    assert "Get-MpPreference" in ps1_content
    assert "Get-MpComputerStatus" in ps1_content
    assert "worlds" in ps1_content
    assert "resource_packs" in ps1_content
    assert "behavior_packs" in ps1_content
    assert "Backups_Minecraft" in ps1_content

    # Verificar que el bat usa %~dp0 y ejecuta con Bypass
    assert "%~dp0tools\\setup_defender_exclusions.ps1" in bat_content
    assert "ExecutionPolicy Bypass" in bat_content
