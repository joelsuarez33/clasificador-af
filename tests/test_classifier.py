import pytest

from app.classifier import MAX_REINTENTOS, ClasificacionFallidaError, Clasificador
from app.models import ClasificacionInput, ClasificacionOutput
from tests.conftest import respuesta_json

ENTRADA = ClasificacionInput(denominacion="Notebook Lenovo ThinkPad", monto=1200)


def _texto_ultimo_turno(llamada) -> str:
    return llamada["contents"][-1].parts[0].text


def test_clase_valida_primer_intento(catalogo, precedentes, fake_genai):
    client = fake_genai([respuesta_json(53000010)])
    resultado = Clasificador(client, catalogo).clasificar(ENTRADA, precedentes)

    assert resultado.output.clase_sugerida == 53000010
    assert resultado.fallback is False
    assert resultado.intentos == 1
    llamada = client.models.llamadas[0]
    assert llamada["model"] == "gemini-2.5-flash"
    assert llamada["config"].response_schema is ClasificacionOutput
    assert "53000010" in llamada["config"].system_instruction


def test_clase_invalida_reintenta_reinyectando_error(catalogo, precedentes, fake_genai):
    client = fake_genai([respuesta_json(12345678), respuesta_json(53000010, "media")])
    resultado = Clasificador(client, catalogo).clasificar(ENTRADA, precedentes)

    assert resultado.output.clase_sugerida == 53000010
    assert resultado.fallback is False
    assert resultado.intentos == 2
    segunda = client.models.llamadas[1]
    # historial: prompt original, respuesta inválida del modelo, corrección con el error
    assert [c.role for c in segunda["contents"]] == ["user", "model", "user"]
    assert "12345678 no existe en el catálogo" in _texto_ultimo_turno(segunda)


def test_json_malformado_reintenta(catalogo, precedentes, fake_genai):
    client = fake_genai(['{"clase_sugerida": 53000010', respuesta_json(53000010)])
    resultado = Clasificador(client, catalogo).clasificar(ENTRADA, precedentes)

    assert resultado.output.clase_sugerida == 53000010
    assert "no respeta el esquema" in _texto_ultimo_turno(client.models.llamadas[1])


def test_agota_reintentos_y_usa_fallback_validado(catalogo, precedentes, fake_genai):
    client = fake_genai([respuesta_json(99999999)] * (1 + MAX_REINTENTOS))
    resultado = Clasificador(client, catalogo).clasificar(ENTRADA, precedentes)

    assert len(client.models.llamadas) == 1 + MAX_REINTENTOS
    assert resultado.fallback is True
    assert resultado.output.confianza == "baja"
    # 99999999 aparece en precedentes pero está fuera de catálogo: nunca puede devolverse
    assert resultado.output.clase_sugerida == 53000010
    assert catalogo.contiene(resultado.output.clase_sugerida)
    assert all(catalogo.contiene(a.clase) for a in resultado.output.alternativas)
    assert "NO validada" in resultado.output.justificacion


def test_fallback_sin_precedentes_validos_falla_explicito(catalogo, fake_genai):
    from app.models import Precedente

    client = fake_genai([respuesta_json(99999999)] * (1 + MAX_REINTENTOS))
    solo_invalidos = [Precedente(clase=99999999, denominacion="x", distancia=0.1)]
    with pytest.raises(ClasificacionFallidaError):
        Clasificador(client, catalogo).clasificar(ENTRADA, solo_invalidos)


def test_alternativas_fuera_de_catalogo_se_descartan(catalogo, precedentes, fake_genai):
    alternativas = [
        {"clase": 11111111, "motivo": "inventada"},
        {"clase": 53000010, "motivo": "igual a la sugerida"},
        {"clase": 53000020, "motivo": "mobiliario"},
    ]
    client = fake_genai([respuesta_json(53000010, alternativas=alternativas)])
    resultado = Clasificador(client, catalogo).clasificar(ENTRADA, precedentes)

    assert [a.clase for a in resultado.output.alternativas] == [53000020]
