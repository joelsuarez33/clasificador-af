"""API HTTP OPCIONAL sobre app.servicio.

El uso principal es llamar `app.servicio.clasificar()` desde otro script (ver README).
Esta capa solo existe para probar desde el navegador (/docs) o integrar por HTTP;
se puede borrar sin afectar la lógica de clasificación.

    POST /clasificar          -> text/plain, una línea: "52000340 - Maquinas ... CNC"
    POST /clasificar/detalle  -> JSON completo (confianza, justificación, precedentes)
"""

import sys

assert sys.version_info[:2] == (3, 12), f"Se requiere Python 3.12, detectado {sys.version}"

import logging
import os
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from google.api_core import exceptions as gcp_exceptions
from google.genai import errors as genai_errors

from app import __version__
from app.classifier import ClasificacionFallidaError
from app.config import get_settings
from app.models import ClasificacionInput, ClasificacionRespuesta
from app.servicio import ClasificadorAF, formatear_linea, get_clasificador

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("clasificador_af")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # falla con ConfigError explícito si falta configuración
    app.state.clasificador = get_clasificador()
    app.state.api_key = settings.api_key
    logger.info(
        "Servicio listo: %d clases, modelo %s", len(app.state.clasificador.catalogo), settings.gemini_model
    )
    yield


app = FastAPI(title="Clasificador de Activos Fijos", version=__version__, lifespan=lifespan)


def get_servicio(request: Request) -> ClasificadorAF:
    servicio = getattr(request.app.state, "clasificador", None)
    if servicio is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no inicializado")
    return servicio


def verificar_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    esperada = getattr(request.app.state, "api_key", None)
    if esperada and not (x_api_key and secrets.compare_digest(x_api_key, esperada)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-API-Key inválida o ausente")


def _clasificar(servicio: ClasificadorAF, entrada: ClasificacionInput) -> ClasificacionRespuesta:
    try:
        return servicio.clasificar_detallado(entrada)
    except ClasificacionFallidaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except (genai_errors.APIError, gcp_exceptions.GoogleAPIError) as exc:
        logger.exception("Error de Google Cloud clasificando %r", entrada.denominacion)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Error al consultar Google Cloud ({exc.__class__.__name__}); reintentar más tarde",
        ) from exc


@app.post(
    "/clasificar",
    response_class=PlainTextResponse,
    dependencies=[Depends(verificar_api_key)],
    responses={200: {"content": {"text/plain": {"example": "52000340 - Maquinas (del rubro maquinarias I) CNC"}}}},
)
def clasificar(
    entrada: ClasificacionInput, servicio: ClasificadorAF = Depends(get_servicio)
) -> PlainTextResponse:
    return PlainTextResponse(formatear_linea(_clasificar(servicio, entrada)))


@app.post("/clasificar/detalle", response_model=ClasificacionRespuesta, dependencies=[Depends(verificar_api_key)])
def clasificar_detalle(
    entrada: ClasificacionInput, servicio: ClasificadorAF = Depends(get_servicio)
) -> ClasificacionRespuesta:
    return _clasificar(servicio, entrada)


def run() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    run()
