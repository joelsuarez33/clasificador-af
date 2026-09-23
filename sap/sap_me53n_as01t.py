# -*- coding: utf-8 -*-
"""
ME53N -> captura -> AS01
========================

Flujo completo:
  1. Pop-up pide el nro de solicitud de pedido (BANFN).
  2. Abre ME53N, navega a la SolPed y selecciona la pestana Imputacion.
  3. Extrae los datos de imputacion por ID de campo (sin OCR).
  4. Muestra un formulario de revision con los datos que se van a cargar.
     El controller confirma o corrige antes de tocar AS01.
  5. Abre AS01, completa clase de activo, sociedad, denominacion,
     centros de coste y campos de asignacion.
  6. Graba solo si MODO_SIMULACION = False y el usuario confirma.
     Devuelve el nro de activo que informa la statusbar.

Requisitos:
    pip install pywin32 pillow
    SAP GUI abierto y logueado, scripting habilitado (cliente y servidor).

Sin credenciales: reutiliza la sesion activa.
"""

import os
import re
import sys
import time
import ctypes
from ctypes import wintypes
from datetime import datetime
from io import BytesIO

import tkinter as tk
from tkinter import simpledialog, messagebox

try:
    import win32com.client
    import win32gui
    import win32ui
    import win32con
    import win32clipboard
except ImportError:
    print("ERROR: falta pywin32.  Instalar con:  pip install pywin32")
    sys.exit(1)

# --- Clasificador LLM (app/classifier_core.py en la raiz del repo) ---------
RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_REPO not in sys.path:
    sys.path.insert(0, RAIZ_REPO)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(RAIZ_REPO, ".env"))
except ImportError:
    pass

try:
    from app.classifier_core import clasificar_af
    ERROR_IMPORT_LLM = None
except Exception as _exc:          # sin .env, sin dependencias, archivo inexistente
    import traceback
    clasificar_af = None
    ERROR_IMPORT_LLM = "{}: {}\n\n{}".format(
        type(_exc).__name__, _exc, traceback.format_exc(limit=3)
    )

try:
    from PIL import Image
except ImportError:
    print("ERROR: falta Pillow.  Instalar con:  pip install pillow")
    sys.exit(1)


# ===========================================================================
# CONFIGURACION
# ===========================================================================

# True  = completa AS01 y se detiene ANTES de grabar (para revisar en pantalla)
# False = graba y devuelve el numero de activo
MODO_SIMULACION = True

GUARDAR_PNG = True
CARPETA_PNG = os.path.join(os.path.expanduser("~"), "Pictures", "SAP_Capturas")
ESPERA_RENDER = 0.6

# Conexion SAP
SAP_LOGON_LNK = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\SAP Front End\SAP Logon 64.lnk"
SAP_SISTEMA = "TA-F11 ERP Argentina [PRD]"   # descripcion exacta en SAP Logon (PRD: "TA-F11 ERP Argentina [PRD]")
ESPERA_ARRANQUE_LOGON = 4      # segundos tras lanzar SAP Logon
TIMEOUT_SESION = 30            # segundos maximos para que la conexion abra sesion
TIMEOUT_LOGIN_MANUAL = 120     # segundos para loguearse a mano si no hay SSO
PW_RENDERFULLCONTENT = 0x00000002

# Valores por defecto de AS01. El formulario de revision permite cambiarlos.
DEFAULTS_AS01 = {
    "ANLKL":  "54000010",   # Clase de activo - FIJA. ANLA-ANLKL es CHAR 8
    "BUKRS":  "MBA",        # Sociedad
    "TXT50":  "",           # Denominacion (se propone desde la SolPed)
    "TXA50":  "",           # Texto adicional <- respuesta de Gemini
    "KOSTL":  "",           # Centro de coste
    "KOSTLV": "",           # Centro de coste responsable
    "ORD41":  "NAC",
    "GDLGRP": "54000010",   # Grupo de activos fijos
    "ORD43":  "5400",
    "ORD44":  "",           # Categoria 4 <- derivada del CeCo (tabla Detalle Cecos)
}


# ===========================================================================
# IDs DE PANTALLA
# ===========================================================================

P = "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB3:SAPLMEVIEWS:1100/subSUB2:SAPLMEVIEWS:1200/subSUB1:SAPLMEGUI:1301/subSUB2:SAPLMEGUI:3303/tabsREQ_ITEM_DETAIL"
IMPUT = P + "/tabpTABREQDT6/ssubTABSTRIPCONTROL1SUB:SAPLMEVIEWS:1101"
KACB = IMPUT + "/subSUB2:SAPLMEACCTVI:0100/subSUB1:SAPLMEACCTVI:1100/subKONTBLOCK:SAPLKACB:1101"

ME53N_IDS = {
    "banfn":    "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB0:SAPLMEGUI:0030/subSUB1:SAPLMEGUI:3327/txtMEREQ_TOPLINE-BANFN_EXT",
    "clase_doc": "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB0:SAPLMEGUI:0030/subSUB1:SAPLMEGUI:3327/cmbMEREQ_TOPLINE-BSART",
    "posicion": "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB3:SAPLMEVIEWS:1100/subSUB2:SAPLMEVIEWS:1200/subSUB1:SAPLMEGUI:1301/subSUB1:SAPLMEGUI:6000/cmbDYN_6000-LIST",
    "tab_imput": P + "/tabpTABREQDT6",
    "tp_imput": IMPUT + "/subSUB1:SAPLMEACCTVI:1200/cmbMEACCT1200-KNTTP",
    "sociedad": IMPUT + "/subSUB1:SAPLMEACCTVI:1200/cmbMEACCT1200-BUKRS",
    "cta_mayor": IMPUT + "/subSUB2:SAPLMEACCTVI:0100/subSUB1:SAPLMEACCTVI:1100/ctxtMEACCT1100-SAKTO",
    "activo_fijo": KACB + "/ctxtCOBL-ANLN1",
    "subnumero": KACB + "/ctxtCOBL-ANLN2",
    "sociedad_co": KACB + "/ctxtCOBL-KOKRS",
    "centro_coste": KACB + "/ctxtCOBL-KOSTL",
    "orden": KACB + "/ctxtCOBL-AUFNR",
    "cebe": KACB + "/ctxtCOBL-PRCTR",
}

GRID_POSICIONES_IDS = [
    (
        "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB3:SAPLMEVIEWS:1100/"
        "subSUB2:SAPLMEVIEWS:1200/subSUB1:SAPLMEGUI:3212/"
        "cntlGRIDCONTROL/shellcont/shell"
    ),
    (
        "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB2:SAPLMEVIEWS:1100/"
        "subSUB2:SAPLMEVIEWS:1200/subSUB1:SAPLMEGUI:3212/"
        "cntlGRIDCONTROL/shellcont/shell"
    ),
    (
        "wnd[0]/usr/subSUB0:SAPLMEGUI:0019/subSUB3:SAPLMEVIEWS:1100/"
        "subSUB2:SAPLMEVIEWS:1200/subSUB1:SAPLMEGUI:3211/"
        "cntlGRIDCONTROL/shellcont/shell"
    ),
]

TAB = "wnd[0]/usr/subTABSTRIP:SAPLATAB:0100/tabsTABSTRIP100"

AS01_IDS = {
    "anlkl":  "wnd[0]/usr/ctxtANLA-ANLKL",
    "bukrs":  "wnd[0]/usr/ctxtANLA-BUKRS",
    "tab01":  TAB + "/tabpTAB01",
    "txt50":  TAB + "/tabpTAB01/ssubSUBSC:SAPLATAB:0200/subAREA1:SAPLAIST:1140/txtANLA-TXT50",
    "txa50":  TAB + "/tabpTAB01/ssubSUBSC:SAPLATAB:0200/subAREA1:SAPLAIST:1140/txtANLA-TXA50",
    "tab02":  TAB + "/tabpTAB02",
    "kostl":  TAB + "/tabpTAB02/ssubSUBSC:SAPLATAB:0201/subAREA1:SAPLAIST:1145/ctxtANLZ-KOSTL",
    "kostlv": TAB + "/tabpTAB02/ssubSUBSC:SAPLATAB:0201/subAREA1:SAPLAIST:1145/ctxtANLZ-KOSTLV",
    "tab03":  TAB + "/tabpTAB03",
    "ord41":  TAB + "/tabpTAB03/ssubSUBSC:SAPLATAB:0200/subAREA1:SAPLAIST:1160/ctxtANLA-ORD41",
    "gdlgrp": TAB + "/tabpTAB03/ssubSUBSC:SAPLATAB:0200/subAREA1:SAPLAIST:1160/ctxtANLA-GDLGRP",
    "ord43":  TAB + "/tabpTAB03/ssubSUBSC:SAPLATAB:0200/subAREA1:SAPLAIST:1160/ctxtANLA-ORD43",
    "ord44":  TAB + "/tabpTAB03/ssubSUBSC:SAPLATAB:0200/subAREA1:SAPLAIST:1160/ctxtANLA-ORD44",
    "grabar": "wnd[0]/tbar[0]/btn[11]",
}


# ===========================================================================
# UTILIDADES UI
# ===========================================================================

def avisar(titulo, mensaje, error=False):
    """Message box simple, siempre al frente."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if error:
            messagebox.showerror(titulo, mensaje, parent=root)
        else:
            messagebox.showinfo(titulo, mensaje, parent=root)
    finally:
        root.destroy()


def confirmar(titulo, mensaje):
    """Pregunta si/no. Devuelve True si el usuario confirma."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return bool(messagebox.askyesno(titulo, mensaje, parent=root))
    finally:
        root.destroy()


def pedir_banfn():
    """Pop-up que pide el nro de solicitud de pedido. Devuelve str o None."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        valor = simpledialog.askstring(
            "ME53N - Solicitud de pedido",
            "Ingrese el numero de solicitud de pedido (BANFN):",
            parent=root,
        )
    finally:
        root.destroy()

    if valor is None:
        return None

    valor = valor.strip()
    if not valor:
        return None

    if not valor.isdigit():
        avisar("Dato invalido", "El numero de solicitud debe contener solo digitos.", error=True)
        return None

    return valor


def formulario_as01(propuesta):
    """
    Formulario de revision previo a la carga.
    Devuelve el dict corregido, o None si el usuario cancela.
    """
    etiquetas = [
        ("ANLKL",  "Clase de activo"),
        ("BUKRS",  "Sociedad"),
        ("TXT50",  "Denominacion"),
        ("TXA50",  "Texto adicional"),
        ("KOSTL",  "Centro de coste"),
        ("KOSTLV", "CeCo responsable"),
        ("ORD41",  "Asignacion 1"),
        ("GDLGRP", "Grupo de activos"),
        ("ORD43",  "Asignacion 3"),
        ("ORD44",  "Asignacion 4"),
    ]

    resultado = {"ok": False, "datos": {}}

    root = tk.Tk()
    root.title("AS01 - Revisar antes de cargar")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(
        root,
        text="Revisa los valores propuestos. Se cargan en AS01 al confirmar.",
        font=("Segoe UI", 9, "bold"),
    ).grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 8), sticky="w")

    entradas = {}
    for fila, (clave, etiqueta) in enumerate(etiquetas, start=1):
        tk.Label(root, text=etiqueta + ":").grid(
            row=fila, column=0, padx=(12, 6), pady=3, sticky="e"
        )
        ancho = 48 if clave in ("TXT50", "TXA50") else 22
        caja = tk.Entry(root, width=ancho)
        caja.insert(0, propuesta.get(clave, ""))
        caja.grid(row=fila, column=1, padx=(0, 12), pady=3, sticky="w")
        entradas[clave] = caja

    aviso = (
        "MODO SIMULACION: completa AS01 y NO graba."
        if MODO_SIMULACION
        else "ATENCION: va a GRABAR el activo en SAP."
    )
    tk.Label(root, text=aviso, fg="#b00020" if not MODO_SIMULACION else "#555").grid(
        row=len(etiquetas) + 1, column=0, columnspan=2, padx=12, pady=(8, 4)
    )

    def aceptar():
        datos = {k: e.get().strip() for k, e in entradas.items()}
        faltan = [k for k in ("ANLKL", "BUKRS", "TXT50") if not datos[k]]
        if faltan:
            messagebox.showerror(
                "Faltan datos",
                "Campos obligatorios vacios: {}".format(", ".join(faltan)),
                parent=root,
            )
            return
        resultado["datos"] = datos
        resultado["ok"] = True
        root.destroy()

    def cancelar():
        root.destroy()

    marco = tk.Frame(root)
    marco.grid(row=len(etiquetas) + 2, column=0, columnspan=2, pady=(4, 12))
    tk.Button(marco, text="Cargar en AS01", width=16, command=aceptar).pack(side="left", padx=6)
    tk.Button(marco, text="Cancelar", width=12, command=cancelar).pack(side="left", padx=6)

    root.bind("<Return>", lambda _e: aceptar())
    root.bind("<Escape>", lambda _e: cancelar())
    root.mainloop()

    return resultado["datos"] if resultado["ok"] else None


# ===========================================================================
# CONEXION SAP
# ===========================================================================

def _scripting_engine():
    """
    Devuelve el scripting engine de SAP GUI.
    Si SAP Logon no esta corriendo, lo lanza y reintenta.
    """
    lanzado = False
    for intento in range(10):
        try:
            sap_gui = win32com.client.GetObject("SAPGUI")
            app = sap_gui.GetScriptingEngine
            if app is not None:
                return app
        except Exception:
            pass

        if not lanzado:
            try:
                os.startfile(SAP_LOGON_LNK)
                lanzado = True
                time.sleep(ESPERA_ARRANQUE_LOGON)
                continue
            except Exception as exc:
                raise RuntimeError(
                    "No se pudo iniciar SAP Logon desde:\n{}\nDetalle: {}".format(SAP_LOGON_LNK, exc)
                )
        time.sleep(1)

    raise RuntimeError(
        "SAP Logon no expone el scripting engine.\n"
        "Verifica en SAP Logon > Opciones > Accesibilidad y scripting > Scripting "
        "que 'Habilitar scripting' este tildado, cerra SAP GUI por completo y reintenta."
    )


def _sesion_logueada(sesion):
    """True si la sesion ya paso la pantalla de login."""
    try:
        return bool(str(sesion.Info.User).strip())
    except Exception:
        return False


def obtener_sesion():
    """
    Devuelve una sesion logueada en SAP_SISTEMA.
    1. Reusa una conexion ya abierta a ese sistema si existe.
    2. Si no, la abre con OpenConnection (SSO si esta configurado).
    3. Si aparece la pantalla de login, espera a que el usuario se loguee a mano.
    No maneja credenciales.
    """
    app = _scripting_engine()

    # 1. Reusar conexion existente al sistema
    for i in range(app.Children.Count):
        con = app.Children(i)
        try:
            descripcion = str(con.Description).strip()
        except Exception:
            descripcion = ""
        if descripcion == SAP_SISTEMA and con.Children.Count > 0:
            sesion = con.Children(0)
            if _sesion_logueada(sesion):
                return sesion

    # 2. Abrir conexion nueva
    try:
        con = app.OpenConnection(SAP_SISTEMA, True)
    except Exception as exc:
        raise RuntimeError(
            "No se pudo abrir la conexion '{}'.\n"
            "Verifica que el nombre coincida EXACTO con la entrada de SAP Logon "
            "y que el scripting este habilitado.\nDetalle: {}".format(SAP_SISTEMA, exc)
        )

    sesion = None
    for _ in range(TIMEOUT_SESION):
        if con.Children.Count > 0:
            sesion = con.Children(0)
            break
        time.sleep(1)
    if sesion is None:
        raise RuntimeError(
            "La conexion '{}' se abrio pero no creo sesion en {}s.".format(SAP_SISTEMA, TIMEOUT_SESION)
        )

    # 3. Login: SSO entra solo; si no, esperar login manual
    if _sesion_logueada(sesion):
        return sesion

    avisar(
        "Login SAP",
        "Se abrio '{}'.\n\nLogueate en SAP y despues toca Aceptar.\n"
        "El script espera hasta {}s.".format(SAP_SISTEMA, TIMEOUT_LOGIN_MANUAL),
    )
    for _ in range(TIMEOUT_LOGIN_MANUAL):
        if _sesion_logueada(sesion):
            cerrar_popups(sesion)   # popups post-login (multiples logins, novedades)
            return sesion
        time.sleep(1)

    raise RuntimeError(
        "No se detecto login en '{}' dentro de {}s.".format(SAP_SISTEMA, TIMEOUT_LOGIN_MANUAL)
    )


def leer(session, ruta, defecto=""):
    """Lee .text de un control sin romper si no existe en la pantalla actual."""
    try:
        return str(session.findById(ruta).text).strip()
    except Exception:
        return defecto


def _asignar(campo, valor, etiqueta):
    """Valida largo contra MaxLength y escribe el valor."""
    try:
        largo_max = int(campo.MaxLength)
    except Exception:
        largo_max = 0
    if largo_max and len(valor) > largo_max:
        raise RuntimeError(
            "'{}' tiene {} caracteres y el campo {} admite {}.".format(
                valor, len(valor), etiqueta, largo_max
            )
        )
    try:
        campo.text = valor
    except Exception as exc:
        raise RuntimeError(
            "No se pudo escribir '{}' en el campo {} -> {}".format(valor, etiqueta, exc)
        )


def escribir(session, ruta, valor, etiqueta):
    """Escribe en un campo por ID completo. Para campos de pantalla fija (ANLKL, BUKRS)."""
    if valor is None or valor == "":
        return
    try:
        campo = session.findById(ruta)
    except Exception as exc:
        raise RuntimeError(
            "No se encontro el campo {} en la pantalla actual -> {}".format(etiqueta, exc)
        )
    _asignar(campo, valor, etiqueta)


def _buscar_por_nombre(session, nombre, tipo):
    """Busca un campo por nombre tecnico en el area visible. Devuelve el control o None."""
    try:
        usr = session.findById("wnd[0]/usr")
    except Exception:
        return None
    try:
        campo = usr.FindByNameEx(nombre, tipo)
        if campo is not None:
            return campo
    except Exception:
        pass
    try:
        return usr.FindByName(nombre, tipo)
    except Exception:
        return None


def localizar_campo_as01(session, nombre, tipo):
    """
    Busca un campo de AS01 por nombre tecnico (ej. ANLA-ORD41) recorriendo las
    pestanas del tabstrip. No depende del numero de pestana ni del subscreen,
    que cambian entre PRD y QAS o segun la clase de activo.
    """
    campo = _buscar_por_nombre(session, nombre, tipo)
    if campo is not None:
        return campo

    try:
        cantidad = session.findById(TAB).Children.Count
    except Exception as exc:
        raise RuntimeError("No se encontro el tabstrip de AS01 -> {}".format(exc))

    pestanas = []
    for i in range(cantidad):
        try:
            pestana = session.findById(TAB).Children(i)   # re-buscar: el objeto se invalida al cambiar de tab
            pestanas.append(str(pestana.Text).strip())
            pestana.select()
            time.sleep(0.2)
        except Exception:
            continue
        campo = _buscar_por_nombre(session, nombre, tipo)
        if campo is not None:
            return campo

    raise RuntimeError(
        "El campo {} no existe en ninguna pestana de AS01 para esta clase de activo.\n"
        "Pestanas revisadas: {}".format(nombre, ", ".join(pestanas) or "(ninguna)")
    )


def escribir_as01(session, nombre, tipo, valor, etiqueta):
    """Escribe en un campo de AS01 localizandolo por nombre tecnico."""
    if valor is None or valor == "":
        return
    campo = localizar_campo_as01(session, nombre, tipo)
    _asignar(campo, valor, etiqueta)


def cerrar_popups(session):
    """Cierra ventanas modales residuales."""
    intentos = 0
    while session.Children.Count > 1 and intentos < 5:
        try:
            session.findById("wnd[1]").close()
        except Exception:
            break
        intentos += 1


def statusbar(session):
    """Devuelve (tipo, texto) de la barra de estado."""
    try:
        barra = session.findById("wnd[0]/sbar")
        return str(barra.MessageType).strip().upper(), str(barra.text).strip()
    except Exception:
        return "", ""


# ===========================================================================
# BLOQUE 1 - ME53N
# ===========================================================================

def abrir_me53n(session, banfn):
    """Navega a la SolPed y abre la pestana Imputacion."""
    session.findById("wnd[0]").maximize()
    cerrar_popups(session)

    session.findById("wnd[0]/tbar[0]/okcd").text = "/nME53N"
    session.findById("wnd[0]").sendVKey(0)

    session.findById("wnd[0]/tbar[1]/btn[17]").press()
    session.findById(
        "wnd[1]/usr/subSUB0:SAPLMEGUI:0003/ctxtMEPO_SELECT-BANFN"
    ).text = banfn
    session.findById("wnd[1]/tbar[0]/btn[0]").press()

    tipo, mensaje = statusbar(session)
    if tipo in ("E", "A"):
        raise RuntimeError("SAP rechazo la solicitud {}: {}".format(banfn, mensaje))

    cerrar_popups(session)

    # Activar la pestana Imputacion antes de leer sus campos
    try:
        session.findById(ME53N_IDS["tab_imput"]).select()
        time.sleep(0.3)
    except Exception as exc:
        raise RuntimeError(
            "No se pudo abrir la pestana Imputacion. "
            "Verifica que la SolPed {} exista y tenga posiciones. Detalle: {}".format(banfn, exc)
        )

    return mensaje


def extraer_imputacion(session):
    """Lee los campos de la pestana Imputacion. Devuelve dict."""
    combo = lambda v: v.split("  ")[0].strip()

    datos = {
        "banfn":        leer(session, ME53N_IDS["banfn"]),
        "clase_doc":    combo(leer(session, ME53N_IDS["clase_doc"])),
        "posicion":     combo(leer(session, ME53N_IDS["posicion"])),
        "tp_imput":     combo(leer(session, ME53N_IDS["tp_imput"])),
        "sociedad":     combo(leer(session, ME53N_IDS["sociedad"])),
        "cta_mayor":    leer(session, ME53N_IDS["cta_mayor"]),
        "activo_fijo":  leer(session, ME53N_IDS["activo_fijo"]),
        "subnumero":    leer(session, ME53N_IDS["subnumero"]),
        "sociedad_co":  leer(session, ME53N_IDS["sociedad_co"]),
        "centro_coste": leer(session, ME53N_IDS["centro_coste"]),
        "orden":        leer(session, ME53N_IDS["orden"]),
        "cebe":         leer(session, ME53N_IDS["cebe"]),
    }

    # Texto breve de la posicion: "1 [ 1 ] CORRUGADORA TANSEN" -> denominacion
    texto_pos = datos["posicion"]
    if "]" in texto_pos:
        datos["texto_breve"] = texto_pos.split("]", 1)[1].strip()
    else:
        datos["texto_breve"] = texto_pos

    return datos


def _buscar_grid_posiciones(session):
    for ruta in GRID_POSICIONES_IDS:
        try:
            return session.findById(ruta)
        except Exception:
            continue
    raise RuntimeError(
        "No se encontro el grid de posiciones de ME53N. "
        "Verifica que el resumen de posiciones este visible."
    )


def _seleccionar_posicion(session, grid, fila):
    columnas = [str(c) for c in grid.ColumnOrder]
    if not columnas:
        raise RuntimeError("El grid de posiciones no tiene columnas.")
    try:
        grid.setCurrentCell(fila, columnas[0])
    except Exception:
        try:
            grid.currentCellRow = fila
        except Exception:
            pass
    try:
        grid.selectRow(fila)
    except Exception:
        pass
    time.sleep(0.4)


def _columna_texto_breve(grid):
    """Encuentra la columna de texto breve según título o nombre técnico."""
    for columna in (str(c) for c in grid.ColumnOrder):
        try:
            titulos = " ".join(str(t) for t in grid.GetColumnTitles(columna))
        except Exception:
            titulos = ""
        identificador = "{} {}".format(columna, titulos).upper()
        if "TEXTO BREVE" in identificador or "TXZ01" in identificador:
            return columna
    return None


def _texto_breve_de_fila(grid, fila, columna_texto):
    if columna_texto is None:
        return ""
    try:
        return str(grid.GetCellValue(fila, columna_texto)).strip()
    except Exception:
        return ""


def _columna_cantidad(grid):
    """Encuentra la columna Cantidad según título o nombre técnico."""
    for columna in (str(c) for c in grid.ColumnOrder):
        try:
            titulos = " ".join(str(t) for t in grid.GetColumnTitles(columna))
        except Exception:
            titulos = ""
        identificador = "{} {}".format(columna, titulos).upper()
        if "CANTIDAD" in identificador or identificador.split()[0] in {"MENGE", "ERFMG"}:
            return columna
    return None


def _cantidad_de_fila(grid, fila, columna_cantidad):
    if columna_cantidad is None:
        return ""
    try:
        return str(grid.GetCellValue(fila, columna_cantidad)).strip()
    except Exception:
        return ""


def _cantidad_distinta_de_uno(cantidad):
    """Evalúa cantidades SAP como 1, 1.0 o 1,000 sin agregar sufijo."""
    texto = str(cantidad).strip().replace(" ", "")
    if not texto:
        return False
    if re.fullmatch(r"1(?:[.,]0+)?", texto):
        return False
    return True


def _texto_con_cantidad(texto, cantidad):
    texto = str(texto or "").strip()
    cantidad = str(cantidad or "").strip()
    if not texto or not _cantidad_distinta_de_uno(cantidad):
        return texto
    return "{} - {}".format(texto, cantidad)


def extraer_todas_las_imputaciones(session):
    """Selecciona y lee todas las posiciones de la SolPed desde el grid."""
    grid = _buscar_grid_posiciones(session)
    cantidad = int(grid.RowCount)
    if cantidad <= 0:
        raise RuntimeError("La SolPed no tiene posiciones para procesar.")

    columna_texto = _columna_texto_breve(grid)
    columna_cantidad = _columna_cantidad(grid)
    if columna_cantidad is None:
        raise RuntimeError("No se encontro la columna Cantidad en el grid de posiciones de ME53N.")
    posiciones = []
    for fila in range(cantidad):
        texto_grid = _texto_breve_de_fila(grid, fila, columna_texto)
        if not texto_grid:
            # El grid puede incluir una fila de totales dentro de RowCount.
            continue
        cantidad_grid = _cantidad_de_fila(grid, fila, columna_cantidad)
        _seleccionar_posicion(session, grid, fila)
        datos = extraer_imputacion(session)
        datos["texto_breve"] = texto_grid
        datos["cantidad"] = cantidad_grid
        datos["fila_grid"] = fila
        posiciones.append(datos)

    if not posiciones:
        raise RuntimeError("No se encontraron posiciones con texto breve en el grid de ME53N.")

    _seleccionar_posicion(session, grid, posiciones[0]["fila_grid"])
    return posiciones


def elegir_modo_activos(posiciones, propuesta_primera):
    """Pregunta si se crea un activo por posición o uno combinado."""
    resultado = {"modo": None}
    root = tk.Tk()
    root.title("SolPed con varias posiciones")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(
        root,
        text="Se encontraron {} posiciones. Elegí cómo crear los activos:".format(len(posiciones)),
        font=("Segoe UI", 9, "bold"),
    ).pack(padx=14, pady=(12, 8), anchor="w")

    marco = tk.Frame(root)
    marco.pack(padx=14, fill="x")
    for i, datos in enumerate(posiciones, 1):
        texto = _texto_con_cantidad(datos.get("texto_breve", ""), datos.get("cantidad"))
        cantidad = datos.get("cantidad") or "(sin cantidad)"
        tk.Label(
            marco,
            text="{} - {} | Cantidad: {}".format(i, texto or "(sin descripción)", cantidad),
            anchor="w",
            justify="left",
        ).pack(fill="x")

    tk.Label(
        root,
        text=(
            "\nClasificación sugerida para un activo combinado (se toma la primera posición):\n"
            "{}"
        ).format(propuesta_primera.get("TXA50") or "(sin clasificación)"),
        justify="left",
        wraplength=560,
    ).pack(padx=14, pady=(10, 4), anchor="w")

    def elegir(modo):
        resultado["modo"] = modo
        root.destroy()

    botones = tk.Frame(root)
    botones.pack(pady=(8, 12))
    tk.Button(
        botones,
        text="Un activo por línea",
        width=22,
        command=lambda: elegir("por_linea"),
    ).pack(side="left", padx=5)
    tk.Button(
        botones,
        text="Combinar en un activo",
        width=22,
        command=lambda: elegir("unico"),
    ).pack(side="left", padx=5)
    tk.Button(botones, text="Cancelar", width=12, command=root.destroy).pack(side="left", padx=5)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.mainloop()
    return resultado["modo"]


# ===========================================================================
# LOGICA CECO -> CATEGORIA 4 (ANLA-ORD44)
# ===========================================================================

_MAPA_CAT4 = None


def _norm_ceco(valor):
    """'0000001605', 1605, ' b3025 ' -> '1605', 'B3025'. SAP rellena con ceros a la izquierda."""
    texto = str(valor).strip().upper()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto.lstrip("0") or texto


def cargar_mapa_cat4():
    """Lee data/Detalle*Cecos*.xlsx (col A = CeCo, col B = Cat. 4). Cachea en memoria."""
    global _MAPA_CAT4
    if _MAPA_CAT4 is not None:
        return _MAPA_CAT4

    import glob
    _MAPA_CAT4 = {}
    candidatos = sorted(glob.glob(os.path.join(RAIZ_REPO, "data", "Detalle*Ceco*.xlsx")))
    if not candidatos:
        print("AVISO CeCo: no se encontro data/Detalle*Cecos*.xlsx. ORD44 queda para carga manual.")
        return _MAPA_CAT4

    try:
        import openpyxl
        hoja = openpyxl.load_workbook(candidatos[0], read_only=True, data_only=True).active
        for fila in hoja.iter_rows(min_row=2, values_only=True):
            if not fila or fila[0] is None or fila[1] is None:
                continue
            _MAPA_CAT4[_norm_ceco(fila[0])] = str(fila[1]).strip().upper()
        print("Tabla CeCo -> Cat.4: {} registros ({})".format(
            len(_MAPA_CAT4), os.path.basename(candidatos[0])))
    except Exception as exc:
        print("AVISO CeCo: no se pudo leer {} -> {}".format(candidatos[0], exc))
    return _MAPA_CAT4


def categoria4_de_ceco(kostl):
    """Devuelve la Cat. 4 para un CeCo, o '' si no esta en la tabla."""
    if not kostl:
        return ""
    return cargar_mapa_cat4().get(_norm_ceco(kostl), "")


def kostlv_de_kostl(kostl):
    """Devuelve el mismo CeCo para KOSTLV, limitado a 5 caracteres."""
    return (_norm_ceco(kostl) if kostl else "")[:5]


def completar_derivados(datos, propuesta):
    """
    Post-formulario: recalcula KOSTLV y ORD44 desde el CeCo final.
    Solo pisa un campo si quedo vacio o si el usuario no lo toco
    (sigue igual al valor propuesto). Si lo edito a mano, se respeta.
    """
    kostl = datos.get("KOSTL", "")
    if not kostl:
        return datos

    for clave, derivar in (("KOSTLV", kostlv_de_kostl), ("ORD44", categoria4_de_ceco)):
        actual = datos.get(clave, "")
        if not actual or actual == propuesta.get(clave, ""):
            nuevo = derivar(kostl)
            if nuevo and nuevo != actual:
                print("{} recalculado desde CeCo {}: {}".format(clave, kostl, nuevo))
                datos[clave] = nuevo

    if not datos.get("ORD44"):
        print("AVISO CeCo: {} no esta en la tabla Detalle Cecos. ORD44 vacio.".format(kostl))
    return datos


def proponer_as01(datos):
    """Arma la propuesta de AS01 combinando defaults con lo leido de la SolPed."""
    propuesta = dict(DEFAULTS_AS01)

    if datos.get("texto_breve"):
        propuesta["TXT50"] = _texto_con_cantidad(
            datos["texto_breve"], datos.get("cantidad")
        )[:50]
    if datos.get("sociedad_co"):
        propuesta["BUKRS"] = datos["sociedad_co"]
    # CeCo: Centro de coste de la imputacion; si viene vacio, el CeBe
    ceco = datos.get("centro_coste") or datos.get("cebe") or ""
    if ceco:
        origen = "Centro de coste" if datos.get("centro_coste") else "CeBe"
        propuesta["KOSTL"] = _norm_ceco(ceco)[:5]
        propuesta["KOSTLV"] = kostlv_de_kostl(ceco)
        propuesta["ORD44"] = categoria4_de_ceco(ceco)
        print("CeCo {} (desde {}) -> responsable {} / Cat.4 {}".format(
            propuesta["KOSTL"], origen, propuesta["KOSTLV"], propuesta["ORD44"] or "(no esta en tabla)"))
    else:
        print("AVISO CeCo: la SolPed no trae Centro de coste ni CeBe. Cargalo en el formulario.")

    propuesta["TXA50"] = texto_llm(datos.get("texto_breve", ""))
    return propuesta


def combinar_posiciones(posiciones):
    """Arma una sola denominación conservando la imputación de la primera posición."""
    combinado = dict(posiciones[0])
    textos = [p.get("texto_breve", "").strip() for p in posiciones if p.get("texto_breve", "").strip()]
    combinado["texto_breve"] = " + ".join(textos)
    return combinado


def _campo(obj, nombre, defecto=""):
    """Lee un atributo de un modelo Pydantic o una clave de dict."""
    if isinstance(obj, dict):
        return obj.get(nombre, defecto)
    return getattr(obj, nombre, defecto)


def texto_llm(denominacion):
    """
    Llama a Gemini y devuelve el texto para ANLA-TXA50 (max 50 caracteres).
    Si falla, devuelve un texto que lo deja visible en el formulario de revision.
    """
    if not denominacion:
        return "LLM: sin denominacion"
    if clasificar_af is None:
        print("AVISO LLM: no se pudo importar el clasificador ->\n{}".format(ERROR_IMPORT_LLM))
        avisar(
            "Clasificador LLM no disponible",
            "No se pudo importar app.classifier_core. El flujo sigue sin LLM.\n\n"
            "Raiz del repo: {}\n\n{}".format(RAIZ_REPO, ERROR_IMPORT_LLM[:900]),
            error=True,
        )
        return "LLM: no disponible"

    try:
        resultado = clasificar_af(denominacion=denominacion)
    except Exception as exc:
        import traceback
        detalle = "{}: {}\n\n{}".format(type(exc).__name__, exc, traceback.format_exc(limit=4))
        print("AVISO LLM: fallo la clasificacion ->\n{}".format(detalle))
        avisar(
            "Clasificador LLM - error",
            "Gemini/BigQuery fallo al clasificar '{}'. El flujo sigue sin LLM.\n\n{}".format(
                denominacion, detalle[:900]),
            error=True,
        )
        return "LLM: error en clasificacion"

    clase = _campo(resultado, "clase_sugerida")
    descripcion = " ".join(_campo(resultado, "descripcion_clase").split())
    confianza = _campo(resultado, "confianza")
    justificacion = _campo(resultado, "justificacion")

    print("\n--- Respuesta Gemini ---")
    print("  Clase sugerida: {}".format(clase))
    print("  Confianza     : {}".format(confianza))
    if justificacion:
        print("  Justificacion : {}".format(justificacion))

    return "{} {}".format(clase, descripcion)[:50]


# ===========================================================================
# BLOQUE 2 - CAPTURA Y PORTAPAPELES
# ===========================================================================

def capturar_ventana(hwnd):
    """Captura la ventana por handle y devuelve una imagen PIL RGB."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.5)

    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(ESPERA_RENDER)

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ancho = rect.right - rect.left
    alto = rect.bottom - rect.top

    if ancho <= 0 or alto <= 0:
        raise RuntimeError("La ventana SAP tiene dimensiones invalidas.")

    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, ancho, alto)
        save_dc.SelectObject(bitmap)

        ok = ctypes.windll.user32.PrintWindow(
            hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
        )
        if ok != 1:
            save_dc.BitBlt((0, 0), (ancho, alto), mfc_dc, (0, 0), win32con.SRCCOPY)

        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1
        )
    finally:
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception:
                pass
        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception:
                pass
        if hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass


def copiar_al_portapapeles(imagen):
    """Deja la imagen en el portapapeles como CF_DIB (pegable con Ctrl+V)."""
    buffer_bmp = BytesIO()
    imagen.convert("RGB").save(buffer_bmp, format="BMP")
    datos_dib = buffer_bmp.getvalue()[14:]   # CF_DIB no lleva BITMAPFILEHEADER
    buffer_bmp.close()

    intentos = 5
    for intento in range(intentos):
        try:
            win32clipboard.OpenClipboard()
        except Exception:
            if intento == intentos - 1:
                raise RuntimeError(
                    "No se pudo abrir el portapapeles (otra aplicacion lo tiene tomado)."
                )
            time.sleep(0.3)
            continue

        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, datos_dib)
            return True
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    return False


def guardar_png(imagen, etiqueta):
    """Guarda una copia en disco. Devuelve la ruta o None."""
    try:
        os.makedirs(CARPETA_PNG, exist_ok=True)
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(CARPETA_PNG, "{}_{}.png".format(etiqueta, sello))
        imagen.save(ruta, format="PNG")
        return ruta
    except Exception as exc:
        print("AVISO: no se pudo guardar el PNG -> {}".format(exc))
        return None


def capturar_y_copiar(session, etiqueta):
    """Captura wnd[0], copia al portapapeles y opcionalmente guarda PNG."""
    try:
        hwnd = int(session.findById("wnd[0]").Handle)
    except Exception as exc:
        print("AVISO: no se pudo obtener el handle de SAP -> {}".format(exc))
        return None

    try:
        imagen = capturar_ventana(hwnd)
    except Exception as exc:
        print("AVISO: fallo la captura -> {}".format(exc))
        return None

    ruta = guardar_png(imagen, etiqueta) if GUARDAR_PNG else None

    try:
        copiar_al_portapapeles(imagen)
    except Exception as exc:
        print("AVISO: fallo el portapapeles -> {}".format(exc))

    return ruta


# ===========================================================================
# BLOQUE 3 - AS01
# ===========================================================================

def cargar_as01(session, datos):
    """
    Completa AS01 con los datos validados.
    Devuelve (grabado: bool, mensaje: str).
    """
    session.findById("wnd[0]").maximize()
    cerrar_popups(session)

    # --- Pantalla inicial -------------------------------------------------
    session.findById("wnd[0]/tbar[0]/okcd").text = "/nAS01"
    session.findById("wnd[0]").sendVKey(0)

    escribir(session, AS01_IDS["anlkl"], datos["ANLKL"], "Clase de activo (ANLA-ANLKL)")
    escribir(session, AS01_IDS["bukrs"], datos["BUKRS"], "Sociedad (ANLA-BUKRS)")
    session.findById("wnd[0]").sendVKey(0)

    tipo, mensaje = statusbar(session)
    if tipo in ("E", "A"):
        raise RuntimeError(
            "SAP rechazo clase {} / sociedad {}: {}".format(
                datos["ANLKL"], datos["BUKRS"], mensaje
            )
        )

    cerrar_popups(session)

    # --- Campos de las pestanas: se localizan por nombre tecnico ----------
    # (tipo GuiTextField = txt, GuiCTextField = ctxt con matchcode)
    campos_as01 = [
        ("ANLA-TXT50",  "GuiTextField",  "TXT50",  "Denominacion (ANLA-TXT50)"),
        ("ANLA-TXA50",  "GuiTextField",  "TXA50",  "Texto adicional (ANLA-TXA50)"),
        ("ANLZ-KOSTL",  "GuiCTextField", "KOSTL",  "Centro de coste (ANLZ-KOSTL)"),
        ("ANLZ-KOSTLV", "GuiCTextField", "KOSTLV", "CeCo responsable (ANLZ-KOSTLV)"),
        ("ANLA-ORD41",  "GuiCTextField", "ORD41",  "Asignacion 1 (ANLA-ORD41)"),
        ("ANLA-GDLGRP", "GuiCTextField", "GDLGRP", "Grupo de activos (ANLA-GDLGRP)"),
        ("ANLA-ORD43",  "GuiCTextField", "ORD43",  "Asignacion 3 (ANLA-ORD43)"),
        ("ANLA-ORD44",  "GuiCTextField", "ORD44",  "Asignacion 4 (ANLA-ORD44)"),
    ]
    for nombre, tipo, clave, etiqueta in campos_as01:
        escribir_as01(session, nombre, tipo, datos[clave], etiqueta)

    # Volver a la primera pestana para revisar en pantalla
    try:
        session.findById(TAB).Children(0).select()
    except Exception:
        pass

    # --- Grabar -----------------------------------------------------------
    if MODO_SIMULACION:
        return False, (
            "MODO SIMULACION: AS01 quedo completado en pantalla SIN grabar.\n"
            "Revisa los datos y grabalo a mano con Ctrl+S, o pone "
            "MODO_SIMULACION = False en el script."
        )

    if not confirmar(
        "Confirmar alta",
        "Se va a GRABAR el activo fijo en SAP.\n\n"
        "Clase : {}\nSoc.  : {}\nDenom.: {}\n\nContinuar?".format(
            datos["ANLKL"], datos["BUKRS"], datos["TXT50"]
        ),
    ):
        return False, "Alta cancelada por el usuario antes de grabar."

    session.findById(AS01_IDS["grabar"]).press()
    time.sleep(0.5)
    cerrar_popups(session)

    tipo, mensaje = statusbar(session)
    if tipo in ("E", "A"):
        raise RuntimeError("SAP rechazo el alta: {}".format(mensaje))

    return True, mensaje or "Activo creado (sin mensaje en statusbar)."


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    banfn = pedir_banfn()
    if not banfn:
        print("Cancelado por el usuario.")
        return 0

    print("Solicitud de pedido: {}".format(banfn))

    try:
        session = obtener_sesion()
    except RuntimeError as exc:
        print("ERROR: {}".format(exc))
        avisar("Conexion SAP", str(exc), error=True)
        return 1

    # --- 1. ME53N ---------------------------------------------------------
    try:
        abrir_me53n(session, banfn)
        posiciones_solped = extraer_todas_las_imputaciones(session)
    except Exception as exc:
        print("ERROR ME53N: {}".format(exc))
        avisar("ME53N", str(exc), error=True)
        return 1

    print("\n--- Datos leidos de la SolPed ---")
    for numero, posicion in enumerate(posiciones_solped, 1):
        texto = _texto_con_cantidad(posicion.get("texto_breve", ""), posicion.get("cantidad"))
        print(
            "  Posicion {}: {} (Cantidad: {})".format(
                numero, texto or "(sin descripcion)", posicion.get("cantidad") or "(sin cantidad)"
            )
        )

    # --- 2. Elegir estrategia y revisar ----------------------------------
    propuesta_primera = proponer_as01(posiciones_solped[0])
    if len(posiciones_solped) == 1:
        modo = "unico"
    else:
        modo = elegir_modo_activos(posiciones_solped, propuesta_primera)
        if modo is None:
            print("\nCarga en AS01 cancelada.")
            return 0

    if modo == "unico":
        datos_combinados = combinar_posiciones(posiciones_solped)
        # La clasificación del activo combinado se sugiere con la primera línea.
        propuesta = dict(propuesta_primera)
        propuesta["TXT50"] = _texto_con_cantidad(
            datos_combinados.get("texto_breve", ""),
            posiciones_solped[0].get("cantidad"),
        )[:50]
        datos_as01 = formulario_as01(propuesta)
        if datos_as01 is None:
            print("\nCarga en AS01 cancelada.")
            return 0
        datos_as01 = completar_derivados(datos_as01, propuesta)
        trabajos = [(datos_as01, propuesta)]
    else:
        trabajos = []
        for numero, posicion in enumerate(posiciones_solped, 1):
            propuesta = propuesta_primera if numero == 1 else proponer_as01(posicion)
            propuesta = dict(propuesta)
            propuesta["TXT50"] = propuesta.get("TXT50") or _texto_con_cantidad(
                posicion.get("texto_breve", ""), posicion.get("cantidad")
            )[:50]
            datos_as01 = formulario_as01(propuesta)
            if datos_as01 is None:
                print("\nCarga en AS01 cancelada. Los activos anteriores no se modifican.")
                return 0
            trabajos.append((completar_derivados(datos_as01, propuesta), propuesta))

    # --- 3. AS01 ----------------------------------------------------------
    for numero, (datos_as01, propuesta) in enumerate(trabajos, 1):
        try:
            grabado, mensaje = cargar_as01(session, datos_as01)
        except Exception as exc:
            print("ERROR AS01 en activo {}: {}".format(numero, exc))
            avisar(
                "AS01",
                "Fallo la carga del activo {}:\n\n{}\n\n"
                "La pantalla quedo como esta para que revises.".format(numero, exc),
                error=True,
            )
            return 1
        print("\nActivo {} procesado: {}".format(numero, mensaje))

    datos_as01 = trabajos[-1][0]
    resumen = (
        "SolPed {} -> AS01\n\n"
        "Activos procesados : {}\n"
        "Clase de activo : {}\n"
        "Sociedad        : {}\n"
        "Denominacion    : {}\n"
        "Centro de coste : {}\n\n"
        "{}"
    ).format(
        banfn,
        len(trabajos),
        datos_as01["ANLKL"],
        datos_as01["BUKRS"],
        datos_as01["TXT50"],
        datos_as01["KOSTL"] or "(vacio)",
        mensaje,
    )

    print("\n" + resumen)
    avisar("Grabado" if grabado else "Pendiente de grabar", resumen)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        sys.exit(130)