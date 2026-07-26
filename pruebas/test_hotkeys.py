# -*- coding: utf-8 -*-
"""Emparejamiento de hotkeys y construcción del registro.

La prueba de `mods` no es teórica: con la regla anterior ("sin modificadores" significaba
"ningún modificador pulsado"), F8 dejaba de funcionar en cuanto te agachabas en Minecraft
—que se hace con Mayús— y el fallo era intermitente e indiagnosticable dentro del juego.
"""

import unittest

import modelo
from hotkeys import Enlace, HiloHook, registro_desde_macros


def _macro(id_macro, sc, ext=0, mods=0, habilitada=True, tragar=False):
    m = modelo.Macro(id=id_macro, nombre=id_macro, habilitada=habilitada,
                     hotkey=modelo.Hotkey(sc=sc, ext=ext, mods=mods, vk=0x77,
                                          tragar_tecla=tragar),
                     accion=modelo.Accion(tipo=modelo.TIPO_MANTENER,
                                          objetivo=modelo.Objetivo(tipo="raton",
                                                                   boton="izq")))
    return m


class Emparejamiento(unittest.TestCase):

    def test_sin_modificadores_dispara_siempre(self):
        enlaces = (Enlace(0, "minar", False),)
        for mods in (0, 1, 2, 4, 7):
            elegido = HiloHook._elegir(enlaces, mods)
            self.assertIsNotNone(elegido, "F8 debe disparar con mods=%d" % mods)
            self.assertEqual(elegido.id_macro, "minar")

    def test_con_modificadores_los_exige(self):
        enlaces = (Enlace(1, "con_ctrl", False),)
        self.assertIsNone(HiloHook._elegir(enlaces, 0))
        self.assertIsNone(HiloHook._elegir(enlaces, 2))
        self.assertEqual(HiloHook._elegir(enlaces, 1).id_macro, "con_ctrl")
        self.assertEqual(HiloHook._elegir(enlaces, 5).id_macro, "con_ctrl")  # Ctrl+Mayús

    def test_gana_el_mas_especifico(self):
        enlaces = tuple(sorted([Enlace(0, "suelta", False), Enlace(1, "con_ctrl", False)],
                               key=lambda e: -e.mods))
        self.assertEqual(HiloHook._elegir(enlaces, 1).id_macro, "con_ctrl")
        self.assertEqual(HiloHook._elegir(enlaces, 0).id_macro, "suelta")
        self.assertEqual(HiloHook._elegir(enlaces, 4).id_macro, "suelta")

    def test_sin_candidatos(self):
        self.assertIsNone(HiloHook._elegir((Enlace(3, "a", False),), 1))


class Registro(unittest.TestCase):

    def test_agrupa_por_tecla_fisica(self):
        reg = registro_desde_macros([_macro("a", 66), _macro("b", 66, mods=1),
                                     _macro("c", 88)])
        self.assertEqual(set(reg), {(66, 0), (88, 0)})
        self.assertEqual(len(reg[(66, 0)]), 2)

    def test_ignora_deshabilitadas_y_sin_tecla(self):
        rota = _macro("rota", 66)
        rota.soportada = False
        reg = registro_desde_macros([_macro("apagada", 66, habilitada=False), rota,
                                     _macro("sin_tecla", 0)])
        self.assertEqual(reg, {})

    def test_marca_las_tragadas_y_ordena_por_especificidad(self):
        h = HiloHook(lambda i, a: None, lambda: None, lambda c: None)
        h.registrar(registro_desde_macros([_macro("a", 66), _macro("b", 66, mods=1),
                                           _macro("t", 88, tragar=True)]),
                    panico=(1, 0))
        self.assertEqual(h._tragadas, {(88, 0)})
        self.assertTrue(h._necesita_mods)
        self.assertEqual([e.mods for e in h._registro[(66, 0)]], [1, 0])

    def test_sin_modificadores_no_pregunta_por_ellos(self):
        """Optimización del camino caliente: 3 syscalls menos por pulsación."""
        h = HiloHook(lambda i, a: None, lambda: None, lambda c: None)
        h.registrar(registro_desde_macros([_macro("a", 66)]), panico=(1, 0))
        self.assertFalse(h._necesita_mods)


if __name__ == "__main__":
    unittest.main()
