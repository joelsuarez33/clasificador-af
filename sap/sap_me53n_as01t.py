# -*- coding: utf-8 -*-
"""
ME53N -> captura -> AS01
========================

Flujo completo:
  1. Pop-up pide el nro de solicitud de pedido (BANFN).
  2. Abre ME53N, navega a la SolPed y selecciona la pestana Imputacion.
  3. Extrae los datos de imputacion por ID de campo (sin OCR).
  4. Captura la pantalla y la deja en el portapapeles (Ctrl+V).
  5. Muestra un formulario de revision con los datos que se van a cargar.
     El controller confirma o corrige antes de tocar AS01.
  6. Abre AS01, completa clase de activo, sociedad, denominacion,
     centros de coste y campos de asignacion.
  7. Graba solo si MODO_SIMULACION = False y el usuario confirma.
     Devuelve el nro de activo que informa la statusbar.

Requisitos:
    pip install pywin32 pillow
    SAP GUI abierto y logueado, scripting habilitado (cliente y servidor).

Sin credenciales: reutiliza la sesion activa.
"""

import os
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
PW_RENDERFULLCONTENT = 0x00000002

# Valores por defecto de AS01. El formulario de revision permite cambiarlos.
DEFAULTS_AS01 = {
    "ANLKL":  "54000010",   # Clase de activo
    "BUKRS":  "MBA",        # Sociedad
    "TXT50":  "",           # Denominacion (se propone desde la SolPed)
    "TXA50":  "Propuesta LLM",
    "KOSTL":  "",           # Centro de coste
    "KOSTLV": "",           # Centro de coste responsable
    "ORD41":  "NAC",
    "ORD43":  "5400",
    "ORD44":  "B302",
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


def leer(session, ruta, defecto=""):
    """Lee .text de un control sin romper si no existe en la pantalla actual."""
    try:
        return str(session.findById(ruta).text).strip()
    except Exception:
        return defecto


def escribir(session, ruta, valor, etiqueta):
    """Escribe en un campo. Lanza RuntimeError con contexto si falla."""
    if valor is None or valor == "":
        return
    try:
        session.findById(ruta).text = valor
    except Exception as exc:
        raise RuntimeError(
            "No se pudo escribir '{}' en el campo {} -> {}".format(valor, etiqueta, exc)
        )


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


def proponer_as01(datos):
    """Arma la propuesta de AS01 combinando defaults con lo leido de la SolPed."""
    propuesta = dict(DEFAULTS_AS01)

    if datos.get("texto_breve"):
        propuesta["TXT50"] = datos["texto_breve"][:50]
    if datos.get("sociedad_co"):
        propuesta["BUKRS"] = datos["sociedad_co"]
    if datos.get("centro_coste"):
        propuesta["KOSTL"] = datos["centro_coste"]
        propuesta["KOSTLV"] = datos["centro_coste"]

    return propuesta


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

    # --- TAB01: datos generales ------------------------------------------
    try:
        session.findById(AS01_IDS["tab01"]).select()
    except Exception:
        pass
    escribir(session, AS01_IDS["txt50"], datos["TXT50"], "Denominacion (ANLA-TXT50)")
    escribir(session, AS01_IDS["txa50"], datos["TXA50"], "Texto adicional (ANLA-TXA50)")

    # --- TAB02: imputaciones ---------------------------------------------
    session.findById(AS01_IDS["tab02"]).select()
    escribir(session, AS01_IDS["kostl"], datos["KOSTL"], "Centro de coste (ANLZ-KOSTL)")
    escribir(session, AS01_IDS["kostlv"], datos["KOSTLV"], "CeCo responsable (ANLZ-KOSTLV)")

    # --- TAB03: asignaciones ---------------------------------------------
    session.findById(AS01_IDS["tab03"]).select()
    escribir(session, AS01_IDS["ord41"], datos["ORD41"], "Asignacion 1 (ANLA-ORD41)")
    escribir(session, AS01_IDS["ord43"], datos["ORD43"], "Asignacion 3 (ANLA-ORD43)")
    escribir(session, AS01_IDS["ord44"], datos["ORD44"], "Asignacion 4 (ANLA-ORD44)")

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
        datos_solped = extraer_imputacion(session)
    except Exception as exc:
        print("ERROR ME53N: {}".format(exc))
        avisar("ME53N", str(exc), error=True)
        return 1

    print("\n--- Datos leidos de la SolPed ---")
    for clave, valor in datos_solped.items():
        if valor:
            print("  {:<14}: {}".format(clave, valor))

    # --- 2. Captura -------------------------------------------------------
    ruta_png = capturar_y_copiar(session, "ME53N_{}".format(banfn))
    if ruta_png:
        print("\nCaptura guardada: {}".format(ruta_png))
    print("Captura disponible en el portapapeles (Ctrl+V).")

    # --- 3. Revision ------------------------------------------------------
    propuesta = proponer_as01(datos_solped)
    datos_as01 = formulario_as01(propuesta)
    if datos_as01 is None:
        print("\nCarga en AS01 cancelada. La captura sigue en el portapapeles.")
        return 0

    # --- 4. AS01 ----------------------------------------------------------
    try:
        grabado, mensaje = cargar_as01(session, datos_as01)
    except Exception as exc:
        print("ERROR AS01: {}".format(exc))
        avisar(
            "AS01",
            "Fallo la carga en AS01:\n\n{}\n\n"
            "La pantalla quedo como esta para que revises.".format(exc),
            error=True,
        )
        return 1

    capturar_y_copiar(session, "AS01_{}".format(banfn))

    resumen = (
        "SolPed {} -> AS01\n\n"
        "Clase de activo : {}\n"
        "Sociedad        : {}\n"
        "Denominacion    : {}\n"
        "Centro de coste : {}\n\n"
        "{}\n\n"
        "Captura de AS01 en el portapapeles (Ctrl+V)."
    ).format(
        banfn,
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