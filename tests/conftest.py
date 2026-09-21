"""Fixtures compartidas. Ningún test llama a Vertex AI ni a BigQuery: todo va con dobles."""

import json
from types import SimpleNamespace

import pytest

from app.catalogo import Catalogo
from app.models import CatalogoItem, Precedente


@pytest.fixture
def catalogo() -> Catalogo:
    return Catalogo(
        [
            CatalogoItem(clase=51000010, descripcion="Terrenos / propiedades reales", explicacion="Con o sin edificaciones", rubro="Terrenos"),
            CatalogoItem(clase=52000010, descripcion="Sistemas de tanques", explicacion="Para líquidos técnicos y gases", rubro="Equipo Operativo"),
            CatalogoItem(clase=53000010, descripcion="Equipos de computación", explicacion="PCs, notebooks, servidores", rubro="Equipos de oficina"),
            CatalogoItem(clase=53000020, descripcion="Mobiliario de oficina", explicacion="Escritorios, sillas", rubro="Equipos de oficina"),
        ]
    )


@pytest.fixture
def precedentes() -> list[Precedente]:
    return [
        Precedente(clase=53000010, denominacion="Notebook Dell Latitude 5440", distancia=0.05),
        Precedente(clase=53000010, denominacion="Notebook HP ProBook", distancia=0.09),
        Precedente(clase=53000020, denominacion="Escritorio para notebook", distancia=0.30),
        Precedente(clase=99999999, denominacion="Notebook clase vieja", distancia=0.08),
    ]


class FakeModels:
    """Doble de `client.models` de google-genai: devuelve respuestas predefinidas en orden."""

    def __init__(self, respuestas: list[str]):
        self._respuestas = list(respuestas)
        self.llamadas: list[dict] = []

    def generate_content(self, *, model, contents, config):
        self.llamadas.append({"model": model, "contents": list(contents), "config": config})
        return SimpleNamespace(text=self._respuestas.pop(0), parsed=None)

    def embed_content(self, *, model, contents, config):
        self.llamadas.append({"model": model, "contents": list(contents), "config": config})
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3]) for _ in contents])


class FakeGenaiClient:
    def __init__(self, respuestas: list[str] | None = None):
        self.models = FakeModels(respuestas or [])


@pytest.fixture
def fake_genai():
    return FakeGenaiClient


def respuesta_json(
    clase: int,
    confianza: str = "alta",
    alternativas: list[dict] | None = None,
    denominacion: str = "Notebook Lenovo ThinkPad",
) -> str:
    return json.dumps(
        {
            "clase_sugerida": clase,
            "denominacion_sugerida": denominacion,
            "confianza": confianza,
            "justificacion": "Precedentes muy similares.",
            "alternativas": alternativas or [],
        }
    )
