from openpyxl import Workbook

from preprocess.build_index import calcular_row_id, leer_historico, preparar_filas


def test_preparar_filas_limpia_y_deduplica():
    filas, stats = preparar_filas(
        [
            (53000010, "  Notebook   DELL\tLatitude "),
            (53000010, "notebook dell latitude"),  # duplicado tras limpieza
            (53000020, "notebook dell latitude"),  # mismo texto, otra clase: se conserva
            (None, "sin clase"),
            (53000010, None),
            ("abc", "clase no numérica"),
        ]
    )
    assert stats == {"leidas": 6, "descartadas": 3, "duplicadas": 1}
    assert len(filas) == 2
    assert filas[0].denominacion == "Notebook DELL Latitude"  # original para mostrar
    assert filas[0].denominacion_limpia == "notebook dell latitude"  # para embeber
    assert filas[0].row_id == calcular_row_id(53000010, "notebook dell latitude")
    assert filas[0].row_id != filas[1].row_id


def test_leer_historico_por_nombre_de_columna(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Clase", "Denominación del activo fijo"])
    ws.append([51000010, "Circ.VI, Parcela 819u"])
    ws.append([52000010, "Tanque de aceite"])
    xlsx = tmp_path / "AF_definitivos_creados.xlsx"
    wb.save(xlsx)

    filas, stats = leer_historico(xlsx)
    assert [(f.clase, f.denominacion) for f in filas] == [
        (51000010, "Circ.VI, Parcela 819u"),
        (52000010, "Tanque de aceite"),
    ]
    assert stats["leidas"] == 2
