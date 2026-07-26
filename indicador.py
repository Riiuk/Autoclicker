# -*- coding: utf-8 -*-
"""Avisos que llegan con el juego en primer plano.

El 100 % del uso del programa ocurre con Minecraft delante y esta ventana escondida detrás.
Todo lo que se cuente solo en la barra de estado es, en la práctica, invisible. De ahí dos
canales que sí llegan:

  * `Sonidos`: tonos cortos y distinguibles entre sí. `winsound.Beep` BLOQUEA mientras suena,
    así que va en su propio hilo: si sonara en el hilo de Tk, pararía el drenaje de la cola.
  * `Indicador`: una ventanita sin bordes, siempre encima, en una esquina. Marcada como no
    activable para que no le robe el foco al juego al aparecer.
"""

import queue
import threading
import tkinter as tk

import winapi

try:
    import winsound
except ImportError:      # por si algún día esto corre fuera de Windows
    winsound = None


class Sonidos(object):
    """Tonos distintos por evento. Suenan aunque la ventana no tenga el foco."""

    TONOS = {
        "arranca":    ((880, 55), (1245, 65)),          # sube: macro armada
        "para":       ((1245, 55), (880, 65)),          # baja: macro parada
        "panico":     ((392, 110), (330, 110), (262, 160)),
        "aviso_auto": ((660, 70), (660, 70)),
        "uipi":       ((523, 90), (392, 90), (523, 90)),
        "hook":       ((740, 60), (740, 60), (740, 60)),
        "conflicto":  ((330, 120),),
    }

    def __init__(self, activos=True):
        self.activos = activos
        self._cola = queue.Queue(maxsize=8)
        self._hilo = threading.Thread(target=self._sonar, name="sonidos", daemon=True)
        self._hilo.start()

    def evento(self, tipo):
        if not self.activos or winsound is None:
            return
        tonos = self.TONOS.get(tipo)
        if not tonos:
            return
        try:
            self._cola.put_nowait(tonos)
        except queue.Full:
            pass          # si vamos con retraso, mejor perder un pitido que acumularlos

    def _sonar(self):
        while True:
            tonos = self._cola.get()
            for frecuencia, ms in tonos:
                try:
                    winsound.Beep(frecuencia, ms)
                except (RuntimeError, ValueError, OSError):
                    return      # sin altavoz o sin permiso: nos callamos y ya


class Indicador(object):
    """Ventanita flotante con la macro activa. Best effort sobre pantalla completa."""

    def __init__(self, raiz, activo=True):
        self._raiz = raiz
        self.activo = activo
        self._top = None
        self._texto = tk.StringVar(value="")

    def _crear(self):
        if self._top is not None:
            return
        top = tk.Toplevel(self._raiz)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.88)
        except tk.TclError:
            pass
        marco = tk.Frame(top, padx=10, pady=6, borderwidth=1, relief="solid")
        marco.pack()
        tk.Label(marco, textvariable=self._texto).pack()
        top.update_idletasks()
        winapi.hacer_ventana_no_activable(top.winfo_id())
        self._top = top

    def mostrar(self, texto):
        if not self.activo:
            return
        self._crear()
        self._texto.set(texto)
        self._top.update_idletasks()
        ancho = self._top.winfo_reqwidth()
        pantalla = self._raiz.winfo_screenwidth()
        margen = max(8, int(self._raiz.winfo_fpixels("2m")))
        self._top.geometry("+%d+%d" % (pantalla - ancho - margen, margen))
        self._top.deiconify()
        self._top.lift()

    def ocultar(self):
        if self._top is not None:
            self._top.withdraw()

    def destruir(self):
        if self._top is not None:
            self._top.destroy()
            self._top = None
