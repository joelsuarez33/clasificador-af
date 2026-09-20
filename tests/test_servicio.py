import pytest

from app.classifier import Clasificador
from app.models import ClasificacionInput, ClasificacionRespuesta
from app.servicio import ClasificadorAF, formatear_linea
from tests.conftest import respuesta_json


@pytest.fixture
def servicio(catalogo, precedentes, fake_genai):
    def construir(respuestas):
        return ClasificadorAF(
            buscador=lambda denominacion, k: precedentes,
            clasificador=Clasificador(fake_genai(respuestas), catalogo),
            catalogo=catalogo,
        )

    return construir


def test_llamada_estandar_devuelve_una_sola_linea(servicio):
    linea = servicio([respuesta_json(53000010)]).clasificar("Notebook Lenovo", monto=1200)
    assert linea == "53000010 - Equipos de computación"
    assert "\n" not in linea


def test_llamada_estandar_acepta_opciones_de_formato(servicio):
    s = servicio([respuesta_json(53000010)] * 3)
    assert s.clasificar("Notebook", solo_codigo=True) == "53000010"
    assert s.clasificar("Notebook", separador=" | ") == "53000010 | Equipos de computación"
    assert s.clasificar("Notebook", max_largo=12) == "53000010 - E"


def test_contexto_adicional_llega_al_prompt(servicio):
    s = servicio([respuesta_json(53000010)])
    s.clasificar("Notebook", monto=1200, centro_costo="CC-1", orden_compra="OC-9")
    prompt = s.clasificador._client.models.llamadas[0]["contents"][0].parts[0].text
    assert "- centro_costo: " in prompt and "OC-9" in prompt


def test_detallado_devuelve_todo(servicio):
    r = servicio([respuesta_json(53000010, "media")]).clasificar_detallado("Notebook Lenovo")
    assert isinstance(r, ClasificacionRespuesta)
    assert (r.clase_sugerida, r.confianza, r.fallback, r.intentos) == (53000010, "media", False, 1)
    assert len(r.precedentes) == 4


def test_acepta_clasificacion_input(servicio):
    entrada = ClasificacionInput(denominacion="Notebook", proveedor="Lenovo")
    assert servicio([respuesta_json(53000010)]).clasificar(entrada).startswith("53000010")


def test_formatear_linea_colapsa_saltos_de_linea():
    respuesta = ClasificacionRespuesta(
        clase_sugerida=53000010,
        confianza="alta",
        justificacion="x",
        alternativas=[],
        descripcion_clase="Equipos de\ncomputación  y accesorios",
        precedentes=[],
        modelo="gemini-2.5-flash",
        fallback=False,
        intentos=1,
    )
    assert formatear_linea(respuesta) == "53000010 - Equipos de computación y accesorios"
