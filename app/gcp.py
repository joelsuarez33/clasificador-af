"""Clientes de Google Cloud autenticados con el archivo de Service Account."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from google import genai
from google.cloud import bigquery
from google.genai import errors as genai_errors
from google.oauth2 import service_account

from app.config import Settings

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
CODIGOS_TRANSITORIOS = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class GcpClients:
    genai: genai.Client
    bigquery: bigquery.Client


def es_error_transitorio(exc: BaseException) -> bool:
    """Errores de Vertex AI que vale la pena reintentar (cuota, timeouts, 5xx)."""
    return isinstance(exc, genai_errors.APIError) and exc.code in CODIGOS_TRANSITORIOS


@lru_cache(maxsize=4)
def crear_clientes(settings: Settings) -> GcpClients:
    # Credenciales explícitas: nunca cae en credenciales de usuario de gcloud.
    credenciales = service_account.Credentials.from_service_account_file(
        str(settings.credentials_path), scopes=list(SCOPES)
    )
    return GcpClients(
        genai=genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.gcp_location,
            credentials=credenciales,
        ),
        bigquery=bigquery.Client(
            project=settings.gcp_project_id,
            credentials=credenciales,
            location=settings.bq_location,
        ),
    )
