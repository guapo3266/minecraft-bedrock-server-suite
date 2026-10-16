"""Emite el router autónomo extraído del backend para entrenamiento en Colab."""
import ast
from pathlib import Path
import sys


def main():
    # Mantener acentos al canalizar stdout en Windows (cp1252 por defecto).
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(__file__).resolve().parents[1] / "gui_backend/services/ai_assistant.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            nodes[node.target.id] = node
    needed = {"_select_tools_impl"}
    while True:
        expanded = needed | {
            ref.id
            for name in needed
            for ref in ast.walk(nodes[name])
            if isinstance(ref, ast.Name) and isinstance(ref.ctx, ast.Load) and ref.id in nodes
        }
        if expanded == needed:
            break
        needed = expanded
    chosen = sorted({nodes[name] for name in needed}, key=lambda n: n.lineno)
    print('"""Router portátil v4. Extraído mecánicamente del backend; no depende de datasets."""')
    print("import random\nimport re\nimport unicodedata\nfrom typing import Any, Dict, List, Optional, Tuple\n")
    for node in chosen:
        print(ast.get_source_segment(source, node))
        print()
    print('''def select_tool_names(prompt: Optional[str], top_n: Optional[int] = 4) -> List[str]:
    return [tool["function"]["name"] for tool in _select_tools_impl(prompt, top_n=top_n)]


def select_tools(prompt: Optional[str], tools=None, top_n: Optional[int] = 4):
    if tools is None:
        return _select_tools_impl(prompt, top_n=top_n)
    by_name = {tool["function"]["name"]: tool for tool in tools}
    return [by_name[name] for name in select_tool_names(prompt, top_n=top_n)]
''')


if __name__ == "__main__":
    main()
