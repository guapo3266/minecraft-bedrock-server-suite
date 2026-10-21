"""Extrae la entrada vigente del changelog para preparar una Release."""

import argparse
import json
from pathlib import Path
import posixpath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suite_release import REPOSITORY  # noqa: E402

# Destino relativo de un enlace Markdown ("](docs/x.md)"). La Release de GitHub
# no resuelve rutas del repositorio: copiadas tal cual daban 404 (2026-10-20).
_RELATIVE_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")
# Rama y no etiqueta: el hash, la procedencia y la evidencia de cada entrega se
# registran en docs/ DESPUES de etiquetarla y solo existen en main.
_DOCS_REF = "main"


def absolute_links(text):
    """Reescribe los enlaces relativos (a la raiz del repo) como enlaces a GitHub."""
    base = f"https://github.com/{REPOSITORY}/blob/{_DOCS_REF}/"

    def absolute(match):
        target = posixpath.normpath(match.group(1))
        if target.startswith(".."):
            return match.group(0)
        return f"]({base}{target})"

    return _RELATIVE_LINK.sub(absolute, text)


def release_notes():
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## [{version}] - "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
    body = absolute_links("\n".join(lines[start + 1:end]).strip())
    return f"# Bedrock Suite {version}\n\nExtrae **BedrockSuite-Windows-x64.zip** y abre **iniciar_gui.bat**.\n" \
           "Incluye Python y la interfaz compilada. BDS se descarga desde Mojang durante el primer inicio.\n\n" + body + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(release_notes(), encoding="utf-8")
