# -*- coding: utf-8 -*-
"""Pruebas del motor. La primera es la que importa: nada puede quedarse pulsado."""

import unittest

import modelo
from modelo import Accion, Ajustes, Config, Hotkey, Macro, Objetivo, Paso
from motor import EstadoPulsado, Motor
from pruebas.falso import InyectorFalso, RelojFalso, correr


def _cfg(*macros):
    aj = Ajustes()
    aj.seguir_foco = False      # el vigilante de foco toca Win32; se prueba aparte
    return Config(ajustes=aj, macros=list(macros))


def _mantener(id_macro="m1", boton="izq", auto_soltar_min=0, modo="toggle"):
    return Macro(id=id_macro, nombre="Minar", habilitada=True,
                 hotkey=Hotkey(sc=66, ext=0, vk=0x77, nombre="F8", modo=modo),
                 accion=Accion(tipo=modelo.TIPO_MANTENER,
                               objetivo=Objetivo(tipo="raton", boton=boton)),
                 auto_soltar_min=auto_soltar_min)


def _clic_auto(id_macro="m2", intervalo=83, duracion=30, repeticiones=0, jitter=0):
    return Macro(id=id_macro, nombre="Clicar", habilitada=True,
                 hotkey=Hotkey(sc=67, ext=0, vk=0x78, nombre="F9"),
                 accion=Accion(tipo=modelo.TIPO_CLIC_AUTO,
                               objetivo=Objetivo(tipo="raton", boton="izq"),
                               intervalo_ms=intervalo, duracion_ms=duracion,
                               jitter_intervalo_ms=jitter, repeticiones=repeticiones))


def _secuencia(id_macro="m3", repeticiones=0):
    return Macro(id=id_macro, nombre="Andar y picar", habilitada=True,
                 hotkey=Hotkey(sc=68, ext=0, vk=0x79, nombre="F10"),
                 accion=Accion(tipo=modelo.TIPO_SECUENCIA, repeticiones=repeticiones,
                               pasos=[Paso(op=modelo.OP_TECLA_ABAJO, vk=87),
                                      Paso(op=modelo.OP_ESPERAR, ms=500),
                                      Paso(op=modelo.OP_TECLA_ARRIBA, vk=87),
                                      Paso(op=modelo.OP_CLIC, boton="izq",
                                           duracion_ms=30)]))


class Base(unittest.TestCase):

    def montar(self, cfg):
        self.reloj = RelojFalso()
        self.iny = InyectorFalso(self.reloj)
        self.avisos = []
        self.motor = Motor(self.iny, self.reloj,
                           notificar=lambda t, x: self.avisos.append((t, x)))
        self.motor.preparar()
        self.motor.aplicar_config(cfg)
        correr(self.motor, self.reloj, 0.01)
        return self.motor

    def tipos_de_aviso(self):
        return [t for t, _ in self.avisos]


class InvarianteDeSuelta(Base):
    """Tras parar, pánico o soltar todo, TODO down tiene su up."""

    def test_mantener_toggle(self):
        m = self.montar(_cfg(_mantener()))
        m.comando_hotkey("m1", True)
        correr(m, self.reloj, 1.0)
        self.assertEqual(self.iny.cuenta("raton_abajo", "izq"), 1)
        self.assertEqual(self.iny.pendientes(), {("raton", "izq")})

        m.comando_hotkey("m1", True)     # segunda pulsación = soltar
        correr(m, self.reloj, 0.5)
        self.assertEqual(self.iny.cuenta("raton_arriba", "izq"), 1)
        self.assertEqual(self.iny.pendientes(), set())

    def test_mantener_no_reafirma_el_boton(self):
        """Un segundo LEFTDOWN reiniciaría el progreso de rotura del bloque en Minecraft."""
        m = self.montar(_cfg(_mantener()))
        m.comando_hotkey("m1", True)
        correr(m, self.reloj, 600.0)     # diez minutos de tiempo virtual
        self.assertEqual(self.iny.cuenta("raton_abajo", "izq"), 1)

    def test_panico_con_las_tres_acciones(self):
        m = self.montar(_cfg(_mantener("a"), _clic_auto("b"), _secuencia("c")))
        # 'b' choca con 'a' por el botón izquierdo, así que se prueban por separado.
        for id_macro in ("a", "c"):
            m.comando_hotkey(id_macro, True)
        correr(m, self.reloj, 2.0)
        self.assertTrue(self.iny.pendientes())

        m.panico()
        correr(m, self.reloj, 0.1)
        self.assertEqual(self.iny.pendientes(), set())
        self.assertIn("panico", self.tipos_de_aviso())
        self.assertEqual(m.estado_macros(), {"a": False, "b": False, "c": False})

    def test_secuencia_cortada_a_media_no_deja_teclas(self):
        m = self.montar(_cfg(_secuencia()))
        m.comando_hotkey("m3", True)
        correr(m, self.reloj, 0.2)       # justo en mitad del "esperar 500 ms" con la W abajo
        self.assertEqual(self.iny.pendientes(), {("tecla", 87)})
        m.parar_todas()
        correr(m, self.reloj, 0.05)
        self.assertEqual(self.iny.pendientes(), set())

    def test_maestro_apagado_suelta_todo(self):
        m = self.montar(_cfg(_mantener()))
        m.comando_hotkey("m1", True)
        correr(m, self.reloj, 0.5)
        m.activar_maestro(False)
        correr(m, self.reloj, 0.05)
        self.assertEqual(self.iny.pendientes(), set())


class Temporizacion(Base):

    def test_clic_auto_sin_deriva(self):
        """El CPS medio no basta: cada evento tiene que caer donde toca."""
        m = self.montar(_cfg(_clic_auto(intervalo=83, duracion=30)))
        m.comando_hotkey("m2", True)
        correr(m, self.reloj, 10.0)
        bajadas = self.iny.instantes_de("raton_abajo", "izq")
        self.assertGreaterEqual(len(bajadas), 119)
        self.assertLessEqual(len(bajadas), 121)
        huecos = [b - a for a, b in zip(bajadas, bajadas[1:])]
        peor = max(abs(h - 0.083) for h in huecos)
        self.assertLess(peor, 1e-6, "deriva por evento de %.6f s" % peor)

        subidas = self.iny.instantes_de("raton_arriba", "izq")
        duraciones = [u - d for d, u in zip(bajadas, subidas)]
        self.assertLess(max(abs(x - 0.030) for x in duraciones), 1e-6)

    def test_repeticiones_finitas(self):
        m = self.montar(_cfg(_clic_auto(repeticiones=5)))
        m.comando_hotkey("m2", True)
        correr(m, self.reloj, 5.0)
        self.assertEqual(self.iny.cuenta("raton_abajo", "izq"), 5)
        self.assertEqual(self.iny.pendientes(), set())
        self.assertFalse(m.estado_macros()["m2"])

    def test_jitter_dentro_de_rango(self):
        m = self.montar(_cfg(_clic_auto(intervalo=100, duracion=20, jitter=12)))
        m.comando_hotkey("m2", True)
        correr(m, self.reloj, 20.0)
        bajadas = self.iny.instantes_de("raton_abajo", "izq")
        huecos = [b - a for a, b in zip(bajadas, bajadas[1:])]
        self.assertGreater(len(set(round(h, 6) for h in huecos)), 5, "no hay aleatoriedad")
        for h in huecos:
            self.assertGreaterEqual(h, 0.088 - 1e-9)
            self.assertLessEqual(h, 0.112 + 1e-9)

    def test_debounce_ignora_rebotes(self):
        m = self.montar(_cfg(_mantener()))
        m.comando_hotkey("m1", True)
        correr(m, self.reloj, 0.05)      # dentro de los 150 ms de debounce
        m.comando_hotkey("m1", True)     # se ignora: no debe apagarla
        correr(m, self.reloj, 0.05)
        self.assertEqual(self.iny.cuenta("raton_arriba", "izq"), 0)


class ArbitroYFoco(Base):

    def test_rechaza_la_segunda_macro_sobre_el_mismo_boton(self):
        m = self.montar(_cfg(_mantener("a"), _clic_auto("b")))
        m.comando_hotkey("a", True)
        correr(m, self.reloj, 0.3)
        m.comando_hotkey("b", True)
        correr(m, self.reloj, 0.3)
        self.assertIn("conflicto", self.tipos_de_aviso())
        self.assertTrue(m.estado_macros()["a"])
        self.assertFalse(m.estado_macros()["b"])
        self.assertEqual(self.iny.cuenta("raton_abajo", "izq"), 1)

    def test_libera_el_recurso_al_parar(self):
        m = self.montar(_cfg(_mantener("a"), _clic_auto("b")))
        m.comando_hotkey("a", True)
        correr(m, self.reloj, 0.3)
        m.comando_hotkey("a", True)      # parar
        correr(m, self.reloj, 0.3)
        m.comando_hotkey("b", True)      # ahora sí debe poder
        correr(m, self.reloj, 0.3)
        self.assertTrue(m.estado_macros()["b"])

    def test_dead_man_avisa_y_suelta(self):
        m = self.montar(_cfg(_mantener(auto_soltar_min=1)))
        m.comando_hotkey("m1", True)
        correr(m, self.reloj, 51.0)
        self.assertIn("aviso_auto", self.tipos_de_aviso())
        self.assertTrue(m.estado_macros()["m1"])
        correr(m, self.reloj, 12.0)
        self.assertFalse(m.estado_macros()["m1"])
        self.assertEqual(self.iny.pendientes(), set())


class AltTab(unittest.TestCase):
    """El vigilante de foco es la única capa que REPULSA; se prueba aislado."""

    def setUp(self):
        self.iny = InyectorFalso()
        self.estado = EstadoPulsado(self.iny)

    def test_suelta_al_salir_y_repulsa_al_volver(self):
        self.estado.pulsar_boton("izq", "m1")
        self.estado.inhibir()
        self.assertEqual(self.iny.pendientes(), set())
        self.estado.restaurar()
        self.assertEqual(self.iny.pendientes(), {("raton", "izq")})
        self.assertEqual(self.iny.cuenta("raton_abajo", "izq"), 2)

    def test_tras_el_panico_no_repulsa_nada(self):
        """Si el pánico salta con el juego en segundo plano, volver al juego NO debe
        volver a pulsar el botón."""
        self.estado.pulsar_boton("izq", "m1")
        self.estado.inhibir()
        self.estado.soltar_todo()
        self.iny.eventos = []
        self.estado.restaurar()
        self.assertEqual(self.iny.eventos, [])

    def test_no_pulsa_mientras_esta_inhibido(self):
        self.estado.inhibir()
        self.estado.pulsar_boton("izq", "m1")
        self.assertEqual(self.iny.eventos, [])
        self.estado.restaurar()
        self.assertEqual(self.iny.cuenta("raton_abajo", "izq"), 1)


if __name__ == "__main__":
    unittest.main()
