# -*- coding: utf-8 -*-
"""
Property-based tests del sistema bilingue de la consola (cambios i18n).

Cubre tres contratos:
  1) console_lang.L(es, en) / set_lang: selector determinista cuyo resultado
     es SIEMPRE uno de sus dos argumentos, elegido segun WRAPPER_LANG, y
     set_lang solo acepta "es"/"en" (no-op en cualquier otro caso).
  2) Contrato de placeholders: toda llamada L(es, en) en el codigo fuente
     debe tener el MISMO conjunto de placeholders {..} en ambos argumentos
     (ambos f-strings se evaluan con las mismas variables; si divergieran,
     el segundo argumento lanzaria KeyError en runtime).
  3) i18n.jsx (frontend): las claves y los placeholders de cada mensaje son
     SIMETRICOS entre el bloque es: y el bloque en:.
"""
import sys, os, re, ast, io, keyword
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from hypothesis import given, strategies as st, settings, example, HealthCheck, assume
import console_lang as cl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─────────────────────────────────────────────────────────────
# Estrategias de generacion
# ─────────────────────────────────────────────────────────────

# Idioma arbitrario: texto sin control chars ni surrogates (os.environ no los
# soporta; los mensajes en cambio si pueden contener cualquier caracter).
lang_any = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=0, max_size=20,
)

# Mensaje arbitrario: cualquier texto, incluidos vacio, unicode y llaves sueltas.
msg_any = st.text(min_size=0, max_size=200)

# Identificadores validos de placeholder (para construir templates f-string):
# primer caracter letra (Python requiere identificadores validos en {..}).
@st.composite
def placeholder_names(draw):
    n = draw(st.integers(min_value=1, max_value=4))
    first = draw(st.characters(whitelist_categories=("Ll", "Lu"), max_codepoint=0x7F))
    rest_chars = st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        max_codepoint=0x7F,
    )
    rest = draw(st.lists(
        st.text(alphabet=rest_chars, min_size=0, max_size=11),
        min_size=n, max_size=n, unique=True,
    ))
    return [first + r for r in rest]


# ─────────────────────────────────────────────────────────────
# 1) console_lang: oraculo de seleccion + validacion de idioma
# ─────────────────────────────────────────────────────────────

@given(msg_any, msg_any, lang_any)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_L_oraculo(es, en, lang):
    """Oracle: L devuelve es si WRAPPER_LANG=='es', en en cualquier otro caso
    (incluidos idiomas invalidos, vacio o ausente)."""
    cl.set_lang(lang)
    esperado = es if lang == "es" else en
    assert cl.L(es, en) == esperado


@given(msg_any, msg_any, lang_any)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_L_no_corrompe_ni_mezcla(es, en, lang):
    """Invariante: el resultado es SIEMPRE uno de los dos argumentos, nunca
    una transformacion, concatenacion o texto ajeno (p.ej. corrupciones de
    caracteres como las vistas en la refactorizacion)."""
    cl.set_lang(lang)
    out = cl.L(es, en)
    assert out in (es, en)
    assert type(out) is str


@given(lang_any)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@example("es")
@example("en")
@example("")
@example("español")
def test_set_lang_acepta_solo_es_en(lang):
    """set_lang devuelve True SOLO para 'es'/'en'; el env solo cambia ahi."""
    estado_previo = os.environ.get("WRAPPER_LANG")
    ok = cl.set_lang(lang)
    if lang in cl.VALID_LANGS:
        assert ok is True
        assert os.environ.get("WRAPPER_LANG") == lang
    else:
        assert ok is False
        assert os.environ.get("WRAPPER_LANG") == estado_previo


@given(lang_any)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_set_lang_idempotente(lang):
    """Fijar dos veces el mismo idioma deja el estado en ese idioma."""
    cl.set_lang(lang)
    cl.set_lang(lang)
    if lang in cl.VALID_LANGS:
        assert os.environ.get("WRAPPER_LANG") == lang


# ─────────────────────────────────────────────────────────────
# 2) Contrato de placeholders en las llamadas L(es, en) del codigo
# ─────────────────────────────────────────────────────────────

def extract_placeholders(node):
    """Textos de los placeholders {..} de un argumento de L().

    Recibe un nodo AST (ast.Constant o ast.JoinedStr). Devuelve frozenset
    vacio para strings planos; frozenset con ast.unparse de cada FormattedValue
    para f-strings; None para cualquier otro tipo (contrato roto).
    """
    if isinstance(node, ast.Constant):
        return frozenset()
    if isinstance(node, ast.JoinedStr):
        return frozenset(
            ast.unparse(v.value)
            for v in node.values
            if isinstance(v, ast.FormattedValue)
        )
    return None


@given(placeholder_names())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@example([])
@example(["e"])
@example(["a", "a"])  # placeholder repetido -> conjunto unico
def test_extract_placeholders_roundtrip(names):
    """Roundtrip: un template construido con N placeholders expone exactamente
    ese conjunto (con repeticiones colapsadas al conjunto)."""
    # Los placeholders de un f-string deben ser identificadores validos:
    # las keywords de Python ('or', 'as', 'in'...) no lo son y romperian el
    # ast.parse del template. La estrategia puede generarlas; se descartan.
    assume(not any(keyword.iskeyword(n) for n in names))
    if not names:
        template = '"solo texto fijo"'
    else:
        template = 'f"inicio {' + "} medio {".join(names) + '} fin"'
    node = ast.parse(template, mode="eval").body
    assert extract_placeholders(node) == frozenset(names)


def _find_L_calls(path):
    """Todas las llamadas L(es, en) con 2 argumentos en un archivo .py."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    calls = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "L"
                and len(node.args) == 2):
            calls.append(node.args)
    return calls


L_PY_FILES = [
    "server_wrapper.py",
    "server_gui_server.py",
    "auto_backup.py",
    "backup_worker.py",
    "gui_backend/supervisor.py",
    "gui_backend/services/bds_update.py",
    "gui_backend/routers/actions.py",
    "gui_backend/routers/backups.py",
    "gui_backend/routers/setup.py",
    "gui_backend/routers/system.py",
    "gui_backend/routers/websocket.py",
]


def test_todas_las_L_tienen_mismo_tipo_y_mismos_placeholders():
    """Exhaustivo sobre el codigo real: cada L(es, en) del backend debe tener
    argumentos del mismo tipo (f-string o string plano) y placeholders
    IDENTICOS en ambos idiomas. Sin esto, un placeholder distinto entre ES y
    EN lanzaria KeyError al evaluar el f-string con las variables reales."""
    hallazgos = []
    for rel in L_PY_FILES:
        path = os.path.join(BASE_DIR, rel)
        for args in _find_L_calls(path):
            es, en = args
            ph_es, ph_en = extract_placeholders(es), extract_placeholders(en)
            if ph_es is None or ph_en is None or ph_es != ph_en:
                hallazgos.append(f"{rel}: L({ast.unparse(es)}, {ast.unparse(en)})")
    assert not hallazgos, "L() con placeholders asimetricos:\n" + "\n".join(hallazgos)


# ─────────────────────────────────────────────────────────────
# 3) i18n.jsx: simetria de claves y placeholders es <-> en
# ─────────────────────────────────────────────────────────────

I18N_PATH = os.path.join(BASE_DIR, "gui_frontend", "src", "i18n.jsx")


def _extract_i18n_block(text, lang):
    """Diccionario key -> valor del bloque '  <lang>: { ... }' de i18n.jsx."""
    m = re.search(
        r"^  %s: \{(.*?)^  \},?$" % re.escape(lang),
        text, re.MULTILINE | re.DOTALL,
    )
    assert m, f"bloque i18n '{lang}' no encontrado"
    return dict(re.findall(
        r"^\s{4}(\w+): '((?:[^'\\]|\\.)*)',?\s*$",
        m.group(1), re.MULTILINE,
    ))


def _placeholders_js(value):
    """Conjunto de {var} de un valor i18n (sintaxis de t(key, {vars}))."""
    return frozenset(re.findall(r"\{(\w+)\}", value))


def _i18n_dicts():
    with io.open(I18N_PATH, encoding="utf-8") as f:
        text = f.read()
    es = _extract_i18n_block(text, "es")
    en = _extract_i18n_block(text, "en")
    assert len(es) > 50 and len(en) > 50, "parseo sospechoso de i18n.jsx"
    return es, en


@given(st.sampled_from(sorted(_i18n_dicts()[0].keys())))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@example("filterAll")
@example("filterError")   # regresion: antes existian filterErrors/filterCommands
@example("filterCommand")
@example("searchPlaceholder")
def test_claves_es_simetricas_en_y_con_mismos_placeholders(key):
    """Para cada clave del bloque es: existe la misma en en:, y ambos valores
    tienen los mismos {placeholders} (t() hace replaceAll de cada variable)."""
    es, en = _i18n_dicts()
    assert key in en, f"clave '{key}' falta en el bloque en:"
    assert _placeholders_js(es[key]) == _placeholders_js(en[key]), (
        f"placeholders asimetricos en '{key}': "
        f"es={sorted(_placeholders_js(es[key]))} en={sorted(_placeholders_js(en[key]))}"
    )


def test_simetria_total_de_claves_es_en():
    """Exhaustivo: los conjuntos de claves de es: y en: son identicos."""
    es, en = _i18n_dicts()
    assert set(es) == set(en), {
        "solo en es:": sorted(set(es) - set(en)),
        "solo en en:": sorted(set(en) - set(es)),
    }
