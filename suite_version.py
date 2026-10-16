"""Versión del producto compartida por backend y frontend, independiente de BDS."""

import json
from pathlib import Path


VERSION = json.loads(Path(__file__).with_name("version.json").read_text(encoding="utf-8"))["version"]
