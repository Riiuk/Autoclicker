# -*- coding: utf-8 -*-
"""Validador y serialización. La regla de oro: NUNCA lanza."""

import unittest

import modelo


def _macro_ok():
    return {"id": "b3f1c8a2", "nombre": "Minar", "habilitada": True,
            "hotkey": {"sc": 66, "ext": 0, "vk": 119, "mods": 0, "nombre": "F8",
                       "modo": "toggle", "tragar_tecla": False},
            "accion": {"tipo": "MANTENER",
                       "objetivo": {"tipo": "raton", "boton": "izq"}},
            "auto_soltar_min": 0, "retardo_inicial_ms": 0}


class ValidadorNoLanza(unittest.TestCase):

    def _degrada(self, macro_bruta, pista=None):
        m = modelo.validar_macro(macro_bruta)
        self.assertFalse(m.soportada, "debería haberse degradado: %r" % (macro_bruta,))
        self.assertFalse(m.habilitada)
        if pista:
            self.assertIn(pista, m.motivo)
        return m

    def test_macro_valida(self):
        m = modelo.validar_macro(_macro_ok())
        self.assertTrue(m.soportada)
        self.assertEqual(m.accion.objetivo.boton, "izq")
        self.assertEqual(m.hotkey.clave, (66, 0))

    def test_vk_fuera_de_rango(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "MANTENER", "objetivo": {"tipo": "tecla", "vk": 70000}}
        self._degrada(b, "fuera de rango")

    def test_vk_negativo_y_no_entero(self):
        for valor in (-1, 3.5, "87", True, None):
            b = _macro_ok()
            b["accion"] = {"tipo": "MANTENER", "objetivo": {"tipo": "tecla", "vk": valor}}
            self._degrada(b)

    def test_espera_absurda(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "SECUENCIA",
                       "pasos": [{"op": "esperar", "ms": 999999999}]}
        self._degrada(b, "fuera de rango")

    def test_operacion_desconocida(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "SECUENCIA", "pasos": [{"op": "formatear_disco"}]}
        self._degrada(b, "desconocida")

    def test_tipo_de_accion_desconocido(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "TELETRANSPORTAR"}
        self._degrada(b, "desconocido")

    def test_boton_inventado(self):
        b = _macro_ok()
        b["accion"]["objetivo"]["boton"] = "rueda_del_destino"
        self._degrada(b, "desconocido")

    def test_demasiados_pasos(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "SECUENCIA",
                       "pasos": [{"op": "esperar", "ms": 10}] * (modelo.MAX_PASOS + 1)}
        self._degrada(b, "más de")

    def test_sin_tecla_asignada(self):
        b = _macro_ok()
        b["hotkey"]["sc"] = 0
        b["hotkey"]["ext"] = 0
        self._degrada(b, "tecla")

    def test_basura_pura(self):
        for basura in (None, 42, "hola", [], {"a": 1}):
            m = modelo.validar_macro(basura)
            self.assertFalse(m.soportada)
            self.assertTrue(m.id)

    def test_intervalo_no_puede_comerse_la_duracion(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "CLIC_AUTO", "objetivo": {"tipo": "raton", "boton": "izq"},
                       "duracion_ms": 50, "intervalo_ms": 10}
        m = modelo.validar_macro(b)
        self.assertTrue(m.soportada)
        self.assertEqual(m.accion.intervalo_ms, 50 + modelo.HOLGURA_INTERVALO_MS)

    def test_duracion_por_debajo_del_minimo(self):
        b = _macro_ok()
        b["accion"] = {"tipo": "CLIC_AUTO", "objetivo": {"tipo": "raton", "boton": "izq"},
                       "duracion_ms": 1}
        self._degrada(b, "fuera de rango")


class ConfigCompleta(unittest.TestCase):

    def test_config_valida(self):
        cfg, avisos = modelo.validar_config(
            {"version": 1, "ajustes": {"debounce_ms": 200}, "macros": [_macro_ok()]})
        self.assertEqual(avisos, [])
        self.assertEqual(len(cfg.macros), 1)
        self.assertEqual(cfg.ajustes.debounce_ms, 200)
        self.assertEqual(cfg.ajustes.hotkey_panico.nombre, "F12")

    def test_macro_rota_avisa_pero_no_rompe_las_demas(self):
        cfg, avisos = modelo.validar_config(
            {"version": 1, "macros": [{"nombre": "Rota", "accion": {"tipo": "?"}},
                                      _macro_ok()]})
        self.assertEqual(len(cfg.macros), 2)
        self.assertFalse(cfg.macros[0].soportada)
        self.assertTrue(cfg.macros[1].soportada)
        self.assertTrue(avisos)

    def test_ids_duplicados_se_desambiguan(self):
        a, b = _macro_ok(), _macro_ok()
        cfg, _ = modelo.validar_config({"version": 1, "macros": [a, b]})
        self.assertNotEqual(cfg.macros[0].id, cfg.macros[1].id)

    def test_tope_de_macros(self):
        cfg, avisos = modelo.validar_config(
            {"version": 1, "macros": [_macro_ok()] * (modelo.MAX_MACROS + 10)})
        self.assertEqual(len(cfg.macros), modelo.MAX_MACROS)
        self.assertTrue(avisos)

    def test_panico_ilegible_se_restaura(self):
        cfg, avisos = modelo.validar_config(
            {"version": 1, "ajustes": {"hotkey_panico": {"sc": "no"}}, "macros": []})
        self.assertEqual(cfg.ajustes.hotkey_panico.nombre, "F12")
        self.assertTrue(any("pánico" in a for a in avisos))


class IdaYVuelta(unittest.TestCase):

    def _ciclo(self, bruto):
        cfg, _ = modelo.validar_config({"version": 1, "macros": [bruto]})
        vuelta, avisos = modelo.validar_config(modelo.config_a_json(cfg))
        self.assertEqual(avisos, [])
        return cfg.macros[0], vuelta.macros[0]

    def test_mantener(self):
        a, b = self._ciclo(_macro_ok())
        self.assertEqual(a, b)

    def test_clic_auto(self):
        bruto = _macro_ok()
        bruto["accion"] = {"tipo": "CLIC_AUTO",
                           "objetivo": {"tipo": "raton", "boton": "der"},
                           "intervalo_ms": 83, "jitter_intervalo_ms": 12,
                           "duracion_ms": 30, "jitter_duracion_ms": 8,
                           "repeticiones": 0}
        a, b = self._ciclo(bruto)
        self.assertEqual(a, b)

    def test_secuencia(self):
        bruto = _macro_ok()
        bruto["accion"] = {"tipo": "SECUENCIA", "repeticiones": 3,
                           "pasos": [{"op": "tecla_abajo", "vk": 87},
                                     {"op": "esperar", "ms": 500, "jitter_ms": 60},
                                     {"op": "tecla_arriba", "vk": 87},
                                     {"op": "clic", "boton": "izq", "duracion_ms": 30}]}
        a, b = self._ciclo(bruto)
        self.assertEqual(a, b)


class Recursos(unittest.TestCase):

    def test_recursos_de_secuencia(self):
        bruto = _macro_ok()
        bruto["accion"] = {"tipo": "SECUENCIA",
                           "pasos": [{"op": "tecla_abajo", "vk": 87},
                                     {"op": "clic", "boton": "der", "duracion_ms": 30}]}
        m = modelo.validar_macro(bruto)
        self.assertEqual(m.recursos(), {("tecla", 87), ("raton", "der")})

    def test_copia_inmutable_no_comparte_estado(self):
        m = modelo.validar_macro(_macro_ok())
        copia = m.copia_inmutable()
        m.accion.objetivo.boton = "der"
        m.nombre = "otro"
        self.assertEqual(copia.accion.objetivo.boton, "izq")
        self.assertEqual(copia.nombre, "Minar")


if __name__ == "__main__":
    unittest.main()
