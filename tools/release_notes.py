"""Extrae la entrada vigente del changelog para preparar una Release."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_notes():
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## [{version}] - "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
    body = "\n".join(lines[start + 1:end]).strip()
    return f"# Bedrock Suite {version}\n\nExtrae **BedrockSuite-Windows-x64.zip** y abre **iniciar_gui.bat**.\n" \
           "Incluye Python y la interfaz compilada. BDS se descarga desde Mojang durante el primer inicio.\n\n" + body + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(release_notes(), encoding="utf-8")
