"""Backend de la GUI Bedrock Wrapper.

Paquete modular extraído de server_gui_server.py durante el refactor.
Jerarquía de dependencias (sin ciclos):

    config ← security ← metrics ← state ← supervisor ← services ← routers ← app
"""

from suite_version import VERSION as __version__  # noqa: F401 (compatibilidad pública)
