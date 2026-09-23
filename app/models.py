"""Modelos Pydantic de entrada/salida y del catálogo."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Confianza = Literal["alta", "media", "baja"]


class ClasificacionInput(BaseModel):
    """Activo a clasificar. Acepta campos extra (se pasan al modelo como contexto)."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    denominacion: str = Field(..., min_length=1, max_length=500, description="Denominación del activo fijo")
    monto: float | None = Field(default=None, description="Monto de alta del activo")
    moneda: str | None = None
    centro_costo: str | None = None
    proveedor: str | None = None
    sociedad: str | None = None
    observaciones: str | None = None

    def contexto_adicional(self) -> dict[str, Any]:
        """Todos los campos informados salvo la denominación, incluidos los extra."""
        return {
            k: v
            for k, v in self.model_dump(exclude={"denominacion"}, exclude_none=True).items()
            if v != ""
        }


class AlternativaClase(BaseModel):
    clase: int = Field(description="Código de 8 dígitos del catálogo")
    motivo: str = Field(description="Por qué esta clase es una alternativa plausible")


class ClasificacionLLMOutput(BaseModel):
    """Único esquema que Gemini puede devolver."""

    clase_sugerida: int = Field(description="Código de 8 dígitos, exactamente uno de los del catálogo")
    denominacion_sugerida: str = Field(
        max_length=50,
        description=(
            "Denominación del activo para el campo TXT50 de SAP: máximo 50 caracteres, en español, "
            "sin saltos de línea. Debe describir el activo en conjunto (si son varias posiciones, "
            "el bien resultante), no repetir el nombre de la clase."
        ),
    )


class ClasificacionOutput(ClasificacionLLMOutput):
    """Respuesta interna enriquecida con datos calculados por la aplicación."""

    confianza: Confianza = Field(description="alta | media | baja")
    justificacion: str = Field(description="Justificación en español citando precedentes y criterio del catálogo")
    alternativas: list[AlternativaClase] = Field(description="Hasta 3 clases alternativas del catálogo")


class CatalogoItem(BaseModel):
    clase: int
    descripcion: str
    explicacion: str = ""
    rubro: str = ""


class Precedente(BaseModel):
    clase: int
    denominacion: str
    distancia: float = Field(description="Distancia coseno (0 = idéntico)")

    @property
    def similitud(self) -> float:
        return 1.0 - self.distancia


class ClasificacionRespuesta(ClasificacionOutput):
    """Respuesta HTTP: la salida validada más la evidencia usada."""

    descripcion_clase: str
    precedentes: list[Precedente]
    modelo: str
    fallback: bool = Field(description="True si la clase no vino validada del modelo y se usó el voto de precedentes")
    intentos: int
