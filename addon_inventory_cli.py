# -*- coding: utf-8 -*-
"""addon_inventory_cli.py — CLI de inventario y diagnostico de addons.

CLI de SOLO LECTURA sobre el mismo analizador que la GUI
(``addon_inventory.analyze_addons``): no instala, no activa, no modifica nada.

Salidas:
  * legible (por defecto), agrupada por ambito, mundos y diagnosticos;
  * JSON (``--json``), byte a byte equivalente al payload de ``GET /api/addons``
    de la GUI para la misma instalacion (mismos campos y mismo filtro).

Codigos de salida (documentados tambien en docs/INFORME_ADDONS.md):
  0  analisis completado, inventario COMPLETO y sin diagnosticos de gravedad error
  1  analisis completado con al menos un diagnostico de gravedad error
  2  inventario PARCIAL: algo que deberia poder analizarse no se pudo analizar
  3  error de uso (raiz inexistente, argumentos invalidos)
  4  fallo interno inesperado del analizador
Si coinciden varios, gana el codigo mas alto. El codigo se calcula SIEMPRE
sobre la instalacion completa, aunque se filtren la vista o los diagnosticos.
"""

import argparse
import json
import os
import sys

import addon_inventory
from console_lang import L

EXIT_OK = 0
EXIT_HALLAZGOS = 1
EXIT_PARCIAL = 2
EXIT_USO = 3
EXIT_INTERNO = 4

_COLORES = {
    "error": "\x1b[31m",   # rojo
    "aviso": "\x1b[33m",   # amarillo
    "info": "\x1b[36m",    # cian
    "titulo": "\x1b[1m",   # negrita
    "ok": "\x1b[32m",      # verde
    "reset": "\x1b[0m",
}


class _Parser(argparse.ArgumentParser):
    """argparse sale con 2 en errores de uso; esta CLI documenta 3."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(L(f"[ERROR] Argumentos invalidos: {message}",
                f"[ERROR] Invalid arguments: {message}"), file=sys.stderr)
        raise SystemExit(EXIT_USO)


def idioma_activo():
    """Idioma efectivo de la consola (misma regla que console_lang.L)."""
    return "es" if os.environ.get("WRAPPER_LANG") == "es" else "en"


def _configurar_salida():
    """Salida UTF-8 cuando stdout NO es una consola (redireccion o pipe).

    En una consola real de Windows, `print` usa WriteConsoleW y la codificacion
    no importa; al redirigir, la codificacion local (cp1252) hacia fallar el
    proceso con un nombre de pack acentuado. UTF-8 + errors="replace" nunca
    lanza y deja el JSON parseable por un consumidor.
    """
    try:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass  # stdout sin reconfigure (redirigido a un objeto raro): se sigue


def _habilitar_ansi_windows():
    """Activa el procesado de secuencias ANSI en la consola de Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for handle in (-11, -12):  # STDOUT, STDERR
            modo = ctypes.c_uint32()
            if kernel32.GetConsoleMode(kernel32.GetStdHandle(handle), ctypes.byref(modo)):
                kernel32.SetConsoleMode(kernel32.GetStdHandle(handle), modo.value | 0x0004)
    except Exception:
        pass  # sin consola real (redireccion, servicio): se imprime sin color


def _color(texto, clave, activo):
    if not activo:
        return texto
    return "%s%s%s" % (_COLORES.get(clave, ""), texto, _COLORES["reset"])


def _mensaje(diagnostico, idioma):
    return diagnostico["message_es"] if idioma == "es" else diagnostico["message_en"]


def _plural(cantidad, singular, plural_es, plural_en, idioma):
    """Concordancia minima para las etiquetas del resumen."""
    if idioma == "es":
        return singular if cantidad == 1 else plural_es
    return singular if cantidad == 1 else plural_en


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def construir_parser():
    parser = _Parser(
        prog="addon_inventory_cli.py",
        description=L(
            "Inventario y diagnostico de behavior packs y resource packs (solo lectura): "
            "que packs existen, que mundos los referencian y que problemas demuestran sus metadatos.",
            "Inventory and diagnostics of behavior and resource packs (read-only): "
            "which packs exist, which worlds reference them and which problems their metadata proves.",
        ),
        epilog=L(
            "Codigos de salida: 0 = sin hallazgos; 1 = hay diagnosticos de error; "
            "2 = inventario parcial; 3 = error de uso; 4 = fallo interno.",
            "Exit codes: 0 = no findings; 1 = error diagnostics present; "
            "2 = partial inventory; 3 = usage error; 4 = internal failure.",
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", metavar="DIR",
                        help=L("Instalacion a analizar (por defecto: la carpeta de este script).",
                               "Installation to analyze (default: this script's folder)."))
    parser.add_argument("--json", action="store_true",
                        help=L("Salida JSON (equivalente al payload de GET /api/addons).",
                               "JSON output (equivalent to the GET /api/addons payload)."))
    parser.add_argument("--compact", action="store_true",
                        help=L("Con --json: una sola linea en vez de JSON indentado.",
                               "With --json: single line instead of indented JSON."))
    parser.add_argument("--world", metavar="NOMBRE",
                        help=L("Filtra la vista al ambito de ese mundo (propios + compartidos + sistema).",
                               "Narrow the view to that world's scope (own + shared + system packs)."))
    parser.add_argument("--kind", choices=("behavior", "resource"),
                        help=L("Filtra la vista a packs de comportamiento o de recursos.",
                               "Narrow the view to behavior or resource packs."))
    parser.add_argument("--severity", choices=("error", "aviso", "info", "todos"),
                        default="aviso",
                        help=L("Diagnosticos que muestra la salida legible (por defecto: error y aviso).",
                               "Diagnostics shown by the readable output (default: error and warning)."))
    parser.add_argument("--detalle", action="store_true",
                        help=L("Amplia modulos, dependencias y referencias de cada pack.",
                               "Expand modules, dependencies and references of each pack."))
    parser.add_argument("--lang", choices=("es", "en"),
                        help=L("Idioma de la salida (por defecto: WRAPPER_LANG, o ingles).",
                               "Output language (default: WRAPPER_LANG, otherwise English)."))
    parser.add_argument("--no-color", action="store_true",
                        help=L("Desactiva el color de la salida legible.",
                               "Disable color in the readable output."))
    parser.add_argument("--codes", action="store_true",
                        help=L("Muestra el catalogo de codigos de diagnostico y termina.",
                               "Show the diagnostic code catalog and exit."))
    return parser


# ---------------------------------------------------------------------------
# Salida legible
# ---------------------------------------------------------------------------

def _resumen_legible(payload, opciones):
    resumen = payload["summary"]
    print(_color(L("Resumen", "Summary"), "titulo", opciones["color"]))
    print("  %s: %d (%d %s, %d %s)" % (
        L("Packs", "Packs"), resumen["packs_total"],
        resumen["packs_behavior"], L("de comportamiento", "behavior"),
        resumen["packs_resource"], L("de recursos", "resource")))
    print("     %s: %d %s, %d %s, %d %s" % (
        L("por ambito", "by scope"),
        resumen["packs_compartidos"], L("compartidos", "shared"),
        resumen["packs_de_sistema"], L("de sistema", "system"),
        resumen["packs_de_mundo"], L("de mundo", "world")))
    if resumen["packs_sin_analizar"] or resumen["packs_ilegibles"] or resumen["packs_invalidos"]:
        print("     %s: %d %s, %d %s, %d %s" % (
            L("sin analizar", "not analyzed"),
            resumen["packs_sin_analizar"], L("por formato", "by format"),
            resumen["packs_ilegibles"], L("ilegibles", "unreadable"),
            resumen["packs_invalidos"], L("invalidos", "invalid")))
    print("  %s: %d | %s: %d (%d %s, %d %s, %d %s, %d %s)" % (
        L("Mundos", "Worlds"), resumen["mundos_total"],
        L("Referencias de packs", "Pack references"), resumen["referencias_total"],
        resumen["referencias_resueltas"], L("resueltas", "resolved"),
        resumen["referencias_sin_resolver"], L("sin resolver", "unresolved"),
        resumen["referencias_ambiguas"], L("ambiguas", "ambiguous"),
        resumen["referencias_sin_version"], L("sin version exacta", "without exact version")))
    print("  %s: %d (%d %s, %d %s, %d %s)" % (
        L("Diagnosticos", "Diagnostics"), resumen["diagnosticos_total"],
        resumen["errores"], L("errores", "errors"),
        resumen["avisos"], L("avisos", "warnings"),
        resumen["informativos"], L("informativos", "informational")))


def _severidades_visibles(opciones):
    if opciones["severity"] == "todos":
        return ("error", "aviso", "info")
    if opciones["severity"] == "error":
        return ("error",)
    return ("error", "aviso")


def _packs_legibles(vista, opciones, idioma):
    visibles = _severidades_visibles(opciones)
    por_scope = {}
    for pack in vista["packs"]:
        por_scope.setdefault(pack["scope"], []).append(pack)
    for scope in vista["scopes"]:
        packs = por_scope.get(scope["id"])
        if not packs:
            continue
        print()
        print(_color("== %s (%s) ==" % (scope["id"], scope["root"]), "titulo", opciones["color"]))
        for pack in packs:
            nombre = pack["name"] or L("(sin nombre)", "(no name)")
            estado = "" if pack["status"] == "ok" else " [%s]" % pack["status"].upper()
            print("  * %s%s" % (nombre, estado))
            print("      %s: %s" % (L("ruta", "path"), pack["folder"]))
            if pack["description"]:
                print("      %s: %s" % (L("descripcion", "description"),
                                        pack["description"]))
            uuid = pack["header_uuid"] or L("sin UUID", "no UUID")
            print("      %s: %s | format_version: %s | %s: %s" % (
                "UUID", uuid, pack["format_version"],
                L("version", "version"), addon_inventory.texto_version(pack["version"])))
            if pack["status"] == "unsupported":
                print("      %s: %s" % (L("motivo", "reason"), pack["unsupported_reason"]))
            if pack["referenced_by_worlds"]:
                print("      %s: %s" % (L("mundos que lo referencian", "worlds referencing it"),
                                        ", ".join(pack["referenced_by_worlds"])))
            if opciones["detalle"]:
                for modulo in pack["modules"]:
                    print("      - %s %s %s" % (
                        L("modulo", "module"), modulo["type"] or "?",
                        modulo["uuid"] or L("sin UUID", "no UUID")))
                for dep in pack["pack_dependencies"]:
                    print("      - %s %s %s" % (
                        L("dependencia de pack", "pack dependency"),
                        dep["uuid"] or "?", addon_inventory.texto_version(dep["version"])))
                for dep in pack["script_dependencies"]:
                    print("      - %s %s %s" % (
                        L("dependencia de scripting", "scripting dependency"),
                        dep["module_name"] or "?", dep["version"]))
                for resolucion in pack["dependency_resolution"]:
                    if resolucion["status"] != "resolved":
                        print("      - %s %s -> %s (%s)" % (
                            L("resolucion", "resolution"), resolucion["uuid"],
                            resolucion["status"],
                            ", ".join(c["pack"] for c in resolucion["candidates"])))
                    for contexto in resolucion.get("world_resolutions", []):
                        if contexto["world"] is not None:
                            print("        %s %s: %s -> %s" % (
                                L("mundo", "world"), contexto["world"], resolucion["uuid"],
                                contexto["status"]))
            codigos_pack = sorted({
                code for code in set(pack["diagnostic_codes"])
                if addon_inventory.CATALOGO[code]["severity"] in visibles
            })
            if codigos_pack:
                print("      %s: %s" % (L("diagnosticos", "diagnostics"),
                                        ", ".join(codigos_pack)))


def _mundos_legibles(vista, opciones, idioma):
    if not vista["worlds"]:
        return
    print()
    print(_color("== %s ==" % L("MUNDOS", "WORLDS"), "titulo", opciones["color"]))
    for mundo in vista["worlds"]:
        marcas = []
        if mundo["active"]:
            marcas.append(L("activo", "active"))
        if not mundo["has_level_dat"]:
            marcas.append(L("sin level.dat", "no level.dat"))
        sufijo = (" [%s]" % ", ".join(marcas)) if marcas else ""
        print("  * %s%s" % (mundo["name"], sufijo))
        for estado in mundo["ref_files"]:
            print("      %s: %s" % (estado["file"].rsplit("/", 1)[-1], estado["status"]))
        for ref in mundo["references"]:
            destino = ""
            if ref["candidates"]:
                destino = " -> %s" % ", ".join(c["pack"] for c in ref["candidates"])
            print("      %s %s %s [%s]%s" % (
                L("referencia", "reference"), ref["pack_id"] or "?",
                addon_inventory.texto_version(ref["version"]), ref["status"], destino))
            if opciones["detalle"]:
                print("        (%s)" % ref["file"].rsplit("/", 1)[-1])


def _diagnosticos_legibles(vista, opciones, idioma):
    severidades = _severidades_visibles(opciones)
    visibles = [d for d in vista["diagnostics"] if d["severity"] in severidades]
    print()
    print(_color("== %s ==" % L("DIAGNOSTICOS", "DIAGNOSTICS"), "titulo", opciones["color"]))
    if not visibles:
        print("  %s" % _color(L("Sin diagnosticos con esa gravedad.", "No diagnostics at that severity."),
                              "ok", opciones["color"]))
        return
    for diagnostico in visibles:
        print("  [%s] %s" % (_color(diagnostico["severity"], diagnostico["severity"], opciones["color"]),
                             diagnostico["code"]))
        print("      %s: %s" % (L("archivo", "file"), diagnostico["source_file"]))
        if diagnostico["field"]:
            print("      %s: %s" % (L("campo", "field"), diagnostico["field"]))
        print("      %s: %s" % (L("fuente", "source"), diagnostico["source"]))
        if not diagnostico["determined"]:
            print("      %s" % L("resultado no determinado por la documentacion consultada",
                                 "result not determined by the consulted documentation"))
        print("      %s" % _mensaje(diagnostico, idioma))


def _no_analizados_legibles(vista, opciones, idioma):
    if not vista["not_analyzed"]:
        return
    print()
    print(_color("== %s ==" % L("NO ANALIZADOS", "NOT ANALYZED"), "titulo", opciones["color"]))
    for item in vista["not_analyzed"]:
        detalle = " (%s)" % item["detail"] if item["detail"] else ""
        print("  - %s -> %s%s" % (item["path"], item["reason_code"], detalle))


def imprimir_legible(payload, vista, opciones):
    idioma = opciones["idioma"]
    color = opciones["color"]
    linea = "=" * 70
    print(_color(linea, "titulo", color))
    print(_color("  %s" % L("INVENTARIO DE ADDONS (solo lectura)", "ADDON INVENTORY (read-only)"),
                 "titulo", color))
    print(_color(linea, "titulo", color))
    print("%s: %s" % (L("Instalacion", "Installation"), payload["base_dir"]))
    print("%s (level-name): %s" % (
        L("Mundo activo", "Active world"), payload["active_world"] or L("no determinada", "not determined")))
    if payload["complete"]:
        estado = _color(L("COMPLETO", "COMPLETE"), "ok", color)
    else:
        estado = _color(L("PARCIAL", "PARTIAL"), "aviso", color)
    print("%s: %s" % (L("Estado del inventario", "Inventory state"), estado))
    if payload["partial_reasons"]:
        print("  %s: %s" % (L("motivos", "reasons"), ", ".join(payload["partial_reasons"])))
    print("%s: manifest format_version %s" % (
        L("Formatos soportados", "Supported formats"),
        ", ".join(str(v) for v in payload["supported"]["manifest_format_versions"])))
    print("  %s: %s" % (L("Ubicaciones exploradas", "Scanned locations"),
                        ", ".join(payload["supported"]["locations"])))
    if vista.get("filter"):
        print("%s: %s" % (L("Filtro aplicado", "Applied filter"),
                          json.dumps(vista["filter"], ensure_ascii=False)))
    print()
    _resumen_legible(vista, opciones)
    _packs_legibles(vista, opciones, idioma)
    _mundos_legibles(vista, opciones, idioma)
    _diagnosticos_legibles(vista, opciones, idioma)
    _no_analizados_legibles(vista, opciones, idioma)
    print()
    print(L("Codigos de salida: 0 = sin hallazgos; 1 = hay errores; 2 = inventario parcial; "
            "3 = error de uso; 4 = fallo interno.",
            "Exit codes: 0 = no findings; 1 = errors present; 2 = partial inventory; "
            "3 = usage error; 4 = internal failure."))


def imprimir_catalogo(opciones):
    idioma = opciones["idioma"]
    print(_color("== %s ==" % L("CATALOGO DE CODIGOS", "DIAGNOSTIC CODE CATALOG"),
                 "titulo", opciones["color"]))
    for entrada in addon_inventory.catalogo_publico():
        print("  %s [%s] %s%s" % (
            entrada["code"], entrada["severity"], L("fuente", "source") + ": " + entrada["source"],
            " | " + L("inventario parcial", "partial inventory") if entrada["partial"] else ""))
        print("      %s" % (entrada["message_es"] if idioma == "es" else entrada["message_en"]))


# ---------------------------------------------------------------------------
# Codigos de salida
# ---------------------------------------------------------------------------

def codigo_salida(payload):
    """Codigo de salida documentado, calculado sobre la INSTALACION completa."""
    if not payload["complete"]:
        return EXIT_PARCIAL
    if any(d["severity"] == "error" for d in payload["diagnostics"]):
        return EXIT_HALLAZGOS
    return EXIT_OK


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)
    _configurar_salida()
    opciones = {
        "idioma": args.lang or idioma_activo(),
        "severity": args.severity,
        "detalle": args.detalle,
        "color": not args.no_color and sys.stdout.isatty(),
    }
    if args.compact and not args.json:
        print(L("[ERROR] --compact solo tiene sentido con --json.",
                "[ERROR] --compact only makes sense with --json."), file=sys.stderr)
        return EXIT_USO
    if args.severity != "aviso" and args.json and not args.codes:
        print(L("[AVISO] --severity no se aplica a la salida JSON: el payload es completo.",
                "[WARNING] --severity does not apply to JSON output: the payload is complete."),
              file=sys.stderr)

    previo = os.environ.get("WRAPPER_LANG")
    if args.lang:
        os.environ["WRAPPER_LANG"] = args.lang
    try:
        if opciones["color"]:
            _habilitar_ansi_windows()
        if args.codes:
            imprimir_catalogo(opciones)
            return EXIT_OK
        raiz = os.path.abspath(args.root or os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isdir(raiz):
            print(L(f"[ERROR] La instalacion indicada no existe o no es una carpeta: {raiz}",
                    f"[ERROR] The given installation does not exist or is not a folder: {raiz}"),
                  file=sys.stderr)
            return EXIT_USO
        payload = addon_inventory.analyze_addons(raiz)
        vista = addon_inventory.filter_payload(payload, world=args.world, kind=args.kind)
        if args.json:
            print(json.dumps(vista, ensure_ascii=False,
                             indent=None if args.compact else 2,
                             separators=(",", ":") if args.compact else None))
        else:
            imprimir_legible(payload, vista, opciones)
        return codigo_salida(payload)
    except Exception as exc:  # pragma: no cover - salvaguarda de ultimo recurso
        print(L(f"[ERROR] Fallo interno del analizador: {type(exc).__name__}: {exc}",
                f"[ERROR] Internal analyzer failure: {type(exc).__name__}: {exc}"),
              file=sys.stderr)
        return EXIT_INTERNO
    finally:
        if args.lang:
            if previo is None:
                os.environ.pop("WRAPPER_LANG", None)
            else:
                os.environ["WRAPPER_LANG"] = previo


if __name__ == "__main__":
    raise SystemExit(main())
