"""Catálogo oficial de clases en memoria (generado por preprocess/load_catalogo.py)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from app.models import CatalogoItem


class Catalogo:
    def __init__(self, items: Iterable[CatalogoItem]):
        self.items: list[CatalogoItem] = list(items)
        self._por_clase = {item.clase: item for item in self.items}
        if not self._por_clase:
            raise ValueError("El catálogo está vacío")

    @property
    def codigos(self) -> frozenset[int]:
        return frozenset(self._por_clase)

    def contiene(self, clase: int) -> bool:
        return clase in self._por_clase

    def get(self, clase: int) -> CatalogoItem | None:
        return self._por_clase.get(clase)

    def __len__(self) -> int:
        return len(self._por_clase)


def cargar_catalogo(path: Path) -> Catalogo:
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path}. Generalo con: python -m preprocess.load_catalogo"
        )
    datos = json.loads(path.read_text(encoding="utf-8"))
    return Catalogo(CatalogoItem.model_validate(d) for d in datos)
