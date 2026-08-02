# -*- coding: utf-8 -*-
"""
Property-based tests para server_gui_server.py (GUI del wrapper).
Cubre la lógica pura: comparación semántica de versiones (_version_tuple),
el guard anti zip-slip (_is_safe_zip_entry) y el gate de conexiones locales
(_ensure_local).
"""
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from hypothesis import given, strategies as st, settings, HealthCheck
import pytest
from fastapi import HTTPException
import server_gui_server as sgs


# ─────────────────────────────────────────────────────────────
# Estrategias de generación
# ─────────────────────────────────────────────────────────────

# Versión "realista": 1-4 segmentos de 0..9999
version = st.builds(
    lambda segs: ".".join(str(s) for s in segs),
    st.lists(st.integers(min_value=0, max_value=9999), min_size=1, max_size=4),
)

# Versión basura: texto arbitrario (sin control chars), incluye casos inválidos
garbage_version = st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
                          min_size=0, max_size=30)

# Ruta de zip: segmentos con caracteres típicos de archivo
zip_segment = st.text(alphabet=st.characters(
    blacklist_categories=("Cc", "Cs"),
    blacklist_characters="\x00/\\"),
    min_size=0, max_size=20)

# Entrada hostil: mezcla de segmentos normales, "..", segmentos vacíos, backslashes
hostile_name = st.lists(
    st.one_of(zip_segment, st.just(".."), st.just("."), st.just("")),
    min_size=1, max_size=6,
).map(lambda segs: "/".join(segs))

# Nombre normal sin traversal
safe_name = st.lists(zip_segment, min_size=1, max_size=6).filter(
    lambda segs: all(s not in ("", ".", "..") and ":" not in s for s in segs)
).map(lambda segs: "/".join(segs))

# Referencia independiente para el orden de versiones: tuplas numéricas con
# segmentos ausentes = 0 (misma semántica, implementación distinta).
def ref_version_tuple(v):
    segs = tuple(int(x) if x.isdigit() else 0 for x in str(v).split("."))[:4]
    return segs + (0, 0, 0, 0)[: 4 - len(segs)]


# ─────────────────────────────────────────────────────────────
# 1) _version_tuple — comparador semántico de versiones
# ─────────────────────────────────────────────────────────────

@given(version)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_version_no_exception(v):
    """Cualquier versión válida produce una tupla de 4 enteros."""
    t = sgs._version_tuple(v)
    assert isinstance(t, tuple) and len(t) == 4
    assert all(isinstance(x, int) and x >= 0 for x in t)


@given(garbage_version)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_version_garbage_no_exception(v):
    """Ni siquiera texto basura rompe el comparador (segmentos inválidos -> 0)."""
    t = sgs._version_tuple(v)
    assert isinstance(t, tuple) and len(t) == 4
    assert all(isinstance(x, int) for x in t)


@given(version)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_version_padding_invariance(v):
    """Añadir '.0' no cambia el valor: 1.21 == 1.21.0 == 1.21.0.0."""
    assert sgs._version_tuple(v) == sgs._version_tuple(v + ".0")
    assert sgs._version_tuple(v) == sgs._version_tuple(v + ".0.0")


@given(version, version)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_version_oracle_ordering(a, b):
    """El comparador coincide con una implementación de referencia independiente."""
    got = sgs._version_tuple(a) > sgs._version_tuple(b)
    expected = ref_version_tuple(a) > ref_version_tuple(b)
    assert got == expected, f"discrepancia: {a!r} vs {b!r}"


@given(version, version, version)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_version_transitivity(a, b, c):
    """Orden total transitivo: si a>b y b>c entonces a>c."""
    ta, tb, tc = (sgs._version_tuple(x) for x in (a, b, c))
    if ta > tb and tb > tc:
        assert ta > tc, f"transitividad rota: {a!r} > {b!r} > {c!r}"


@given(version, st.integers(min_value=0, max_value=9999))
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_version_append_segment_monotonic(v, k):
    """Añadir un segmento >= 0 nunca disminuye el valor."""
    assert sgs._version_tuple(v) <= sgs._version_tuple(f"{v}.{k}"), f"{v} + .{k}"


# ─────────────────────────────────────────────────────────────
# 2) _is_safe_zip_entry — guard anti zip-slip
# ─────────────────────────────────────────────────────────────

def ref_safe(name):
    """Referencia independiente (regex): rechaza traversal '..', absolutas y 'C:'."""
    norm = name.replace("\\", "/")
    if norm.startswith("/") or os.path.isabs(norm):
        return False
    if re.search(r"(^|/)\.\.(/|$)", norm):
        return False
    if re.match(r"^[^/]*:", norm):
        return False
    return True


@given(hostile_name)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_zip_entry_oracle(name):
    """El guard coincide con la referencia independiente en nombres hostiles."""
    assert sgs._is_safe_zip_entry(name) == ref_safe(name), f"discrepancia: {name!r}"


@given(hostile_name)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_zip_entry_no_escape_invariant(name):
    """Propiedad de seguridad: lo aceptado nunca escapa de BASE_DIR."""
    if sgs._is_safe_zip_entry(name):
        target = os.path.normpath(os.path.join(sgs.BASE_DIR, name.replace("\\", "/")))
        assert target == sgs.BASE_DIR or target.startswith(sgs.BASE_DIR + os.sep), (
            f"escape: {name!r} -> {target}"
        )


@given(safe_name)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_zip_entry_accepts_normal_files(name):
    """Los nombres de archivo normales (sin traversal) siempre se aceptan."""
    assert sgs._is_safe_zip_entry(name) is True, f"rechazado incorrectamente: {name!r}"


@st.composite
def traversal_name(draw):
    """Genera nombres que SÍ contienen traversal '..' en algún punto."""
    segs = draw(st.lists(
        st.one_of(zip_segment, st.just("..")),
        min_size=1, max_size=5,
    ))
    if ".." not in segs:
        segs[draw(st.integers(min_value=0, max_value=len(segs) - 1))] = ".."
    return "/".join(segs)


@given(traversal_name())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_zip_entry_rejects_traversal(name):
    """Todo nombre con un segmento '..' es rechazado."""
    assert sgs._is_safe_zip_entry(name) is False, f"no rechazado: {name!r}"


# ─────────────────────────────────────────────────────────────
# 3) _ensure_local — gate de conexiones locales
# ─────────────────────────────────────────────────────────────

@given(st.text(min_size=0, max_size=50))
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_ensure_local_no_other_exceptions(host):
    """Solo puede lanzar HTTPException 403; los hosts loopback siempre pasan."""
    if host in ("127.0.0.1", "::1"):
        assert sgs._ensure_local(host) is None
        return
    with pytest.raises(HTTPException) as exc:
        sgs._ensure_local(host)
    assert exc.value.status_code == 403


# ─────────────────────────────────────────────────────────────
# 4) _is_allowed_origin — anti-CSRF: navegadores solo desde loopback
# ─────────────────────────────────────────────────────────────

# Origen hostil arbitrario: texto, URLs con host externo, malformadas
origin_text = st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
                      min_size=0, max_size=80)

@st.composite
def local_origin(draw):
    """Origen legitimo: http(s)://127.0.0.1:puerto o http(s)://localhost:puerto."""
    scheme = draw(st.sampled_from(["http", "https"]))
    host = draw(st.sampled_from(["127.0.0.1", "localhost"]))
    port = draw(st.integers(min_value=1, max_value=65535))
    return f"{scheme}://{host}:{port}"


@given(local_origin())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_origin_accepts_local_browser(origin):
    """El navegador de la propia maquina siempre pasa."""
    assert sgs._is_allowed_origin(origin) is True, f"rechazado: {origin!r}"


@given(st.one_of(st.none(), origin_text))
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_origin_consistency(origin):
    """Consistencia: se acepta sii el hostname parseado es loopback.

    Ausencia de Origin (clientes no-navegador) se permite; el filtro de IP
    queda como respaldo. Cualquier host que no sea 127.0.0.1/localhost se
    rechaza; texto malformado sin hostname tambien.
    """
    if origin is None or origin == "":
        assert sgs._is_allowed_origin(origin) is True
        return
    try:
        host = sgs.urlsplit(origin).hostname
    except ValueError:
        host = None
    expected = host in ("127.0.0.1", "localhost")
    assert sgs._is_allowed_origin(origin) is expected, f"{origin!r} -> host={host!r}"


@pytest.mark.parametrize("origin,expected", [
    (None, True),                                    # curl / scripts locales
    ("", True),
    ("http://127.0.0.1:8000", True),                 # GUI React servida por uvicorn
    ("http://localhost:8000", True),
    ("http://127.0.0.1:9999", True),                 # puerto distinto, mismo host
    ("http://evil.example.com", False),              # pagina maliciosa
    ("https://evil.example.com/steal", False),
    ("http://192.168.1.10:8000", False),             # otra maquina de la LAN
    ("http://127.0.0.1.evil.com", False),            # dominio que termina en la IP
    ("not a url", False),                            # malformado sin hostname
])
def test_origin_examples(origin, expected):
    assert sgs._is_allowed_origin(origin) is expected
