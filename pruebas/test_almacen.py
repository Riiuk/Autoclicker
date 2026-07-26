# -*- coding: utf-8 -*-
"""Persistencia: escritura atómica, recuperación por .bak, migración y registro."""

import json
import os
import shutil
import tempfile
import unittest

import almacen
import modelo


class ConCarpetaTemporal(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="autoclicker-test-")
        self._original = almacen.carpeta_config
        almacen.carpeta_config = lambda: self.dir

    def tearDown(self):
        almacen.carpeta_config = self._original
        shutil.rmtree(self.dir, ignore_errors=True)

    def escribir(self, nombre, contenido):
        ruta = os.path.join(self.dir, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return ruta


class GuardarYCargar(ConCarpetaTemporal):

    def test_ida_y_vuelta(self):
        cfg = modelo.Config(macros=[modelo.nueva_macro("Minar")])
        cfg.macros[0].hotkey = modelo.Hotkey(sc=66, ext=0, vk=0x77, nombre="F8")
        self.assertIsNone(almacen.guardar(cfg))
        vuelta, avisos = almacen.cargar()
        self.assertEqual(avisos, [])
        self.assertEqual(len(vuelta.macros), 1)
        self.assertEqual(vuelta.macros[0].nombre, "Minar")

    def test_sin_fichero_devuelve_config_vacia(self):
        cfg, avisos = almacen.cargar()
        self.assertEqual(cfg.macros, [])
        self.assertEqual(avisos, [])

    def test_deja_bak_al_reescribir(self):
        cfg = modelo.Config()
        almacen.guardar(cfg)
        cfg.macros.append(modelo.nueva_macro("Otra"))
        cfg.macros[0].hotkey = modelo.Hotkey(sc=66, ext=0, vk=0x77)
        almacen.guardar(cfg)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "config.json.bak")))

    def test_una_macro_no_soportada_sobrevive_en_disco(self):
        """El caso real: alguien vuelve a una versión anterior, o se equivoca editando el
        fichero a mano, y luego toca cualquier otra cosa en la interfaz."""
        futura = {"id": "futura", "nombre": "Rueda", "habilitada": True,
                  "hotkey": {"sc": 88, "ext": 0, "vk": 123},
                  "accion": {"tipo": "RUEDA_DEL_RATON", "vueltas": 3}}
        buena = {"id": "buena", "nombre": "Minar", "habilitada": True,
                 "hotkey": {"sc": 66, "ext": 0, "vk": 119},
                 "accion": {"tipo": "MANTENER",
                            "objetivo": {"tipo": "raton", "boton": "izq"}}}
        self.escribir("config.json", json.dumps({"version": 1,
                                                 "macros": [futura, buena]}))

        cfg, avisos = almacen.cargar()
        self.assertTrue(any("Rueda" in a for a in avisos))
        cfg.macros[1].nombre = "Minar más"
        self.assertIsNone(almacen.guardar(cfg))

        vuelta, _ = almacen.cargar()
        self.assertEqual([m.nombre for m in vuelta.macros], ["Rueda", "Minar más"])
        self.assertEqual(vuelta.macros[0].accion.tipo, modelo.TIPO_MANTENER)  # sin interpretar
        self.assertFalse(vuelta.macros[0].soportada)
        with open(os.path.join(self.dir, "config.json"), encoding="utf-8") as f:
            self.assertIn("RUEDA_DEL_RATON", f.read())

    def test_no_deja_temporales(self):
        almacen.guardar(modelo.Config())
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".tmp")], [])

    def test_json_corrupto_recupera_del_bak(self):
        cfg = modelo.Config(macros=[modelo.nueva_macro("Buena")])
        cfg.macros[0].hotkey = modelo.Hotkey(sc=66, ext=0, vk=0x77)
        almacen.guardar(cfg)
        shutil.copy(os.path.join(self.dir, "config.json"),
                    os.path.join(self.dir, "config.json.bak"))
        self.escribir("config.json", "{esto no es json")
        vuelta, avisos = almacen.cargar()
        self.assertEqual(len(vuelta.macros), 1)
        self.assertTrue(any("copia de seguridad" in a for a in avisos))

    def test_corrupto_sin_bak_no_revienta(self):
        self.escribir("config.json", "\x00\x01basura binaria")
        cfg, avisos = almacen.cargar()
        self.assertEqual(cfg.macros, [])
        self.assertTrue(avisos)

    def test_acepta_bom(self):
        """El README invita a editar el fichero a mano y el Bloc de notas guarda con BOM."""
        cfg = modelo.Config(macros=[modelo.nueva_macro("Con BOM")])
        cfg.macros[0].hotkey = modelo.Hotkey(sc=66, ext=0, vk=0x77)
        almacen.guardar(cfg)
        ruta = os.path.join(self.dir, "config.json")
        with open(ruta, "rb") as f:
            crudo = f.read()
        with open(ruta, "wb") as f:
            f.write(b"\xef\xbb\xbf" + crudo)
        vuelta, avisos = almacen.cargar()
        self.assertEqual(avisos, [])
        self.assertEqual(len(vuelta.macros), 1)
        self.assertEqual(vuelta.macros[0].nombre, "Con BOM")

    def test_fichero_gigante_se_rechaza_antes_de_parsear(self):
        self.escribir("config.json", "[" + ("0," * (modelo.MAX_BYTES_CONFIG // 2)) + "0]")
        cfg, avisos = almacen.cargar()
        self.assertEqual(cfg.macros, [])
        self.assertTrue(any("grande" in a for a in avisos))


class Migracion(ConCarpetaTemporal):

    def test_version_futura_se_rehusa_y_se_respalda(self):
        self.escribir("config.json", json.dumps({"version": 99, "macros": []}))
        cfg, avisos = almacen.cargar()
        self.assertEqual(cfg.macros, [])
        self.assertTrue(any("más nueva" in a for a in avisos))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "config.json.futuro")))

    def test_version_ilegible_se_asume_la_actual(self):
        self.escribir("config.json", json.dumps({"version": "dos", "macros": []}))
        cfg, avisos = almacen.cargar()
        self.assertTrue(any("Versión" in a for a in avisos))


class Registro(ConCarpetaTemporal):

    def setUp(self):
        ConCarpetaTemporal.setUp(self)
        # El deduplicador es estado de módulo: si no se limpia, una prueba se come
        # el registro de la siguiente.
        almacen._ultimo_registro[0] = None
        almacen._ultimo_registro[1] = 0

    def _provocar(self):
        try:
            raise KeyError((31, 0))     # simula una fuga de código de tecla
        except KeyError:
            import sys
            tipo, valor, tb = sys.exc_info()
            almacen.registrar_excepcion(tipo, valor, tb, "prueba")

    def test_escribe_tipo_y_ubicacion(self):
        self._provocar()
        with open(os.path.join(self.dir, "error.log"), encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("KeyError", texto)
        self.assertIn("test_almacen.py", texto)

    def test_redacta_lo_que_venga_del_hook(self):
        """El texto de una excepción nacida en hotkeys.py podría llevar un código de
        tecla ajena. Se omite el mensaje, se conserva el tipo."""
        import sys
        codigo = compile("raise KeyError((31, 0))", "C:\\x\\hotkeys.py", "exec")
        try:
            exec(codigo, {})
        except KeyError:
            tipo, valor, tb = sys.exc_info()
            almacen.registrar_excepcion(tipo, valor, tb, "hook")
        with open(os.path.join(self.dir, "error.log"), encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("KeyError", texto)
        self.assertIn("mensaje omitido", texto)
        self.assertNotIn("31", texto.split("|")[0])

    def test_deduplica(self):
        for _ in range(10):
            self._provocar()
        with open(os.path.join(self.dir, "error.log"), encoding="utf-8") as f:
            self.assertEqual(len(f.readlines()), 1)

    def test_rota_al_crecer(self):
        ruta = os.path.join(self.dir, "error.log")
        self.escribir("error.log", "x" * (almacen.MAX_BYTES_LOG + 10))
        almacen._ultimo_registro[0] = None
        self._provocar()
        self.assertTrue(os.path.exists(ruta + ".1"))
        self.assertLess(os.path.getsize(ruta), 1000)


class Diferido(ConCarpetaTemporal):

    def test_agrupa_y_escribe_al_vaciar(self):
        g = almacen.GuardadoDiferido(retardo=60.0)
        cfg = modelo.Config()
        g.pedir(cfg)
        cfg.macros.append(modelo.nueva_macro("Tardía"))
        cfg.macros[0].hotkey = modelo.Hotkey(sc=66, ext=0, vk=0x77)
        g.pedir(cfg)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")))
        self.assertIsNone(g.vaciar())
        vuelta, _ = almacen.cargar()
        self.assertEqual(len(vuelta.macros), 1)


if __name__ == "__main__":
    unittest.main()
