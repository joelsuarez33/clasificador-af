"""Limpieza de texto y embeddings con Vertex AI (compartido por indexado y consulta)."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Literal

from google import genai
from google.genai import types
from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.gcp import es_error_transitorio

logger = logging.getLogger(__name__)

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
MAX_BATCH = 250  # límite de instancias por request de text-embedding-005

_ESPACIOS = re.compile(r"\s+")


def normalizar_denominacion(texto: object) -> str:
    """Normaliza unicode y espacios, conservando mayúsculas (versión para mostrar)."""
    return _ESPACIOS.sub(" ", unicodedata.normalize("NFKC", str(texto))).strip()


def limpiar_denominacion(texto: object) -> str:
    """Versión usada para embeber: espacios normalizados y minúsculas."""
    return normalizar_denominacion(texto).lower()


@retry(
    retry=retry_if_exception(es_error_transitorio),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(6),
    reraise=True,
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _embed_lote(
    client: genai.Client, textos: list[str], *, task_type: TaskType, model: str, dim: int
) -> list[list[float]]:
    respuesta = client.models.embed_content(
        model=model,
        contents=textos,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=dim),
    )
    vectores = [list(e.values) for e in (respuesta.embeddings or [])]
    if len(vectores) != len(textos):
        raise RuntimeError(f"Vertex AI devolvió {len(vectores)} embeddings para {len(textos)} textos")
    return vectores


def embed_textos(
    client: genai.Client,
    textos: list[str],
    *,
    task_type: TaskType,
    model: str = "text-embedding-005",
    dim: int = 768,
    batch_size: int = 100,
) -> list[list[float]]:
    if not 1 <= batch_size <= MAX_BATCH:
        raise ValueError(f"batch_size debe estar entre 1 y {MAX_BATCH}")
    vectores: list[list[float]] = []
    for inicio in range(0, len(textos), batch_size):
        lote = textos[inicio : inicio + batch_size]
        vectores.extend(_embed_lote(client, lote, task_type=task_type, model=model, dim=dim))
    return vectores
