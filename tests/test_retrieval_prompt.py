from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models import ClasificacionInput
from app.prompt_builder import build_system_prompt, build_user_prompt, votos_por_clase
from app.retrieval import buscar_precedentes

SETTINGS = Settings(gcp_project_id="proyecto-test", bq_dataset="af", credentials_path=Path("sa.json"))


class FakeBigQuery:
    def __init__(self, filas):
        self.filas = filas
        self.consultas = []

    def query(self, sql, job_config=None):
        self.consultas.append((sql, job_config))
        return SimpleNamespace(result=lambda: self.filas)


def test_buscar_precedentes_embebe_query_y_usa_vector_search(fake_genai):
    genai = fake_genai()
    bq = FakeBigQuery([{"clase": 53000010, "denominacion": "Notebook HP", "distancia": 0.12}])
    clients = SimpleNamespace(genai=genai, bigquery=bq)

    resultado = buscar_precedentes("  NOTEBOOK   Lenovo ", k=5, settings=SETTINGS, clients=clients)

    assert resultado[0].clase == 53000010
    assert resultado[0].similitud == pytest.approx(0.88)
    embed = genai.models.llamadas[0]
    assert embed["contents"] == ["notebook lenovo"]
    assert embed["config"].task_type == "RETRIEVAL_QUERY"
    sql, job_config = bq.consultas[0]
    assert "VECTOR_SEARCH" in sql and "`proyecto-test.af.af_historico_embeddings`" in sql
    assert "top_k => 5" in sql
    assert job_config.query_parameters[0].values == [0.1, 0.2, 0.3]


def test_buscar_precedentes_valida_k():
    with pytest.raises(ValueError):
        buscar_precedentes("x", k=0, settings=SETTINGS, clients=SimpleNamespace())


def test_system_prompt_incluye_catalogo_completo_y_reglas(catalogo):
    prompt = build_system_prompt(catalogo)
    for item in catalogo.items:
        assert str(item.clase) in prompt
    assert "Nunca inventes" in prompt
    assert '"baja"' in prompt


def test_user_prompt_marca_precedentes_fuera_de_catalogo(catalogo, precedentes):
    entrada = ClasificacionInput(denominacion="Notebook Lenovo", monto=900, proveedor="Lenovo")
    prompt = build_user_prompt(entrada, precedentes, catalogo)
    assert "Denominación: Notebook Lenovo" in prompt
    assert '- proveedor: "Lenovo"' in prompt
    assert "clase 99999999 ([FUERA DE CATÁLOGO])" in prompt


def test_votos_excluyen_clases_fuera_de_catalogo(catalogo, precedentes):
    votos = votos_por_clase(precedentes, catalogo)
    assert [v.clase for v in votos] == [53000010, 53000020]
    assert votos[0].cantidad == 2
