# -*- coding: utf-8 -*-
"""Nombres legibles de teclas y conjuntos reservados.

La identidad canónica de una tecla es `(scanCode, ext)`: la POSICIÓN FÍSICA. Es independiente
de la distribución del teclado —lo que importa jugando— y distingue Intro de Intro-del-numpad
y Supr del punto del numpad, cosa que el virtual-key no siempre hace. El `vk` se guarda solo
para mostrar y para inyectar.

`EXTENDED_VKS` vive en `winapi.py` y aquí se importa: una sola tabla.
"""

import ctypes
from ctypes import wintypes

from winapi import EXTENDED_VKS, u32  # noqa: F401  (EXTENDED_VKS se reexporta a propósito)

MAPVK_VSC_TO_VK_EX = 3
MAPVK_VK_TO_VSC_EX = 4

u32.GetKeyNameTextW.argtypes = (wintypes.LONG, wintypes.LPWSTR, ctypes.c_int)
u32.GetKeyNameTextW.restype = ctypes.c_int
u32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.HKL)
u32.MapVirtualKeyExW.restype = wintypes.UINT
u32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
u32.GetKeyboardLayout.restype = wintypes.HKL

# Teclas que NO pueden bindearse con "tragar tecla": son las que usan los lectores de
# pantalla y la navegación del sistema. Tragarlas globalmente deja el equipo inutilizable
# para alguien que dependa de tecnología asistiva, y sin ninguna pista de la causa.
RESERVADAS_NO_TRAGABLES = frozenset({
    0x09,   # Tab
    0x14,   # Bloq Mayús
    0x1B,   # Esc
    0x2D,   # Insert
    0x5B, 0x5C,   # Windows izquierda / derecha
    0x70,   # F1 (ayuda)
    0x25, 0x26, 0x27, 0x28,   # flechas
})

# GetKeyNameTextW nombra mal unas cuantas, sobre todo las extendidas. Aquí mandan estas.
_NOMBRES_POR_VK = {
    0x03: "Cancelar",
    0x08: "Retroceso",
    0x09: "Tab",
    0x0C: "Borrar (numpad 5)",
    0x0D: "Intro",
    0x13: "Pausa",
    0x14: "Bloq Mayús",
    0x1B: "Esc",
    0x20: "Espacio",
    0x21: "Re Pág",
    0x22: "Av Pág",
    0x23: "Fin",
    0x24: "Inicio",
    0x25: "Flecha izquierda",
    0x26: "Flecha arriba",
    0x27: "Flecha derecha",
    0x28: "Flecha abajo",
    0x2C: "Impr Pant",
    0x2D: "Insert",
    0x2E: "Supr",
    0x5B: "Windows izquierda",
    0x5C: "Windows derecha",
    0x5D: "Menú contextual",
    0x90: "Bloq Num",
    0x91: "Bloq Despl",
    0xA0: "Mayús izquierda",
    0xA1: "Mayús derecha",
    0xA2: "Ctrl izquierda",
    0xA3: "Ctrl derecha",
    0xA4: "Alt izquierda",
    0xA5: "Alt Gr",
}
for _i in range(24):
    _NOMBRES_POR_VK[0x70 + _i] = "F%d" % (_i + 1)
for _i in range(10):
    _NOMBRES_POR_VK[0x60 + _i] = "Numpad %d" % _i
_NOMBRES_POR_VK.update({
    0x6A: "Numpad *", 0x6B: "Numpad +", 0x6D: "Numpad -",
    0x6E: "Numpad .", 0x6F: "Numpad /",
})

MOD_CTRL, MOD_ALT, MOD_MAYUS = 1, 2, 4
_ETIQUETAS_MOD = ((MOD_CTRL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_MAYUS, "Mayús"))


def _distribucion():
    return u32.GetKeyboardLayout(0)


def vk_desde_scancode(sc, ext):
    """Traduce la posición física al virtual-key de la distribución activa."""
    codigo = (0xE000 | (sc & 0xFF)) if ext else (sc & 0xFF)
    return int(u32.MapVirtualKeyExW(codigo, MAPVK_VSC_TO_VK_EX, _distribucion()))


def scancode_desde_vk(vk):
    """(sc, ext) para un virtual-key, según la distribución activa.

    MapVirtualKeyExW no marca como extendidas las flechas ni algunas más (rareza histórica de
    Windows: ese bit lo pone el teclado, no la tabla), así que se corrige con EXTENDED_VKS.
    Solo afecta a valores por defecto: las hotkeys reales las captura el hook, que sí trae el
    flag correcto.
    """
    codigo = int(u32.MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC_EX, _distribucion()))
    ext = 1 if (codigo & 0xE000) == 0xE000 else 0
    if not ext and vk in EXTENDED_VKS:
        ext = 1
    return (codigo & 0xFF, ext)


def nombre_de_tecla(sc, ext, vk=None):
    """Nombre legible en español de la tecla en la posición `(sc, ext)`."""
    if vk is None:
        vk = vk_desde_scancode(sc, ext)
    nombre = _NOMBRES_POR_VK.get(vk)
    if nombre:
        # Numpad e Intro comparten VK con sus gemelas: desempata la posición física.
        if vk == 0x0D and ext:
            return "Intro (numpad)"
        return nombre
    lparam = ((sc & 0xFF) << 16) | ((1 if ext else 0) << 24)
    buf = ctypes.create_unicode_buffer(64)
    if u32.GetKeyNameTextW(lparam, buf, 64) > 0 and buf.value.strip():
        return buf.value.strip()
    if vk:
        return "VK %d" % vk
    return "SC %d%s" % (sc, "e" if ext else "")


def descripcion_hotkey(hk):
    """'Ctrl+Alt+F8' a partir de un dict/objeto con sc, ext, vk y mods."""
    sc = _leer(hk, "sc", 0)
    ext = _leer(hk, "ext", 0)
    vk = _leer(hk, "vk", None)
    mods = _leer(hk, "mods", 0)
    partes = [etq for bit, etq in _ETIQUETAS_MOD if mods & bit]
    partes.append(nombre_de_tecla(sc, ext, vk))
    return "+".join(partes)


def _leer(obj, campo, defecto):
    if isinstance(obj, dict):
        return obj.get(campo, defecto)
    return getattr(obj, campo, defecto)
