# -*- coding: utf-8 -*-
"""Persistencia: `%APPDATA%\\Autoclicker\\config.json` y el registro de errores.

Decisiones que no son obvias:
  * La carpeta se resuelve explícitamente y, si no se puede, se REHÚSA persistir con aviso.
    Nada de caer al directorio actual: en un build `--onedir` ése es el de instalación,
    que puede ser de solo lectura y además es escribible por cualquiera.
  * Escritura atómica: fichero temporal + `os.replace`, con `.bak` de la versión anterior.
  * El guardado se difiere y se agrupa fuera del hilo de Tk: cada `os.replace` lo escanea
    Defender de forma síncrona, y hacer eso dentro del callback de la GUI para el drenaje de
    la cola de eventos.
  * `error.log` rota y NUNCA recibe códigos de tecla: los mensajes de excepciones que
    vengan de `hotkeys.py` se redactan, porque es el único módulo que ve pulsaciones ajenas.
"""

import json
import os
import threading
import time
import traceback

from modelo import VERSION_CONFIG, MAX_BYTES_CONFIG, Config, config_a_json, validar_config
from winapi import carpeta_appdata

NOMBRE_APP = "Autoclicker"
MAX_BYTES_LOG = 1024 * 1024


def carpeta_config():
    """Carpeta de datos, o None si no hay ninguna razonable."""
    base = carpeta_appdata()
    if not base:
        return None
    return os.path.join(base, NOMBRE_APP)


def ruta_config():
    c = carpeta_config()
    return os.path.join(c, "config.json") if c else None


def ruta_log():
    c = carpeta_config()
    return os.path.join(c, "error.log") if c else None


def _asegurar_carpeta():
    c = carpeta_config()
    if not c:
        return None
    try:
        os.makedirs(c, exist_ok=True)
        return c
    except OSError:
        return None


# ------------------------------------------------------------------------------ carga
def migrar(bruto):
    """(bruto, aviso). Una versión más nueva no se toca: se rehúsa y se respalda."""
    if not isinstance(bruto, dict):
        return bruto, None
    version = bruto.get("version", VERSION_CONFIG)
    if not isinstance(version, int) or isinstance(version, bool):
        return bruto, None
    if version > VERSION_CONFIG:
        return None, ("La configuración es de una versión más nueva (%d) que este programa "
                      "(%d). No se toca: se ha guardado una copia y se empieza de cero."
                      % (version, VERSION_CONFIG))
    # De la v1 en adelante, aquí irán las migraciones sucesivas.
    return bruto, None


def leer_json(ruta):
    """(bruto, error). Comprueba el tamaño ANTES de parsear."""
    try:
        if os.path.getsize(ruta) > MAX_BYTES_CONFIG:
            return None, "El fichero de configuración es demasiado grande; se ignora."
    except OSError as exc:
        return None, "No se pudo leer la configuración (%s)." % type(exc).__name__
    try:
        # utf-8-sig, no utf-8: el README invita a editar el fichero a mano y el Bloc de
        # notas guarda con BOM. Sin esto, `json` se planta en el primer carácter.
        with open(ruta, "r", encoding="utf-8-sig") as f:
            return json.load(f), None
    except ValueError:
        return None, "La configuración está corrupta (JSON inválido)."
    except OSError as exc:
        return None, "No se pudo leer la configuración (%s)." % type(exc).__name__


def cargar():
    """(Config, avisos). Nunca lanza: si todo falla, devuelve una configuración vacía."""
    avisos = []
    ruta = ruta_config()
    if not ruta:
        return Config(), ["No se encontró %APPDATA%: los cambios NO se guardarán."]
    if not os.path.exists(ruta):
        return Config(), []

    bruto, error = leer_json(ruta)
    if error:
        avisos.append(error)
        respaldo = ruta + ".bak"
        if os.path.exists(respaldo):
            bruto, error2 = leer_json(respaldo)
            if error2:
                avisos.append("La copia de seguridad tampoco sirve; se empieza de cero.")
                return Config(), avisos
            avisos.append("Se ha recuperado la configuración desde la copia de seguridad.")
        else:
            return Config(), avisos

    bruto, aviso_mig = migrar(bruto)
    if aviso_mig:
        avisos.append(aviso_mig)
        try:
            os.replace(ruta, ruta + ".futuro")
        except OSError:
            pass
        return Config(), avisos

    cfg, avisos_val = validar_config(bruto)
    avisos.extend(avisos_val)
    return cfg, avisos


# ------------------------------------------------------------------------------ guardado
def guardar_json(datos):
    """Escritura atómica. Devuelve None si fue bien, o un texto de error."""
    carpeta = _asegurar_carpeta()
    if not carpeta:
        return "No hay dónde guardar la configuración; los cambios se perderán al salir."
    ruta = os.path.join(carpeta, "config.json")
    tmp = ruta + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(ruta):
            try:
                os.replace(ruta, ruta + ".bak")
            except OSError:
                pass
        os.replace(tmp, ruta)
        return None
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return "No se pudo guardar la configuración (%s)." % type(exc).__name__


def guardar(cfg):
    return guardar_json(config_a_json(cfg))


class GuardadoDiferido(object):
    """Agrupa las escrituras y las saca del hilo de Tk.

    Solo se pide guardar en ediciones del usuario, nunca en transiciones de estado por hotkey:
    si no, cada activación de una macro escribiría en disco.
    """

    def __init__(self, retardo=2.0, al_fallar=None):
        self._retardo = retardo
        self._al_fallar = al_fallar
        self._lock = threading.Lock()
        self._pendiente = None
        self._hilo = None

    def pedir(self, cfg):
        # Serializamos aquí (barato) para no quedarnos con una referencia viva que la UI
        # pueda seguir editando mientras el hilo escribe.
        datos = config_a_json(cfg)
        with self._lock:
            self._pendiente = datos
            if self._hilo is None or not self._hilo.is_alive():
                self._hilo = threading.Thread(target=self._trabajar, name="guardado",
                                              daemon=True)
                self._hilo.start()

    def _trabajar(self):
        time.sleep(self._retardo)
        with self._lock:
            datos = self._pendiente
            self._pendiente = None
        if datos is None:
            return
        error = guardar_json(datos)
        if error and self._al_fallar:
            try:
                self._al_fallar(error)
            except Exception:
                pass

    def vaciar(self):
        """Escribe ya lo que hubiera pendiente. Se llama al cerrar."""
        with self._lock:
            datos = self._pendiente
            self._pendiente = None
        if datos is not None:
            return guardar_json(datos)
        return None


# ------------------------------------------------------------------------------ registro
_ultimo_registro = [None, 0]
_lock_log = threading.Lock()


def _rotar_si_toca(ruta):
    try:
        if os.path.getsize(ruta) > MAX_BYTES_LOG:
            os.replace(ruta, ruta + ".1")
    except OSError:
        pass


def _mensaje_seguro(exc_value, tb):
    """El texto de la excepción, salvo que venga de `hotkeys.py`.

    Ése es el único módulo que ve pulsaciones que no son nuestras. Un `KeyError: (31, 0)`
    escapando de ahí sería exactamente la fuga que hay que evitar, así que se redacta.
    """
    origen_sensible = False
    t = tb
    while t is not None:
        nombre = os.path.basename(t.tb_frame.f_code.co_filename)
        if nombre == "hotkeys.py":
            origen_sensible = True
        t = t.tb_next
    if origen_sensible:
        return "(mensaje omitido: procede del hook de teclado)"
    try:
        return str(exc_value)[:200]
    except Exception:
        return "(mensaje ilegible)"


def registrar_excepcion(tipo, valor, tb, contexto=""):
    """Escribe tipo, mensaje saneado y ubicaciones. Sin código fuente ni variables locales."""
    ruta = ruta_log()
    if not ruta or not _asegurar_carpeta():
        return
    marcos = []
    for f in traceback.extract_tb(tb):
        marcos.append("%s:%d en %s" % (os.path.basename(f.filename), f.lineno, f.name))
    cuerpo = "%s: %s | %s" % (getattr(tipo, "__name__", str(tipo)),
                              _mensaje_seguro(valor, tb), " <- ".join(reversed(marcos)))
    if contexto:
        cuerpo = "[%s] %s" % (contexto, cuerpo)

    with _lock_log:
        if _ultimo_registro[0] == cuerpo:
            _ultimo_registro[1] += 1
            if _ultimo_registro[1] % 50 != 0:
                return          # deduplicado: no llenamos el disco con lo mismo
            cuerpo += "  (x%d)" % _ultimo_registro[1]
        else:
            _ultimo_registro[0] = cuerpo
            _ultimo_registro[1] = 1
        _rotar_si_toca(ruta)
        try:
            with open(ruta, "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), cuerpo))
        except OSError:
            pass
