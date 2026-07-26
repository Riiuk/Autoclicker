# -*- coding: utf-8 -*-
"""Arranca el motor SIN interfaz, leyendo `config.json`.

Es la prueba de humo del paso 7 del plan y un entregable, no un script de usar y tirar: si
algo falla en Minecraft, esto dice si el problema está abajo (Win32, hook, motor) o arriba
(la GUI). Uso:

    python motor_test.py            # carga %APPDATA%\\Autoclicker\\config.json
    python motor_test.py otro.json  # carga un fichero concreto

Ctrl+C para salir. La tecla de pánico (F12 por defecto) también para todo.
"""

import json
import sys
import time

import almacen
import hotkeys
import modelo
import motor as motor_mod
import teclas
import winapi


def cargar(argv):
    if len(argv) > 1:
        # El mismo camino de lectura y validación que usa la aplicación: tolera BOM,
        # rechaza ficheros gigantes y nunca lanza por un JSON mal escrito.
        bruto, error = almacen.leer_json(argv[1])
        if error:
            print("  " + error)
            return None
        bruto, aviso = almacen.migrar(bruto)
        if aviso:
            print("  " + aviso)
            return None
        cfg, avisos = modelo.validar_config(bruto)
    else:
        cfg, avisos = almacen.cargar()
    for a in avisos:
        print("  aviso:", a)
    return cfg


def main(argv):
    cfg = cargar(argv)
    if cfg is None:
        return 2
    if not cfg.macros:
        print("No hay macros en la configuración. Crea alguna con la interfaz, o escribe un")
        print("config.json a mano (ver README).")
        return 2

    iny = winapi.Inyector()
    # Capa 6: por si un cierre anterior dejó algo pulsado. Un UP sin DOWN no hace daño.
    winapi.soltar_todo_ciego(iny)

    reloj = winapi.RelojWin32()
    motor = motor_mod.Motor(iny, reloj, notificar=lambda t, x: print("  [%s] %s" % (t, x)))
    motor_mod.instalar_redes_de_seguridad(motor)

    hook = hotkeys.HiloHook(motor.comando_hotkey, motor.panico, lambda c: None)
    hook.start()
    if not hook.esperar_listo():
        print("El hook de teclado no arrancó.")
        return 3
    hook.registrar(hotkeys.registro_desde_macros(cfg.macros),
                   cfg.ajustes.hotkey_panico.clave)
    motor.vigilar_hook(hook)
    motor.aplicar_config(cfg)
    motor.arrancar()

    print("Autoclicker (sin interfaz). Pánico: %s"
          % teclas.descripcion_hotkey(cfg.ajustes.hotkey_panico))
    for m in cfg.macros:
        estado = "activa" if (m.habilitada and m.soportada) else "deshabilitada"
        print("  %-28s %-14s %-18s [%s]" % (
            m.nombre, teclas.descripcion_hotkey(m.hotkey),
            modelo.ETIQUETAS_TIPO.get(m.accion.tipo, m.accion.tipo), estado))
    print("Ctrl+C para salir.")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nSaliendo...")
    finally:
        motor.parar()
        hook.parar()
        winapi.soltar_todo_ciego(iny)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
