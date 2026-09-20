"""Búsqueda de precedentes históricos similares con BigQuery VECTOR_SEARCH."""

from __future__ import annotations

from google.cloud import bigquery

from app.config import Settings, get_settings
from app.embeddings import embed_textos, limpiar_denominacion
from app.gcp import GcpClients, crear_clientes
from app.models import Precedente

K_MAX = 100


def construir_sql(tabla_fq: str, k: int) -> str:
    # top_k se interpola como entero validado; el embedding va como parámetro.
    return f"""
SELECT
  base.clase AS clase,
  base.denominacion AS denominacion,
  distance AS distancia
FROM VECTOR_SEARCH(
  TABLE `{tabla_fq}`,
  'embedding',
  (SELECT @query_embedding AS embedding),
  'embedding',
  top_k => {int(k)},
  distance_type => 'COSINE'
)
ORDER BY distancia ASC
"""


def buscar_precedentes(
    denominacion: str,
    k: int = 15,
    *,
    settings: Settings | None = None,
    clients: GcpClients | None = None,
) -> list[Precedente]:
    if not 1 <= k <= K_MAX:
        raise ValueError(f"k debe estar entre 1 y {K_MAX}")
    texto = limpiar_denominacion(denominacion)
    if not texto:
        return []

    settings = settings or get_settings()
    clients = clients or crear_clientes(settings)

    [vector] = embed_textos(
        clients.genai,
        [texto],
        task_type="RETRIEVAL_QUERY",
        model=settings.embedding_model,
        dim=settings.embedding_dim,
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("query_embedding", "FLOAT64", vector)]
    )
    filas = clients.bigquery.query(
        construir_sql(settings.tabla_historico_fq, k), job_config=job_config
    ).result()
    return [
        Precedente(clase=int(f["clase"]), denominacion=f["denominacion"], distancia=float(f["distancia"]))
        for f in filas
    ]
