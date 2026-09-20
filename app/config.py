"""Configuración: lee `.env` + entorno, valida variables requeridas y la Service Account.

La autenticación es exclusivamente por archivo de Service Account
(GOOGLE_APPLICATION_CREDENTIALS). No hay flujos interactivos ni de navegador.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

REQUIRED_VARS = ("GCP_PROJECT_ID", "BQ_DATASET", "GOOGLE_APPLICATION_CREDENTIALS")

# Identificadores que se interpolan en SQL: se restringen para evitar inyección.
_PROJECT_RE = re.compile(r"^[a-z][a-z0-9\-]{4,28}[a-z0-9]$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


class ConfigError(RuntimeError):
    """La configuración está incompleta o es inválida."""


def verificar_python() -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Se requiere Python 3.12, detectado {sys.version}")


@dataclass(frozen=True)
class Settings:
    gcp_project_id: str
    bq_dataset: str
    credentials_path: Path
    gcp_location: str = "us-central1"
    bq_location: str = "US"
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-005"
    embedding_dim: int = 768
    tabla_historico: str = "af_historico_embeddings"
    tabla_politica: str = "politica_af"
    vector_index: str = "idx_af_historico_embedding"
    catalogo_path: Path = ROOT_DIR / "data" / "catalogo.json"
    af_historico_xlsx: Path = ROOT_DIR / "data" / "AF_definitivos_creados.xlsx"
    politica_af_xlsx: Path = ROOT_DIR / "data" / "Politica_AF.xlsx"
    top_k: int = 15
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str | None = None

    @property
    def dataset_fq(self) -> str:
        return f"{self.gcp_project_id}.{self.bq_dataset}"

    @property
    def tabla_historico_fq(self) -> str:
        return f"{self.dataset_fq}.{self.tabla_historico}"

    @property
    def tabla_politica_fq(self) -> str:
        return f"{self.dataset_fq}.{self.tabla_politica}"


def _resolver_ruta(valor: str) -> Path:
    ruta = Path(valor).expanduser()
    return ruta if ruta.is_absolute() else (ROOT_DIR / ruta).resolve()


def _validar_credenciales(ruta: Path) -> list[str]:
    """Devuelve la lista de problemas encontrados en el archivo de credenciales."""
    if not ruta.exists():
        return [f"GOOGLE_APPLICATION_CREDENTIALS apunta a un archivo inexistente: {ruta}"]
    if not ruta.is_file():
        return [f"GOOGLE_APPLICATION_CREDENTIALS no es un archivo: {ruta}"]
    if not os.access(ruta, os.R_OK):
        return [f"GOOGLE_APPLICATION_CREDENTIALS no es legible (permisos): {ruta}"]
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"El archivo de credenciales no es un JSON válido ({exc.__class__.__name__}): {ruta}"]
    if not isinstance(contenido, dict) or contenido.get("type") != "service_account":
        return [f"El archivo de credenciales no es de tipo 'service_account': {ruta}"]
    faltantes = [k for k in ("client_email", "private_key") if not contenido.get(k)]
    if faltantes:
        return [f"Al JSON de Service Account le faltan campos {faltantes}: {ruta}"]
    return []


def _entero(valores: dict[str, str | None], nombre: str, defecto: int, errores: list[str]) -> int:
    crudo = valores.get(nombre)
    if crudo in (None, ""):
        return defecto
    try:
        valor = int(crudo)
    except ValueError:
        errores.append(f"{nombre} debe ser un entero, recibido {crudo!r}")
        return defecto
    if valor <= 0:
        errores.append(f"{nombre} debe ser positivo, recibido {valor}")
    return valor


def load_settings(env_file: Path | None = ENV_FILE, *, exportar_credenciales: bool = True) -> Settings:
    """Carga y valida la configuración. Lanza ConfigError con el detalle de todo lo que falta.

    Las variables del entorno del proceso tienen prioridad sobre el `.env`.
    """
    archivo = dotenv_values(env_file) if env_file is not None and Path(env_file).exists() else {}
    valores: dict[str, str | None] = {**archivo, **os.environ}

    def val(nombre: str, defecto: str | None = None) -> str | None:
        crudo = valores.get(nombre)
        return crudo.strip() if isinstance(crudo, str) and crudo.strip() else defecto

    errores: list[str] = []
    faltantes = [v for v in REQUIRED_VARS if not val(v)]
    if faltantes:
        errores.append(
            "Faltan variables requeridas: " + ", ".join(faltantes)
            + f". Definilas en {ENV_FILE} (ver .env.example) o en el entorno."
        )

    project = val("GCP_PROJECT_ID") or ""
    dataset = val("BQ_DATASET") or ""
    if project and not _PROJECT_RE.match(project):
        errores.append(f"GCP_PROJECT_ID tiene un formato inválido: {project!r}")
    if dataset and not _IDENT_RE.match(dataset):
        errores.append(f"BQ_DATASET tiene un formato inválido (solo letras, números y _): {dataset!r}")

    tablas = {
        "BQ_TABLA_HISTORICO": val("BQ_TABLA_HISTORICO", Settings.tabla_historico),
        "BQ_TABLA_POLITICA": val("BQ_TABLA_POLITICA", Settings.tabla_politica),
        "BQ_VECTOR_INDEX": val("BQ_VECTOR_INDEX", Settings.vector_index),
    }
    for nombre, valor in tablas.items():
        if not _IDENT_RE.match(valor or ""):
            errores.append(f"{nombre} tiene un formato inválido: {valor!r}")

    credenciales_crudo = val("GOOGLE_APPLICATION_CREDENTIALS")
    credenciales = _resolver_ruta(credenciales_crudo) if credenciales_crudo else Path()
    if credenciales_crudo:
        errores.extend(_validar_credenciales(credenciales))

    top_k = _entero(valores, "TOP_K", Settings.top_k, errores)
    api_port = _entero(valores, "API_PORT", Settings.api_port, errores)
    embedding_dim = _entero(valores, "EMBEDDING_DIM", Settings.embedding_dim, errores)

    if errores:
        raise ConfigError("Configuración inválida:\n  - " + "\n  - ".join(errores))

    if exportar_credenciales:
        # Ruta absoluta para que cualquier SDK de Google la encuentre sin depender del cwd.
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credenciales)

    return Settings(
        gcp_project_id=project,
        bq_dataset=dataset,
        credentials_path=credenciales,
        gcp_location=val("GCP_LOCATION", Settings.gcp_location),
        bq_location=val("BQ_LOCATION", Settings.bq_location),
        gemini_model=val("GEMINI_MODEL", Settings.gemini_model),
        embedding_model=val("EMBEDDING_MODEL", Settings.embedding_model),
        embedding_dim=embedding_dim,
        tabla_historico=tablas["BQ_TABLA_HISTORICO"],
        tabla_politica=tablas["BQ_TABLA_POLITICA"],
        vector_index=tablas["BQ_VECTOR_INDEX"],
        catalogo_path=_resolver_ruta(val("CATALOGO_JSON", "data/catalogo.json")),
        af_historico_xlsx=_resolver_ruta(val("AF_HISTORICO_XLSX", "data/AF_definitivos_creados.xlsx")),
        politica_af_xlsx=_resolver_ruta(val("POLITICA_AF_XLSX", "data/Politica_AF.xlsx")),
        top_k=top_k,
        api_host=val("API_HOST", Settings.api_host),
        api_port=api_port,
        api_key=val("API_KEY"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    verificar_python()
    return load_settings()


if __name__ == "__main__":
    # Chequeo de configuración sin exponer secretos: `python -m app.config`
    try:
        s = get_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    print("Configuración OK")
    print(f"  Proyecto:      {s.gcp_project_id}")
    print(f"  Dataset BQ:    {s.dataset_fq} ({s.bq_location})")
    print(f"  Vertex AI:     {s.gcp_location} | {s.gemini_model} | {s.embedding_model}")
    print(f"  Credenciales:  {s.credentials_path}")
    print(f"  Catálogo JSON: {s.catalogo_path} ({'existe' if s.catalogo_path.exists() else 'NO generado aún'})")
