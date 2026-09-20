import json

import pytest
from openpyxl import Workbook

from preprocess.load_catalogo import guardar_json, parsear_catalogo, parsear_codigo, parsear_filas

# Estructura equivalente a la hoja "Test Version": título, cabecera, secciones, grupos,
# subrubros, notas y clases mezcladas; columnas en alemán a la derecha.
FILAS = [
    ("Daimler Group Asset Class Catalogue\nVersion 2024", None, None, None, None),
    (None, "Daimler Group \nEstructura de las Clases", None, "Daimler Konzern", None),
    ("D R A F T", "Descripción", "Explicación y Ejemplos", "Bezeichnung", "Beschreibung"),
    (None, "PROPIEDADES, PLANTAS Y EQUIPOS", None, "SACHANLAGEN", None),
    ("0051000 000", "Terrenos, Derechos equivalentes", None, "Grundstücke", None),
    (None, "Terrenos (propiedades reales)", None, "Grundstücke", None),
    (51000010, "Terrenos /  propiedades reales", "Con o sin\nedificaciones", "Grundstücke", "Mit und ohne Bauten"),
    ("51000020", "Derechos equivalentes de tierra", None, "Erbbaurechte", None),
    (None, "Clave: \nIncluir edificaciones relacionadas", None, "Hinweis", None),
    (None, "Edificios de Fábrica", None, "Gebäude", None),
    (None, "Edificios de Fábrica y Oficina (FOB)", None, "FuG", None),
    (51000120.0, "FOB estructuras sólidas", None, "FuG Massivbauten", None),
    (51000120, "Duplicado", None, None, None),
    (None, None, None, None, None),
    (5100012, "Código de 7 dígitos", None, None, None),
    ("0052000 000", "Equipo Técnico y Maquinaria", None, "Technische Anlagen", None),
    (52000010, "Sistemas de tanques", "Para líquidos", "Tankanlagen", None),
]


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (51000010, 51000010),
        ("51000010", 51000010),
        (" 51000010 ", 51000010),
        (51000010.0, 51000010),
        ("0051000 000", None),
        ("D R A F T", None),
        (5100012, None),
        (None, None),
        (True, None),
        (51000010.5, None),
    ],
)
def test_parsear_codigo(valor, esperado):
    assert parsear_codigo(valor) == esperado


def test_parseo_filtra_encabezados_mezclados():
    resultado = parsear_filas(FILAS)

    assert [i.clase for i in resultado.items] == [51000010, 51000020, 51000120, 52000010]
    assert resultado.duplicados == [51000120]
    assert len(resultado.notas) == 1

    terrenos = resultado.items[0]
    assert terrenos.descripcion == "Terrenos / propiedades reales"  # espacios normalizados
    assert terrenos.explicacion == "Con o sin edificaciones"
    assert terrenos.rubro == "Terrenos, Derechos equivalentes > Terrenos (propiedades reales)"
    assert resultado.items[1].explicacion == ""

    # subrubros consecutivos se encadenan; la nota "Clave:" no rompe la jerarquía
    assert resultado.items[2].rubro == (
        "Terrenos, Derechos equivalentes > Edificios de Fábrica > Edificios de Fábrica y Oficina (FOB)"
    )
    assert resultado.items[3].rubro == "Equipo Técnico y Maquinaria"

    niveles = {e.texto: e.nivel for e in resultado.encabezados}
    assert niveles["PROPIEDADES, PLANTAS Y EQUIPOS"] == 0
    assert niveles["Terrenos, Derechos equivalentes"] == 1
    assert niveles["Terrenos (propiedades reales)"] == 2
    # título y cabecera previos a "Descripción" no se interpretan como encabezados
    assert "Descripción" not in niveles


def test_parseo_desde_excel_y_json(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Version"
    for fila in FILAS:
        ws.append(list(fila))
    xlsx = tmp_path / "Politica_AF.xlsx"
    wb.save(xlsx)

    resultado = parsear_catalogo(xlsx)
    salida = tmp_path / "catalogo.json"
    guardar_json(resultado.items, salida)

    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert [d["clase"] for d in datos] == [51000010, 51000020, 51000120, 52000010]
    assert set(datos[0]) == {"clase", "descripcion", "explicacion", "rubro"}


def test_hoja_inexistente(tmp_path):
    wb = Workbook()
    wb.active.title = "Otra"
    xlsx = tmp_path / "p.xlsx"
    wb.save(xlsx)
    with pytest.raises(ValueError, match="Test Version"):
        parsear_catalogo(xlsx)
