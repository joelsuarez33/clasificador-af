# -*- coding: utf-8 -*-
"""
Diagnostico: nombres de columna del grid de posiciones de ME53N
===============================================================

Standalone. No importa nada del proyecto: conecta a la sesion SAP GUI activa,
abre la SolPed que se le pase por parametro e imprime el ColumnOrder del
GuiGridView de posiciones. Ese listado es el que hace falta para leer las
posiciones con GetCellValue.

Uso:
    python sap\\_debug_columnas.py 10012345
    python sap\\_debug_columnas.py 10012345 --valores 3   # ademas, las primeras 3 filas

Requisitos: SAP GUI abierto y logueado, scripting habilitado, pywin32.
"""

import sys
import time

try:
    import win32com.client
except ImportError:
    print("ERROR: falta pywin32.  Instalar con:  pip install pywin32")
    sys.exit(1)


# Grid de posiciones segun el mapa de ME53N. Se prueban variantes por si la
# pantalla quedo con otro numero de subscreen.
GRID_IDS = [
    "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB3:SAPLMEVIEWS:1100/subSUB2:SAPLMEVIEWS:1200"
    "/subSUB1:SAPLMEGUI:3212/cntlGRIDCONTROL/shellcont/shell",
    "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB2:SAPLMEVIEWS:1100/subSUB2:SAPLMEVIEWS:1200"
    "/subSUB1:SAPLMEGUI:3212/cntlGRIDCONTROL/shellcont/shell",
    "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB3:SAPLMEVIEWS:1100/subSUB2:SAPLMEVIEWS:1200"
    "/subSUB1:SAPLMEGUI:3211/cntlGRIDCONTROL/shellcont/shell",
]


def obtener_sesion():
    """Devuelve la primera sesion SAP GUI disponible."""
    try:
        sap_gui = win32com.client.GetObject("SAPGUI")
    except Exception:
        raise RuntimeError(
            "No se encontro SAP GUI en ejecucion.\n"
            "Abri SAP Logon e inicia sesion antes de correr el script."
        )

    app = sap_gui.GetScriptingEngine
    if app.Connections.Count == 0:
        raise RuntimeError("SAP GUI esta abierto pero no hay ninguna conexion activa.")

    conexion = app.Children(0)
    if conexion.Children.Count == 0:
        raise RuntimeError("La conexion SAP no tiene sesiones abiertas.")

    return conexion.Children(0)


def cerrar_popups(session):
    """Cierra ventanas modales residuales."""
    intentos = 0
    while session.Children.Count > 1 and intentos < 5:
        try:
            session.findById("wnd[1]").close()
        except Exception:
            break
        intentos += 1


def abrir_solped(session, banfn):
    """Navega a ME53N y abre la solicitud indicada."""
    session.findById("wnd[0]").maximize()
    cerrar_popups(session)

    session.findById("wnd[0]/tbar[0]/okcd").text = "/nME53N"
    session.findById("wnd[0]").sendVKey(0)

    session.findById("wnd[0]/tbar[1]/btn[17]").press()
    session.findById("wnd[1]/usr/subSUB0:SAPLMEGUI:0003/ctxtMEPO_SELECT-BANFN").text = banfn
    session.findById("wnd[1]/tbar[0]/btn[0]").press()

    try:
        barra = session.findById("wnd[0]/sbar")
        tipo, mensaje = str(barra.MessageType).strip().upper(), str(barra.text).strip()
    except Exception:
        tipo, mensaje = "", ""
    if tipo in ("E", "A"):
        raise RuntimeError("SAP rechazo la solicitud {}: {}".format(banfn, mensaje))

    cerrar_popups(session)
    time.sleep(0.4)


def buscar_grid(session):
    """Devuelve (grid, id) del GuiGridView de posiciones."""
    for ruta in GRID_IDS:
        try:
            return session.findById(ruta), ruta
        except Exception:
            continue
    raise RuntimeError(
        "No se encontro el grid de posiciones.\n"
        "Verifica que la SolPed este abierta y el resumen de posiciones visible (no colapsado).\n"
        "IDs probados:\n  " + "\n  ".join(GRID_IDS)
    )


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2

    banfn = argv[0].strip()
    filas_valores = 0
    if "--valores" in argv:
        try:
            filas_valores = int(argv[argv.index("--valores") + 1])
        except (IndexError, ValueError):
            filas_valores = 3

    try:
        session = obtener_sesion()
        abrir_solped(session, banfn)
        grid, ruta = buscar_grid(session)
    except RuntimeError as exc:
        print("ERROR: {}".format(exc))
        return 1

    columnas = [str(c) for c in grid.ColumnOrder]

    print("\nGrid encontrado en:\n  {}".format(ruta))
    print("\nRowCount   : {}".format(grid.RowCount))
    print("VisibleRows: {}".format(getattr(grid, "VisibleRowCount", "?")))
    print("\nColumnOrder ({} columnas):".format(len(columnas)))
    for i, columna in enumerate(columnas):
        try:
            titulo = grid.GetColumnTitles(columna)[0]
        except Exception:
            titulo = ""
        print("  {:>3}  {:<20} {}".format(i, columna, titulo))

    for fila in range(min(filas_valores, grid.RowCount)):
        print("\n--- Fila {} ---".format(fila))
        for columna in columnas:
            try:
                valor = str(grid.GetCellValue(fila, columna)).strip()
            except Exception:
                valor = "<no legible>"
            if valor:
                print("  {:<20} {}".format(columna, valor))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
