"""Construcción de prompts: sistema (reglas + catálogo completo) y usuario (activo + precedentes)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.catalogo import Catalogo
from app.models import ClasificacionInput, Precedente

SYSTEM_TEMPLATE = """\
Sos un analista contable experto en activos fijos del grupo Daimler. Tu tarea es asignar a cada \
activo la clase correcta del "Daimler Group Asset Class Catalogue".

REGLAS OBLIGATORIAS
1. `clase_sugerida` DEBE ser exactamente uno de los códigos de 8 dígitos listados en CATÁLOGO. \
Nunca inventes, modifiques ni combines códigos.
2. Si ninguna clase calza bien, elegí la más cercana del CATÁLOGO y usá confianza "baja". \
Nunca devuelvas un código que no esté en el CATÁLOGO.
3. Los PRECEDENTES son activos históricos ya clasificados correctamente: son evidencia fuerte, \
pero un precedente marcado [FUERA DE CATÁLOGO] no puede elegirse como clase.
4. `alternativas`: hasta 3 clases del CATÁLOGO distintas de la sugerida, ordenadas de más a menos \
probable, con su motivo. Lista vacía si no hay alternativas razonables.
5. `confianza`:
   - "alta": precedentes muy similares coinciden mayoritariamente en la clase y la descripción del catálogo lo confirma.
   - "media": evidencia parcial (precedentes divididos o poco similares) pero la clase es consistente con el catálogo.
   - "baja": sin precedentes relevantes, evidencia contradictoria, o ninguna clase calza bien.
6. `justificacion`: en español, 2 a 4 oraciones. Citá los precedentes más relevantes (denominación y clase) \
y el criterio del catálogo aplicado.
7. Respondé únicamente con el JSON del esquema solicitado.

CATÁLOGO ({n} clases) — formato: código | rubro | descripción | explicación y ejemplos
{catalogo}
"""


@dataclass(frozen=True)
class VotoClase:
    clase: int
    cantidad: int
    puntaje: float  # suma de similitudes
    mejor_similitud: float


def votos_por_clase(precedentes: list[Precedente], catalogo: Catalogo | None = None) -> list[VotoClase]:
    """Agrupa precedentes por clase, ponderando por similitud. Si se pasa catálogo, excluye clases fuera de él."""
    acumulado: dict[int, list[float]] = {}
    for p in precedentes:
        if catalogo is not None and not catalogo.contiene(p.clase):
            continue
        acumulado.setdefault(p.clase, []).append(max(p.similitud, 0.0))
    votos = [VotoClase(c, len(s), sum(s), max(s)) for c, s in acumulado.items()]
    return sorted(votos, key=lambda v: (v.puntaje, v.mejor_similitud), reverse=True)


def formatear_catalogo(catalogo: Catalogo) -> str:
    lineas = []
    for item in catalogo.items:
        partes = [str(item.clase), item.rubro or "-", item.descripcion]
        if item.explicacion:
            partes.append(item.explicacion)
        lineas.append(" | ".join(partes))
    return "\n".join(lineas)


def build_system_prompt(catalogo: Catalogo) -> str:
    return SYSTEM_TEMPLATE.format(n=len(catalogo), catalogo=formatear_catalogo(catalogo))


def build_user_prompt(entrada: ClasificacionInput, precedentes: list[Precedente], catalogo: Catalogo) -> str:
    lineas = ["ACTIVO A CLASIFICAR", f"Denominación: {entrada.denominacion}"]
    contexto = entrada.contexto_adicional()
    if contexto:
        lineas.append("Datos adicionales:")
        lineas.extend(f"- {k}: {json.dumps(v, ensure_ascii=False, default=str)}" for k, v in contexto.items())

    lineas.append("")
    if precedentes:
        lineas.append(
            f"PRECEDENTES HISTÓRICOS SIMILARES ({len(precedentes)}, ordenados por similitud; "
            "similitud = 1 - distancia coseno)"
        )
        for i, p in enumerate(precedentes, 1):
            item = catalogo.get(p.clase)
            etiqueta = item.descripcion if item else "[FUERA DE CATÁLOGO]"
            lineas.append(f'{i}. [sim {p.similitud:.3f}] clase {p.clase} ({etiqueta}) — "{p.denominacion}"')

        votos = votos_por_clase(precedentes, catalogo)
        if votos:
            lineas.append("")
            lineas.append("RESUMEN DE PRECEDENTES POR CLASE (solo clases del catálogo)")
            lineas.extend(
                f"- {v.clase}: {v.cantidad} precedente(s), similitud máxima {v.mejor_similitud:.3f}"
                for v in votos
            )
    else:
        lineas.append("PRECEDENTES HISTÓRICOS SIMILARES: no se encontraron.")

    lineas.append("")
    lineas.append("Clasificá el activo según las REGLAS OBLIGATORIAS.")
    return "\n".join(lineas)


def build_correccion(error: str) -> str:
    return (
        f"Tu respuesta anterior fue rechazada: {error}\n"
        "Corregila respetando el esquema JSON. `clase_sugerida` y cada `alternativas[].clase` "
        "deben ser exactamente códigos del CATÁLOGO."
    )
