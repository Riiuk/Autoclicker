# -*- coding: utf-8 -*-
"""Genera `autoclicker.ico` con marcos 16/32/48/256, sin dependencias externas.

Windows saca de un `.ico` tamaños distintos para la barra de tareas, Alt-Tab, la esquina de
la ventana y el Explorador. A 150 % y 200 % pide tamaños que un icono de un solo marco no
tiene, y los inventa reescalando: es la pista más barata de que una aplicación no está
preparada para DPI.

Uso:  python assets/generar_icono.py
"""

import math
import os
import struct
import zlib

TAMANOS = (16, 32, 48, 256)
SUPER = 4                        # supermuestreo para que los bordes no queden dentados

FONDO = (37, 99, 168)            # azul
TINTA = (255, 255, 255)


def _dibujar(n):
    """Devuelve RGBA (bytes) de un icono de n x n: cuadrado redondeado, anillo y punto."""
    g = n * SUPER
    centro = (g - 1) / 2.0
    radio_esquina = g * 0.22
    margen = g * 0.06
    r_anillo_ext = g * 0.30
    r_anillo_int = g * 0.22
    r_punto = g * 0.11

    acumulado = bytearray(n * n * 4)
    muestras = SUPER * SUPER
    for py in range(n):
        for px in range(n):
            sr = sg = sb = sa = 0
            for sy in range(SUPER):
                for sx in range(SUPER):
                    x = px * SUPER + sx
                    y = py * SUPER + sy
                    # cuadrado redondeado
                    dx = max(margen + radio_esquina - x, 0,
                             x - (g - 1 - margen - radio_esquina))
                    dy = max(margen + radio_esquina - y, 0,
                             y - (g - 1 - margen - radio_esquina))
                    dentro = math.hypot(dx, dy) <= radio_esquina
                    if not dentro:
                        continue
                    d = math.hypot(x - centro, y - centro)
                    if d <= r_punto or (r_anillo_int <= d <= r_anillo_ext):
                        color = TINTA
                    else:
                        color = FONDO
                    sr += color[0]
                    sg += color[1]
                    sb += color[2]
                    sa += 255
            i = (py * n + px) * 4
            if sa:
                # los canales de color se promedian solo sobre las muestras opacas
                opacas = sa // 255
                acumulado[i] = sr // opacas
                acumulado[i + 1] = sg // opacas
                acumulado[i + 2] = sb // opacas
            acumulado[i + 3] = sa // muestras
    return bytes(acumulado)


def _png(n, rgba):
    def trozo(tipo, datos):
        cuerpo = tipo + datos
        return (struct.pack(">I", len(datos)) + cuerpo
                + struct.pack(">I", zlib.crc32(cuerpo) & 0xFFFFFFFF))

    crudo = b"".join(b"\x00" + rgba[y * n * 4:(y + 1) * n * 4] for y in range(n))
    return (b"\x89PNG\r\n\x1a\n"
            + trozo(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(crudo, 9))
            + trozo(b"IEND", b""))


def _dib(n, rgba):
    """BITMAPINFOHEADER + BGRA de abajo arriba + máscara AND vacía."""
    cabecera = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, n * n * 4, 0, 0, 0, 0)
    filas = []
    for y in range(n - 1, -1, -1):
        fila = bytearray()
        for x in range(n):
            i = (y * n + x) * 4
            fila += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
        filas.append(bytes(fila))
    bytes_mascara = ((n + 31) // 32) * 4 * n
    return cabecera + b"".join(filas) + b"\x00" * bytes_mascara


def generar(ruta):
    marcos = []
    for n in TAMANOS:
        rgba = _dibujar(n)
        # PNG solo para 256 (lo que espera Windows); DIB para el resto, que es lo más
        # compatible con herramientas antiguas y con el empaquetador.
        marcos.append((n, _png(n, rgba) if n >= 256 else _dib(n, rgba)))

    cabecera = struct.pack("<HHH", 0, 1, len(marcos))
    desplazamiento = len(cabecera) + 16 * len(marcos)
    entradas = b""
    for n, datos in marcos:
        entradas += struct.pack("<BBBBHHII", n if n < 256 else 0, n if n < 256 else 0,
                                0, 0, 1, 32, len(datos), desplazamiento)
        desplazamiento += len(datos)
    with open(ruta, "wb") as f:
        f.write(cabecera + entradas + b"".join(d for _, d in marcos))
    return os.path.getsize(ruta)


if __name__ == "__main__":
    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoclicker.ico")
    print("%s  (%d bytes, marcos %s)" % (destino, generar(destino),
                                         ", ".join(str(t) for t in TAMANOS)))
