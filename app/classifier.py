"""Clasificación con Gemini (Vertex AI) y validación estricta contra el catálogo."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from google import genai
from google.genai import types
from pydantic import ValidationError
from tenacity import (
    Retrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.catalogo import Catalogo
from app.gcp import es_error_transitorio
from app.models import AlternativaClase, ClasificacionInput, ClasificacionOutput, Precedente
from app.prompt_builder import build_correccion, build_system_prompt, build_user_prompt, votos_por_clase

logger = logging.getLogger(__name__)

MAX_REINTENTOS = 2  # además del intento inicial
MAX_ALTERNATIVAS = 3


class RespuestaInvalidaError(ValueError):
    """La respuesta del modelo no respeta el esquema o propone un código fuera del catálogo."""


class ClasificacionFallidaError(RuntimeError):
    """No hay ninguna clase validada que devolver (ni del modelo ni de precedentes)."""


@dataclass(frozen=True)
class ResultadoClasificacion:
    output: ClasificacionOutput
    fallback: bool
    intentos: int


class Clasificador:
    def __init__(
        self,
        client: genai.Client,
        catalogo: Catalogo,
        *,
        modelo: str = "gemini-2.5-flash",
        temperatura: float = 0.0,
    ):
        self._client = client
        self.catalogo = catalogo
        self.modelo = modelo
        self._config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(catalogo),
            temperature=temperatura,
            response_mime_type="application/json",
            response_schema=ClasificacionOutput,
        )

    def clasificar(self, entrada: ClasificacionInput, precedentes: list[Precedente]) -> ResultadoClasificacion:
        historial: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=build_user_prompt(entrada, precedentes, self.catalogo))])
        ]
        intentos = 0
        try:
            for intento in Retrying(
                stop=stop_after_attempt(1 + MAX_REINTENTOS),
                retry=retry_if_exception_type(RespuestaInvalidaError),
                reraise=True,
            ):
                with intento:
                    intentos = intento.retry_state.attempt_number
                    output = self._intentar(historial)
                    return ResultadoClasificacion(output=output, fallback=False, intentos=intentos)
        except RespuestaInvalidaError as exc:
            logger.warning("Clasificación sin validar tras %d intentos: %s", intentos, exc)
            return ResultadoClasificacion(
                output=self._fallback(entrada.denominacion, precedentes, str(exc), intentos),
                fallback=True,
                intentos=intentos,
            )
        raise AssertionError("inalcanzable")  # pragma: no cover

    def _llamar_modelo(self, historial: list[types.Content]) -> types.GenerateContentResponse:
        for intento in Retrying(
            retry=retry_if_exception(es_error_transitorio),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            stop=stop_after_attempt(4),
            reraise=True,
        ):
            with intento:
                return self._client.models.generate_content(
                    model=self.modelo, contents=list(historial), config=self._config
                )
        raise AssertionError("inalcanzable")  # pragma: no cover

    def _intentar(self, historial: list[types.Content]) -> ClasificacionOutput:
        respuesta = self._llamar_modelo(historial)
        texto = respuesta.text or ""
        historial.append(types.Content(role="model", parts=[types.Part(text=texto or "(respuesta vacía)")]))

        def rechazar(error: str) -> RespuestaInvalidaError:
            historial.append(types.Content(role="user", parts=[types.Part(text=build_correccion(error))]))
            return RespuestaInvalidaError(error)

        parsed = getattr(respuesta, "parsed", None)
        if isinstance(parsed, ClasificacionOutput):
            output = parsed
        else:
            try:
                output = ClasificacionOutput.model_validate_json(texto)
            except ValidationError as exc:
                errores = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
                raise rechazar(f"la respuesta no respeta el esquema ({errores})") from exc

        if not self.catalogo.contiene(output.clase_sugerida):
            raise rechazar(f"clase_sugerida {output.clase_sugerida} no existe en el catálogo")

        return output.model_copy(update={"alternativas": self._depurar_alternativas(output)})

    def _depurar_alternativas(self, output: ClasificacionOutput) -> list[AlternativaClase]:
        vistas = {output.clase_sugerida}
        depuradas = []
        for alt in output.alternativas:
            if alt.clase in vistas:
                continue
            if not self.catalogo.contiene(alt.clase):
                logger.info("Se descarta alternativa fuera de catálogo: %s", alt.clase)
                continue
            vistas.add(alt.clase)
            depuradas.append(alt)
        return depuradas[:MAX_ALTERNATIVAS]

    def _fallback(
        self, denominacion_fallback: str, precedentes: list[Precedente], error: str, intentos: int
    ) -> ClasificacionOutput:
        """Sin respuesta válida del modelo: voto ponderado de precedentes, siempre con códigos del catálogo.

        La denominación sugerida cae a la del activo de entrada, porque no hay respuesta del modelo.
        """
        votos = votos_por_clase(precedentes, self.catalogo)
        if not votos:
            raise ClasificacionFallidaError(
                f"El modelo no devolvió una clase válida tras {intentos} intentos ({error}) "
                "y no hay precedentes con clases del catálogo. Requiere clasificación manual."
            )
        ganador, *resto = votos
        descripcion = self.catalogo.get(ganador.clase).descripcion
        return ClasificacionOutput(
            clase_sugerida=ganador.clase,
            denominacion_sugerida=denominacion_fallback[:50],
            confianza="baja",
            justificacion=(
                f"Clasificación automática NO validada: el modelo falló {intentos} veces (último error: {error}). "
                f"Se asigna la clase {ganador.clase} ({descripcion}) por voto ponderado de "
                f"{ganador.cantidad} precedente(s) similares (similitud máxima {ganador.mejor_similitud:.3f}). "
                "Requiere revisión manual."
            ),
            alternativas=[
                AlternativaClase(
                    clase=v.clase,
                    motivo=f"{v.cantidad} precedente(s) similares (similitud máxima {v.mejor_similitud:.3f})",
                )
                for v in resto[:MAX_ALTERNATIVAS]
            ],
        )
