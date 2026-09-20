"""La API es una capa opcional sobre app.servicio."""

import pytest
from fastapi.testclient import TestClient

from app.classifier import Clasificador
from app.main import app, get_servicio
from app.servicio import ClasificadorAF
from tests.conftest import respuesta_json


@pytest.fixture
def cliente_http(catalogo, precedentes, fake_genai):
    def construir(respuestas, api_key=None):
        servicio = ClasificadorAF(
            buscador=lambda denominacion, k: precedentes,
            clasificador=Clasificador(fake_genai(respuestas), catalogo),
            catalogo=catalogo,
        )
        app.dependency_overrides[get_servicio] = lambda: servicio
        app.state.api_key = api_key
        return TestClient(app)  # sin `with`: no corre el lifespan real (no toca GCP)

    yield construir
    app.dependency_overrides.clear()
    app.state.api_key = None


def test_clasificar_devuelve_una_linea_de_texto(cliente_http):
    resp = cliente_http([respuesta_json(53000010)]).post(
        "/clasificar", json={"denominacion": "Notebook Lenovo", "monto": 1200}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "53000010 - Equipos de computación"


def test_detalle_devuelve_json_completo(cliente_http):
    resp = cliente_http([respuesta_json(53000010)]).post(
        "/clasificar/detalle", json={"denominacion": "Notebook Lenovo"}
    )
    cuerpo = resp.json()
    assert cuerpo["clase_sugerida"] == 53000010
    assert cuerpo["descripcion_clase"] == "Equipos de computación"
    assert cuerpo["fallback"] is False
    assert len(cuerpo["precedentes"]) == 4


def test_clasificar_input_invalido(cliente_http):
    assert cliente_http([]).post("/clasificar", json={"monto": 10}).status_code == 422


def test_clasificar_nunca_devuelve_codigo_no_validado(cliente_http, catalogo):
    resp = cliente_http([respuesta_json(12345678)] * 3).post("/clasificar", json={"denominacion": "Notebook"})
    assert resp.status_code == 200
    assert catalogo.contiene(int(resp.text.split(" - ")[0]))


def test_api_key(cliente_http):
    cliente = cliente_http([respuesta_json(53000010)], api_key="secreto")
    assert cliente.post("/clasificar", json={"denominacion": "x"}).status_code == 401
    ok = cliente.post("/clasificar", json={"denominacion": "x"}, headers={"X-API-Key": "secreto"})
    assert ok.status_code == 200
