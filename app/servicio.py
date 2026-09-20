"""Punto de entrada para otros scripts (p. ej. la automatización de SAP).

Uso estándar — devuelve UNA sola línea, lista para insertar en un campo de SAP:

    from app.servicio import clasificar
    linea = clasificar("Torno CNC", monto=50000)
    # '52000340 - Maquinas (del rubro maquinarias I) CNC'

Uso opcional — misma clasificación, con confianza, justificación, alternativas y precedentes:

    from app.servicio import clasificar_detallado
    r = clasificar_detallado("Torno CNC", monto=50000)
    r.confianza, r.justificacion, r.precedentes

También desde la consola:

    python -m app.servicio "Torno CNC" --monto 50000
    python -m app.servicio "Torno CNC" --detalle
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.catalogo import Catalogo, cargar_catalogo
from app.classifier import ClasificacionFallidaError, Clasificador
from app.config import ConfigError, get_settings
from app.gcp import crear_clientes
from app.models import ClasificacionInput, ClasificacionRespuesta, Precedente
from app.retrieval import buscar_precedentes

logger = logging.getLogger(__name__)

SEPARADOR = " - "

BuscadorPrecedentes = Callable[[str, int], list[Precedente]]


def formatear_linea(
    respuesta: ClasificacionRespuesta,
    *,
    solo_codigo: bool = False,
    separador: str = SEPARADOR,
    max_largo: int | None = None,
) -> str:
    """Arma la línea única de salida. Nunca contiene saltos de línea."""
    if solo_codigo:
        return str(respuesta.clase_sugerida)
    descripcion = " ".join(respuesta.descripcion_clase.split())
    linea = f"{respuesta.clase_sugerida}{separador}{descripcion}"
    return linea[:max_largo] if max_largo else linea


class ClasificadorAF:
    """Orquesta retrieval -> prompt_builder -> classifier."""

    def __init__(
        self,
        *,
        buscador: BuscadorPrecedentes,
        clasificador: Clasificador,
        catalogo: Catalogo,
        top_k: int = 15,
    ):
        self.buscador = buscador
        self.clasificador = clasificador
        self.catalogo = catalogo
        self.top_k = top_k

    def clasificar_detallado(
        self, denominacion: str | ClasificacionInput, **contexto: Any
    ) -> ClasificacionRespuesta:
        """Clasificación completa: clase, confianza, justificación, alternativas y precedentes."""
        entrada = (
            denominacion
            if isinstance(denominacion, ClasificacionInput)
            else ClasificacionInput(denominacion=denominacion, **contexto)
        )
        precedentes = self.buscador(entrada.denominacion, self.top_k)
        resultado = self.clasificador.clasificar(entrada, precedentes)
        salida = resultado.output
        item = self.catalogo.get(salida.clase_sugerida)
        if item is None:  # defensa en profundidad: el clasificador ya lo garantiza
            raise ClasificacionFallidaError(f"Clase {salida.clase_sugerida} fuera de catálogo")
        logger.info(
            "Clasificado %r -> %s (%s, fallback=%s, intentos=%d)",
            entrada.denominacion, salida.clase_sugerida, salida.confianza, resultado.fallback, resultado.intentos,
        )
        return ClasificacionRespuesta(
            **salida.model_dump(),
            descripcion_clase=item.descripcion,
            precedentes=precedentes,
            modelo=self.clasificador.modelo,
            fallback=resultado.fallback,
            intentos=resultado.intentos,
        )

    def clasificar(
        self,
        denominacion: str | ClasificacionInput,
        *,
        solo_codigo: bool = False,
        separador: str = SEPARADOR,
        max_largo: int | None = None,
        **contexto: Any,
    ) -> str:
        """Llamada estándar: una sola línea con la clase resultante."""
        respuesta = self.clasificar_detallado(denominacion, **contexto)
        return formatear_linea(respuesta, solo_codigo=solo_codigo, separador=separador, max_largo=max_largo)


@lru_cache(maxsize=1)
def get_clasificador() -> ClasificadorAF:
    """Instancia compartida: valida configuración, crea clientes y carga el catálogo una sola vez."""
    settings = get_settings()
    clients = crear_clientes(settings)
    catalogo = cargar_catalogo(settings.catalogo_path)
    return ClasificadorAF(
        buscador=lambda denominacion, k: buscar_precedentes(denominacion, k, settings=settings, clients=clients),
        clasificador=Clasificador(clients.genai, catalogo, modelo=settings.gemini_model),
        catalogo=catalogo,
        top_k=settings.top_k,
    )


def clasificar(denominacion: str | ClasificacionInput, **kwargs: Any) -> str:
    """Una línea con la clase sugerida. Ver ClasificadorAF.clasificar."""
    return get_clasificador().clasificar(denominacion, **kwargs)


def clasificar_detallado(denominacion: str | ClasificacionInput, **contexto: Any) -> ClasificacionRespuesta:
    """Resultado completo (confianza, justificación, alternativas, precedentes)."""
    return get_clasificador().clasificar_detallado(denominacion, **contexto)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clasifica un activo fijo y escribe una línea por stdout.")
    parser.add_argument("denominacion", help="Denominación del activo fijo")
    parser.add_argument("--monto", type=float, default=None)
    parser.add_argument("--centro-costo", default=None)
    parser.add_argument("--proveedor", default=None)
    parser.add_argument("--solo-codigo", action="store_true", help="Imprime solo el código de clase")
    parser.add_argument("--separador", default=SEPARADOR, help="Separador entre código y descripción")
    parser.add_argument("--max-largo", type=int, default=None, help="Recorta la línea a N caracteres")
    parser.add_argument("--detalle", action="store_true", help="Imprime el JSON completo en vez de la línea")
    parser.add_argument("--log", default="WARNING", help="Nivel de log (a stderr)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log.upper(), stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    contexto = {
        k: v
        for k, v in (("monto", args.monto), ("centro_costo", args.centro_costo), ("proveedor", args.proveedor))
        if v is not None
    }
    try:
        if args.detalle:
            respuesta = clasificar_detallado(args.denominacion, **contexto)
            print(json.dumps(respuesta.model_dump(), ensure_ascii=False, indent=2))
        else:
            print(
                get_clasificador().clasificar(
                    args.denominacion,
                    solo_codigo=args.solo_codigo,
                    separador=args.separador,
                    max_largo=args.max_largo,
                    **contexto,
                )
            )
    except (ConfigError, ClasificacionFallidaError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
