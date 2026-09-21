"""Demo interactiva sin API: pide denominaciones y muestra el resultado completo.

    .venv\\Scripts\\python scripts\\demo.py

La primera consulta tarda un poco más porque crea los clientes y carga el catálogo;
después se reutilizan (get_clasificador está cacheado).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.classifier_core import clasificar_detallado, formatear_linea  # noqa: E402


def mostrar(denominacion: str) -> None:
    r = clasificar_detallado(denominacion)
    print()
    print(f"  LÍNEA PARA SAP : {formatear_linea(r)}")
    print(f"  Confianza      : {r.confianza.upper()}")
    if r.fallback:
        print("  ATENCIÓN: clase por voto de precedentes (el modelo no validó). Revisar a mano.")
    print(f"\n  Justificación:\n    {r.justificacion}")
    if r.alternativas:
        print("\n  Alternativas:")
        for a in r.alternativas:
            print(f"    - {a.clase}: {a.motivo}")
    print("\n  Precedentes más similares:")
    for p in r.precedentes[:5]:
        print(f"    [{p.similitud:.0%}] {p.clase}  {p.denominacion}")
    print()


def main() -> int:
    if len(sys.argv) > 1:
        mostrar(" ".join(sys.argv[1:]))
        return 0
    print("Clasificador de Activos Fijos - demo (Enter vacío para salir)")
    while True:
        try:
            denominacion = input("\nDenominación del activo: ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if not denominacion:
            return 0
        try:
            mostrar(denominacion)
        except Exception as exc:  # la demo no se corta por un error puntual
            print(f"  ERROR: {exc.__class__.__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
