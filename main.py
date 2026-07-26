# -*- coding: utf-8 -*-
"""Arranque y cableado.

Orden importante:
  1. Conciencia de DPI ANTES de crear la ventana de Tk (después ya no sirve de nada).
  2. Instancia única: si ya hay una, se trae al frente y salimos, en vez de morir en silencio.
  3. `soltar_todo_ciego()` preventivo: si un cierre anterior dejó un botón pulsado, esto lo
     arregla. Un UP sin su DOWN es inocuo.
  4. Redes de seguridad (`atexit`, excepthooks) antes de que nada pueda fallar.
"""

import queue
import sys
import tkinter as tk

import almacen
import hotkeys
import motor as motor_mod
import ui
import winapi

TAM_COLA = 256


def _crear_cola():
    """Cola CON PÉRDIDAS hacia la interfaz: se tira lo más viejo antes que bloquear a nadie.

    Es telemetría, no órdenes. Las órdenes (hotkey -> motor) van por otro canal que no pasa
    por Tk, porque Windows congela los `after()` mientras arrastras la ventana y apagar una
    macro no puede depender de eso.
    """
    cola = queue.Queue(maxsize=TAM_COLA)

    def publicar(tipo, dato):
        try:
            cola.put_nowait((tipo, dato))
        except queue.Full:
            try:
                cola.get_nowait()
            except queue.Empty:
                pass
            try:
                cola.put_nowait((tipo, dato))
            except queue.Full:
                pass

    return cola, publicar


def main():
    winapi.activar_conciencia_dpi()

    primera, _mutex = winapi.reclamar_instancia_unica()
    if not primera:
        winapi.enfocar_ventana(ui.TITULO_BASE)
        return 0

    iny = winapi.Inyector()
    winapi.soltar_todo_ciego(iny)

    reloj = winapi.RelojWin32()
    cola, publicar = _crear_cola()
    motor = motor_mod.Motor(iny, reloj, notificar=publicar)
    motor_mod.instalar_redes_de_seguridad(motor)

    hook = hotkeys.HiloHook(motor.comando_hotkey, motor.panico,
                            lambda datos: publicar("captura", datos))
    hook.start()
    if not hook.esperar_listo():
        publicar("aviso", "El hook de teclado no arrancó: las teclas no funcionarán.")
    motor.vigilar_hook(hook)

    cfg, avisos = almacen.cargar()

    raiz = tk.Tk()
    raiz.withdraw()

    def _error_de_tk(tipo, valor, tb):
        # tkinter NO enruta a sys.excepthook los fallos de los callbacks de widget, y con
        # --noconsole sys.stderr es None, así que sin esto el hilo de la interfaz —donde
        # vivirán la mayoría de los bugs— no dejaría rastro.
        motor.emergencia()
        almacen.registrar_excepcion(tipo, valor, tb, "interfaz")

    tk.Tk.report_callback_exception = staticmethod(_error_de_tk)

    app = ui.Aplicacion(raiz, motor, hook, cfg, cola, avisos)
    motor.arrancar()
    raiz.protocol("WM_DELETE_WINDOW", app.cerrar)
    raiz.deiconify()
    try:
        raiz.mainloop()
    finally:
        motor.parar()
        hook.parar()
        winapi.soltar_todo_ciego(iny, motor.estado.teclas_deseadas())
    return 0


if __name__ == "__main__":
    sys.exit(main())
