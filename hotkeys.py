# -*- coding: utf-8 -*-
"""Hook global de teclado (WH_KEYBOARD_LL).

=============================== LÉEME ANTES DE TOCAR ESTO ===============================
Un hook de bajo nivel ve TODAS las pulsaciones de la máquina, en todas las aplicaciones:
contraseñas incluidas. La regla que separa esta herramienta de un keylogger:

  * La comparación contra las hotkeys registradas ocurre DENTRO del callback.
  * Lo único que sale del callback es `(id_macro, flanco)`.
  * Ningún vkCode ni scancode de una tecla NO registrada se copia fuera del frame, ni se
    guarda, ni se pasa a un logger, ni acaba en el mensaje de una excepción.
  * El conjunto anti-autorepeat contiene SOLO teclas registradas.

La única excepción autorizada es el modo captura, y por eso está acotado: de un solo
disparo, con timeout, y desarmado en cuanto el diálogo pierde el foco.

Además:
  * El callback nunca propaga una excepción: si se escapara, `PyErr_WriteUnraisable`
    formatearía un traceback dentro del hook (lo más caro que cabe hacer ahí) y volvería sin
    llamar a `CallNextHookEx`, cortando la cadena para el resto del software del sistema.
  * El hook se reinstala SIEMPRE desde este mismo hilo. `SetWindowsHookEx` desde otro
    hilo devuelve un handle válido cuyo callback no vuelve a dispararse jamás.
=========================================================================================
"""

import ctypes
import threading
import time
from ctypes import wintypes

from winapi import (EXTRA_SIG, EXTRA_SONDA, KBDLLHOOKSTRUCT, LRESULT, VK_SONDA, k32,
                    modificadores_pulsados, u32)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
LLKHF_EXTENDED = 0x01

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WM_APP_PARAR = 0x8001
WM_APP_REINSTALAR = 0x8002

SC_ESC = 1

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

u32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
u32.SetWindowsHookExW.restype = wintypes.HHOOK
u32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
u32.UnhookWindowsHookEx.restype = wintypes.BOOL
u32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
u32.CallNextHookEx.restype = LRESULT
u32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                            wintypes.UINT, wintypes.UINT)
u32.GetMessageW.restype = ctypes.c_int
u32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM)
u32.PostThreadMessageW.restype = wintypes.BOOL
k32.GetCurrentThreadId.argtypes = ()
k32.GetCurrentThreadId.restype = wintypes.DWORD
k32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
k32.GetModuleHandleW.restype = wintypes.HMODULE


class Enlace(object):
    """Una hotkey registrada: qué macro dispara y con qué modificadores."""

    __slots__ = ("mods", "id_macro", "tragar")

    def __init__(self, mods, id_macro, tragar):
        self.mods = mods
        self.id_macro = id_macro
        self.tragar = tragar


def registro_desde_macros(macros):
    """{(sc, ext): [Enlace, ...]} con las macros habilitadas. Una sola implementación para
    la UI y para `motor_test.py`."""
    reg = {}
    for m in macros:
        if not (m.habilitada and m.soportada and m.hotkey.asignada()):
            continue
        reg.setdefault(m.hotkey.clave, []).append(
            Enlace(m.hotkey.mods, m.id, m.hotkey.tragar_tecla))
    return reg


class HiloHook(threading.Thread):
    """Hilo dedicado con su propio bucle de mensajes.

    `despachar(id_macro, abajo)` se llama desde el callback: tiene que ser O(1) y no bloquear
    nunca (en el motor es un `append` a un deque más un `SetEvent`).
    """

    def __init__(self, despachar, al_pulsar_panico, al_capturar):
        threading.Thread.__init__(self, name="hook-ll", daemon=True)
        self._despachar = despachar
        self._al_pulsar_panico = al_pulsar_panico
        self._al_capturar = al_capturar

        self._registro = {}          # {(sc, ext): (Enlace, ...)} — se REEMPLAZA entero
        self._panico = (0x58, 0)     # F12 por defecto
        self._abajo = set()          # SOLO teclas registradas
        self._activas = {}           # (sc,ext) -> id_macro que disparó la bajada
        self._tragadas = set()       # (sc, ext) cuyo UP también hay que tragar
        self._necesita_mods = False  # si nadie usa modificadores, ni preguntamos

        self.captura_activa = False
        self._latido = time.perf_counter()
        self._sonda_vista = False
        self.reinstalaciones = 0

        self._hook = None
        self._tid = 0
        self._listo = threading.Event()
        # Referencia viva OBLIGATORIA: si el GC se lleva el CFUNCTYPE, el proceso muere sin
        # traceback la próxima vez que alguien toque una tecla.
        self._cb = HOOKPROC(self._al_llegar_tecla)

    # ------------------------------------------------------------------ configuración
    def registrar(self, enlaces_por_tecla, panico):
        """Reemplaza el registro completo. `enlaces_por_tecla`: {(sc,ext): [Enlace, ...]}."""
        nuevo = {}
        tragadas = set()
        necesita_mods = False
        for clave, enlaces in enlaces_por_tecla.items():
            # Los más específicos primero: si hay F8 y Ctrl+F8, gana Ctrl+F8 cuando toca.
            nuevo[clave] = tuple(sorted(enlaces, key=lambda e: -e.mods))
            if any(e.tragar for e in enlaces):
                tragadas.add(clave)
            if any(e.mods for e in enlaces):
                necesita_mods = True
        self._registro = nuevo          # asignación atómica: el callback ve una u otra, nunca a medias
        self._tragadas = tragadas
        self._necesita_mods = necesita_mods
        self._panico = panico
        self._abajo = set()
        self._activas = {}

    @staticmethod
    def _elegir(enlaces, mods):
        """Qué macro dispara esta tecla con los modificadores que haya pulsados.

        Una hotkey CON modificadores exige que estén pulsados. Una hotkey SIN modificadores
        dispara pase lo que pase: en Minecraft se juega con Mayús (agacharse) y Ctrl (correr)
        pulsados a ratos, y exigir "ningún modificador" haría que F8 fallara justo mientras
        minas agachado, de forma intermitente e indiagnosticable dentro del juego.
        """
        for e in enlaces:
            if e.mods and (mods & e.mods) == e.mods:
                return e
        for e in enlaces:
            if not e.mods:
                return e
        return None

    def armar_captura(self):
        self.captura_activa = True

    def desarmar_captura(self):
        self.captura_activa = False

    # ------------------------------------------------------------------ salud
    def latido(self):
        return self._latido

    def lanzar_sonda_recibida(self):
        """Devuelve si la sonda llegó desde la última consulta, y rearma el testigo."""
        visto = self._sonda_vista
        self._sonda_vista = False
        return visto

    def pedir_reinstalacion(self):
        """Solicita al hilo del hook que se reinstale. Nunca instales desde fuera."""
        if self._tid:
            u32.PostThreadMessageW(self._tid, WM_APP_REINSTALAR, 0, 0)

    # ------------------------------------------------------------------ el callback
    def _al_llegar_tecla(self, ncode, wparam, lparam):
        try:
            if ncode == HC_ACTION:
                kb = KBDLLHOOKSTRUCT.from_address(lparam)   # sin crear objetos puntero
                extra = kb.dwExtraInfo

                if extra == EXTRA_SONDA:
                    # Nuestra sonda de salud: la reconocemos y la TRAGAMOS, así que ninguna
                    # aplicación la ve nunca mientras el hook esté vivo.
                    self._sonda_vista = True
                    self._latido = time.perf_counter()
                    return 1
                if extra == EXTRA_SIG:
                    # Input que hemos inyectado nosotros: pasa de largo, sin realimentación.
                    return u32.CallNextHookEx(None, ncode, wparam, lparam)

                self._latido = time.perf_counter()
                sc = kb.scanCode
                ext = 1 if (kb.flags & LLKHF_EXTENDED) else 0
                clave = (sc, ext)
                arriba = wparam == WM_KEYUP or wparam == WM_SYSKEYUP

                # Pánico primero y siempre: tiene que funcionar aunque todo lo demás falle.
                # Aquí dentro solo se marca un evento; jamás se inyecta ni se hace E/S.
                if clave == self._panico:
                    if not arriba:
                        self._al_pulsar_panico()
                    return u32.CallNextHookEx(None, ncode, wparam, lparam)

                if self.captura_activa:
                    # Única excepción autorizada y acotada. Nunca traga: si se
                    # tragase, un lector de pantalla se quedaría mudo a mitad del diálogo.
                    if not arriba:
                        if sc == SC_ESC and not ext:
                            self._al_capturar(None)
                        else:
                            self._al_capturar((sc, ext, kb.vkCode))
                    return u32.CallNextHookEx(None, ncode, wparam, lparam)

                enlaces = self._registro.get(clave)
                if enlaces is None:
                    # Tecla no registrada: se acabó. No se guarda, no se encola, no se copia.
                    return u32.CallNextHookEx(None, ncode, wparam, lparam)

                if arriba:
                    self._abajo.discard(clave)
                    # El flanco de subida va a la MISMA macro que arrancó el de bajada,
                    # aunque el usuario haya soltado un modificador por el camino.
                    id_macro = self._activas.pop(clave, None)
                    if id_macro is not None:
                        self._despachar(id_macro, False)
                elif clave not in self._abajo:
                    # Solo la transición: el auto-repeat del teclado son ~30 pulsaciones por
                    # segundo y dispararía la macro decenas de veces.
                    self._abajo.add(clave)
                    mods = modificadores_pulsados() if self._necesita_mods else 0
                    elegido = self._elegir(enlaces, mods)
                    if elegido is not None:
                        self._activas[clave] = elegido.id_macro
                        self._despachar(elegido.id_macro, True)

                if clave in self._tragadas:
                    return 1
        except Exception:
            # Jamás propagar hacia Win32. Y jamás registrar nada aquí: el texto de la
            # excepción podría llevar el código de una tecla ajena.
            pass
        return u32.CallNextHookEx(None, ncode, wparam, lparam)

    # ------------------------------------------------------------------ ciclo de vida
    def _instalar(self):
        h = u32.SetWindowsHookExW(WH_KEYBOARD_LL, self._cb, k32.GetModuleHandleW(None), 0)
        # hMod = el módulo actual es válido porque los hooks de bajo nivel NO se inyectan en
        # otros procesos: corren en el nuestro, así que no hace falta una DLL aparte.
        self._hook = h if h else None
        return self._hook is not None

    def _desinstalar(self):
        if self._hook:
            u32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def run(self):
        self._tid = k32.GetCurrentThreadId()
        self._instalar()
        self._listo.set()
        msg = wintypes.MSG()
        try:
            while True:
                r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_APP_PARAR:
                    break
                if msg.message == WM_APP_REINSTALAR:
                    self._desinstalar()
                    if self._instalar():
                        self.reinstalaciones += 1
        finally:
            self._desinstalar()   # desenganchar en el MISMO hilo que enganchó

    def esperar_listo(self, timeout=5.0):
        return self._listo.wait(timeout)

    def parar(self):
        if self._tid:
            u32.PostThreadMessageW(self._tid, WM_APP_PARAR, 0, 0)
