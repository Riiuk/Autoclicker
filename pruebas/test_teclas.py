# -*- coding: utf-8 -*-
"""Nombres de tecla e identidad (sc, ext). Toca Win32 real, pero no inyecta nada."""

import unittest

import teclas
import winapi


class Identidad(unittest.TestCase):

    def test_ida_y_vuelta_de_las_habituales(self):
        for vk in (0x41, 0x77, 0x7B, 0x0D, 0x20, 0x14, 0x26, 0xA3):
            sc, ext = teclas.scancode_desde_vk(vk)
            self.assertNotEqual(sc, 0, "sin scancode para vk 0x%02X" % vk)
            self.assertEqual(teclas.vk_desde_scancode(sc, ext), vk,
                             "no vuelve para vk 0x%02X (sc=%d ext=%d)" % (vk, sc, ext))

    def test_f8_y_f12_coinciden_con_el_esquema(self):
        self.assertEqual(teclas.scancode_desde_vk(0x77), (66, 0))    # F8
        self.assertEqual(teclas.scancode_desde_vk(0x7B), (88, 0))    # F12, pánico

    def test_las_extendidas_llevan_su_flag(self):
        for vk in (0x26, 0x2E, 0xA3, 0x5B):
            _, ext = teclas.scancode_desde_vk(vk)
            self.assertEqual(ext, 1, "vk 0x%02X debería ser extendida" % vk)

    def test_intro_del_numpad_se_distingue(self):
        self.assertEqual(teclas.nombre_de_tecla(28, 0, 0x0D), "Intro")
        self.assertEqual(teclas.nombre_de_tecla(28, 1, 0x0D), "Intro (numpad)")


class Nombres(unittest.TestCase):

    def test_nombres_en_espanol(self):
        casos = {0x77: "F8", 0x7B: "F12", 0x20: "Espacio", 0x1B: "Esc",
                 0x14: "Bloq Mayús", 0x26: "Flecha arriba", 0xA5: "Alt Gr"}
        for vk, esperado in casos.items():
            sc, ext = teclas.scancode_desde_vk(vk)
            self.assertEqual(teclas.nombre_de_tecla(sc, ext, vk), esperado)

    def test_nunca_devuelve_vacio(self):
        for sc in range(0, 90):
            for ext in (0, 1):
                self.assertTrue(teclas.nombre_de_tecla(sc, ext).strip())

    def test_descripcion_con_modificadores(self):
        hk = {"sc": 66, "ext": 0, "vk": 0x77, "mods": 7}
        self.assertEqual(teclas.descripcion_hotkey(hk), "Ctrl+Alt+Mayús+F8")
        hk["mods"] = 0
        self.assertEqual(teclas.descripcion_hotkey(hk), "F8")


class Reservadas(unittest.TestCase):
    """Hay teclas que no se pueden tragar globalmente sin dejar el equipo inservible
    para quien use un lector de pantalla."""

    def test_las_criticas_estan_protegidas(self):
        for vk in (0x14, 0x2D, 0x5B, 0x09, 0x1B, 0x70, 0x25, 0x26, 0x27, 0x28):
            self.assertIn(vk, teclas.RESERVADAS_NO_TRAGABLES)

    def test_f8_no_esta_protegida(self):
        self.assertNotIn(0x77, teclas.RESERVADAS_NO_TRAGABLES)


class TablaUnica(unittest.TestCase):
    """Una sola tabla de botones, y release_all la recorre."""

    def test_los_botones_tienen_flags_distintos(self):
        vistos = set()
        for clave, b in winapi.TABLA_BOTONES.items():
            self.assertEqual(clave, b.clave)
            self.assertTrue(b.etiqueta)
            vistos.add((b.abajo, b.arriba, b.datos))
        self.assertEqual(len(vistos), len(winapi.TABLA_BOTONES))

    def test_soltar_todo_ciego_recorre_la_tabla(self):
        from pruebas.falso import InyectorFalso
        iny = InyectorFalso()
        winapi.soltar_todo_ciego(iny, [87, 65])
        soltados = set(a for o, a in iny.eventos if o == "raton_arriba")
        self.assertEqual(soltados, set(winapi.TABLA_BOTONES))
        self.assertEqual([a for o, a in iny.eventos if o == "tecla_arriba"], [87, 65])

    def test_teclas_reexporta_la_tabla_de_winapi(self):
        self.assertIs(teclas.EXTENDED_VKS, winapi.EXTENDED_VKS)


if __name__ == "__main__":
    unittest.main()
