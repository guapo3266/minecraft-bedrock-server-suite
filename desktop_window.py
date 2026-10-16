"""Ventana portable con Chromium incluido y cierre de servidor supervisado."""

import os
from pathlib import Path
import socket
import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QStackedWidget, QVBoxLayout, QHBoxLayout, QWidget,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

import runtime_paths
from console_lang import L


class CloseSignals(QObject):
    progress = Signal(str)
    result = Signal(object)


class LocalPage(QWebEnginePage):
    """El panel solo navega dentro de su backend; los enlaces externos son explicitos."""
    def __init__(self, profile, parent, origin):
        super().__init__(profile, parent)
        self.origin = origin

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if not is_main_frame or url.toString() == "about:blank":
            return True
        if (url.scheme(), url.host(), url.port()) == self.origin:
            return True
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ("https", "http"):
            QDesktopServices.openUrl(url)
        return False


class SuiteWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Import tardio: stdout/stderr ya apuntan al registro del portable.
        import uvicorn
        import server_gui_server
        from gui_backend.state import manager
        from gui_backend.services.desktop_lifecycle import DesktopCloseCoordinator

        self.manager = manager
        manager.log_sinks.append(lambda entry: print(f"[{entry['time']}] {entry['text']}", flush=True))
        self.coordinator = DesktopCloseCoordinator()
        self.allowed_to_close = False
        self.closing = False
        self.stopping_backend = False
        self.backup_error = False
        self.setWindowTitle("SuiteMinecraft")
        self.resize(1360, 900)
        self.setMinimumSize(760, 620)
        self.setWindowIcon(QIcon(runtime_paths.resource_path("gui_frontend", "public", "favicon.svg")))

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.view = QWebEngineView()
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.setAcceptDrops(False)
        self.stack.addWidget(self.view)
        self.status_panel = QWidget()
        self.status_panel.setObjectName("close-panel")
        layout = QVBoxLayout(self.status_panel)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.addStretch()
        self.heading = QLabel(L("Preparando el panel", "Preparing the dashboard"))
        self.heading.setObjectName("close-heading")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.detail = QLabel(L("Iniciando SuiteMinecraft. El servidor arrancará solo cuando lo elijas.", "Starting SuiteMinecraft. The server will start only when you choose."))
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)
        layout.addSpacing(18)
        buttons = QHBoxLayout()
        self.retry_button = QPushButton(L("Reintentar backup", "Retry backup"))
        self.retry_button.setObjectName("retry-backup")
        self.retry_button.clicked.connect(lambda: self.start_close(retry=True))
        self.exit_button = QPushButton(L("Salir sin este backup", "Exit without this backup"))
        self.exit_button.setObjectName("exit-without-backup")
        self.exit_button.clicked.connect(self.finish_exit)
        self.back_button = QPushButton(L("Volver al panel", "Back to dashboard"))
        self.back_button.clicked.connect(self.back_to_dashboard)
        for button in (self.retry_button, self.exit_button, self.back_button):
            buttons.addWidget(button)
            button.hide()
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        self.stack.addWidget(self.status_panel)
        self.stack.setCurrentWidget(self.status_panel)
        self.status_panel.setStyleSheet("""
            QWidget#close-panel { background: #0b1921; color: #e7f0f4; }
            QLabel { color: #c7d8e2; font-size: 16px; margin-bottom: 18px; }
            QLabel#close-heading { color: #f5fbff; font-size: 29px; font-weight: 600; }
            QPushButton { background: #163744; color: #eefaff; border: 1px solid #456573;
                border-radius: 8px; padding: 12px 18px; font-size: 14px; }
            QPushButton:focus { border: 2px solid #65dfcc; }
            QPushButton:hover { background: #225262; }
            QProgressBar { background: #1e3944; border: 0; }
            QProgressBar::chunk { background: #65dfcc; }
        """)

        menu = self.menuBar().addMenu(L("Aplicación", "Application"))
        menu.addAction(L("Abrir registros", "Open logs"), self.open_logs)
        menu.addAction(L("Abrir carpeta portable", "Open portable folder"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(runtime_paths.installation_dir())))
        menu.addSeparator()
        menu.addAction(L("Salir", "Exit"), self.close)

        self.signals = CloseSignals(self)
        self.signals.progress.connect(self.show_progress)
        self.signals.result.connect(self.on_close_result)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            initial = int(os.environ.get("GUI_PORT", "8000"))
        except ValueError:
            initial = 8000
        initial = initial if 1 <= initial <= 65535 else 8000
        for port in range(initial, 65536):
            try:
                self.socket.bind(("127.0.0.1", port))
                break
            except OSError:
                if port == 65535:
                    raise
        self.url = f"http://127.0.0.1:{port}"
        print("[SuiteMinecraft] " + self.url, flush=True)
        self.profile = QWebEngineProfile("SuiteMinecraft", self.view)
        storage = Path(runtime_paths.installation_dir()) / "data" / "webview"
        self.profile.setPersistentStoragePath(str(storage))
        self.profile.setCachePath(str(storage / "cache"))
        page = LocalPage(self.profile, self.view, ("http", "127.0.0.1", port))
        self.view.setPage(page)
        self.profile.downloadRequested.connect(self.download)
        self.view.loadFinished.connect(self.loaded)
        config = uvicorn.Config(server_gui_server.app, host="127.0.0.1", port=port, log_level="info")
        self.server = uvicorn.Server(config)
        self.backend_error = None
        self.backend_thread = threading.Thread(target=self.serve, daemon=True, name="desktop-backend")
        self.backend_thread.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.page_requested = False

    def serve(self):
        try:
            self.server.run(sockets=[self.socket])
        except BaseException as exc:
            self.backend_error = str(exc)
            print("[SuiteMinecraft] " + repr(exc), flush=True)
        finally:
            self.socket.close()

    def tick(self):
        if self.stopping_backend:
            if not self.backend_thread.is_alive():
                # Se mantiene op_lock hasta salir: ningun watchdog puede abrir
                # una sesion nueva entre el apagado y el fin de QApplication.
                self.allowed_to_close = True
                self.close()
            return
        if not self.backend_thread.is_alive():
            if self.closing:
                return
            self.show_progress("error")
            self.detail.setText(self.backend_error or L("El backend se cerró. Consulta los registros.", "The backend stopped. Check the logs."))
            self.exit_button.setText(L("Cerrar aplicación", "Close application"))
            self.exit_button.show()
            return
        if self.server.started and not self.page_requested:
            self.page_requested = True
            self.view.setUrl(QUrl(self.url))

    def loaded(self, ok):
        if self.closing:
            return
        if ok:
            self.stack.setCurrentWidget(self.view)
        else:
            self.heading.setText(L("No se pudo cargar el panel", "The dashboard could not be loaded"))
            self.detail.setText(L("Puedes consultar los registros desde el menú Aplicación.", "You can open the logs from the Application menu."))

    def closeEvent(self, event):
        if self.allowed_to_close:
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        with self.manager.lock:
            players = sorted(self.manager.players_online)
            running = self.manager.is_running
        if running and players:
            dialog = QMessageBox(self)
            dialog.setWindowTitle(L("Apagar el servidor", "Stop the server"))
            dialog.setText(L(f"Jugadores conectados: {len(players)}. ¿Apagar el servidor y crear el backup final?", f"Players online: {len(players)}. Stop the server and create the final backup?"))
            stop = dialog.addButton(L("Apagar y guardar", "Stop and back up"), QMessageBox.ButtonRole.AcceptRole)
            cancel = dialog.addButton(L("Cancelar", "Cancel"), QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(cancel)
            dialog.exec()
            if dialog.clickedButton() is not stop:
                return
        self.start_close()

    def start_close(self, retry=False):
        self.closing = True
        self.backup_error = False
        for button in (self.retry_button, self.exit_button, self.back_button):
            button.hide()
        self.show_progress("waiting")
        threading.Thread(target=lambda: self.signals.result.emit(self.coordinator.close(self.signals.progress.emit, retry=retry)), daemon=True, name="desktop-close").start()

    def show_progress(self, stage):
        self.stack.setCurrentWidget(self.status_panel)
        self.progress.setVisible(stage != "error")
        messages = {
            "waiting": (L("Preparando el cierre", "Preparing to close"), L("Esperando a que termine cualquier operación en curso…", "Waiting for any running operation to finish…")),
            "stopping": (L("Deteniendo el servidor", "Stopping the server"), L("Guardando el mundo y esperando el apagado de Minecraft…", "Saving the world and waiting for Minecraft to stop…")),
            "backup": (L("Creando el backup final", "Creating the final backup"), L("La ventana permanecerá abierta hasta que termine. En mundos grandes puede tardar varios minutos.", "The window will stay open until this finishes. Large worlds may take several minutes.")),
            "exit": (L("Cerrando SuiteMinecraft", "Closing SuiteMinecraft"), L("Finalizando el panel y sus conexiones…", "Shutting down the dashboard and its connections…")),
            "error": (L("No se pudo completar el cierre", "Shutdown could not be completed"), ""),
        }
        title, text = messages.get(stage, messages["waiting"])
        self.heading.setText(title)
        self.detail.setText(text)

    def on_close_result(self, result):
        if result["state"] == "ready":
            self.finish_exit()
            return
        self.show_progress("error")
        self.detail.setText(str(result.get("message", "")))
        if result["state"] == "backup_error":
            self.backup_error = True
            self.heading.setText(L("El servidor está apagado, pero falló el backup", "The server is off, but the backup failed"))
            self.retry_button.show()
            self.exit_button.show()
            self.retry_button.setFocus()
        else:
            self.back_button.show()
            self.back_button.setFocus()

    def back_to_dashboard(self):
        self.closing = False
        self.stack.setCurrentWidget(self.view)

    def finish_exit(self):
        # Si el backend fallo mientras BDS estaba activo, el boton de cerrar
        # debe pasar igualmente por el apagado; no abandona el wrapper vivo.
        if not self.closing:
            self.start_close()
            return
        self.closing = True
        self.stopping_backend = True
        self.show_progress("exit")
        self.server.should_exit = True
        for button in (self.retry_button, self.exit_button, self.back_button):
            button.hide()

    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(runtime_paths.installation_dir(), "logs")))

    def download(self, request):
        export = Path(runtime_paths.installation_dir()) / "exports"
        export.mkdir(exist_ok=True)
        filename, _ = QFileDialog.getSaveFileName(self, L("Guardar archivo", "Save file"), str(export / Path(request.suggestedFileName()).name))
        if filename:
            request.setDownloadDirectory(str(Path(filename).parent))
            request.setDownloadFileName(Path(filename).name)
            request.accept()
        else:
            request.cancel()


def main():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("SuiteMinecraft")
    app.setOrganizationName("SuiteMinecraft")
    window = SuiteWindow()
    window.show()
    return app.exec()
