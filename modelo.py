# -*- coding: utf-8 -*-
"""Modelo de datos y VALIDADOR ÚNICO.

`config.json` es entrada NO confiable: se edita a mano a propósito y el menú Archivo permite
importar cualquier fichero. Un `vk` fuera de rango va derecho a un `WORD` de `SendInput`, y un
`{"op":"esperar","ms":999999999}` deja el motor aparcado con teclas pulsadas.

Reglas del validador:
  * Todos los caminos de carga (disco, .bak, importar) pasan por `validar_config()`.
  * NUNCA lanza. Lo que no cuadra se degrada a `soportada=False` con un motivo legible.
  * Tipo y rango explícitos en cada campo; nada se cuela por ser "casi" válido.

Vocabulario: claves y valores del JSON en español, salvo los tres tipos de acción, que
van en mayúsculas por ser constantes del dominio.
"""

import copy
import uuid
from dataclasses import dataclass, field

from winapi import BOTONES_VALIDOS

VERSION_CONFIG = 1

TIPO_MANTENER = "MANTENER"
TIPO_CLIC_AUTO = "CLIC_AUTO"
TIPO_SECUENCIA = "SECUENCIA"
TIPOS_ACCION = (TIPO_MANTENER, TIPO_CLIC_AUTO, TIPO_SECUENCIA)

ETIQUETAS_TIPO = {
    TIPO_MANTENER: "Mantener pulsado",
    TIPO_CLIC_AUTO: "Clic automático",
    TIPO_SECUENCIA: "Secuencia de pasos",
}

OP_TECLA_ABAJO = "tecla_abajo"
OP_TECLA_ARRIBA = "tecla_arriba"
OP_CLIC = "clic"
OP_ESPERAR = "esperar"
OPS = (OP_TECLA_ABAJO, OP_TECLA_ARRIBA, OP_CLIC, OP_ESPERAR)

MODOS = ("toggle", "pulso")

# Topes. Existen para que un fichero hostil o un dedazo no puedan aparcar el motor ni
# reventar la memoria.
MAX_BYTES_CONFIG = 1024 * 1024
MAX_MACROS = 200
MAX_PASOS = 200
MAX_MS = 3600000            # 1 hora
MAX_REPETICIONES = 1000000
MAX_AUTO_SOLTAR_MIN = 720   # 12 h
MIN_DURACION_MS = 15        # por debajo, muchos juegos ni ven la pulsación
HOLGURA_INTERVALO_MS = 5    # el intervalo debe dejar respirar a la duración


@dataclass
class Hotkey:
    sc: int = 0
    ext: int = 0
    vk: int = 0
    mods: int = 0
    nombre: str = ""
    modo: str = "toggle"
    tragar_tecla: bool = False

    @property
    def clave(self):
        """Identidad canónica: la posición física de la tecla."""
        return (self.sc, self.ext)

    def asignada(self):
        return self.sc != 0 or self.ext != 0


@dataclass
class Objetivo:
    tipo: str = "raton"        # raton | tecla
    boton: str = "izq"
    vk: int = 0

    def recurso(self):
        return ("raton", self.boton) if self.tipo == "raton" else ("tecla", self.vk)


@dataclass
class Paso:
    op: str = OP_ESPERAR
    vk: int = 0
    boton: str = "izq"
    ms: int = 100
    jitter_ms: int = 0
    duracion_ms: int = 30


@dataclass
class Accion:
    tipo: str = TIPO_MANTENER
    objetivo: Objetivo = field(default_factory=Objetivo)
    intervalo_ms: int = 100
    jitter_intervalo_ms: int = 0
    duracion_ms: int = 30
    jitter_duracion_ms: int = 0
    repeticiones: int = 0
    pasos: list = field(default_factory=list)


@dataclass
class Macro:
    id: str = ""
    nombre: str = "Macro"
    habilitada: bool = True
    hotkey: Hotkey = field(default_factory=Hotkey)
    accion: Accion = field(default_factory=Accion)
    auto_soltar_min: int = 0
    retardo_inicial_ms: int = 0
    soportada: bool = True
    motivo: str = ""

    def recursos(self):
        """Recursos físicos que esta macro va a ocupar. Lo usa el árbitro."""
        r = set()
        a = self.accion
        if a.tipo in (TIPO_MANTENER, TIPO_CLIC_AUTO):
            r.add(a.objetivo.recurso())
        else:
            for p in a.pasos:
                if p.op in (OP_TECLA_ABAJO, OP_TECLA_ARRIBA):
                    r.add(("tecla", p.vk))
                elif p.op == OP_CLIC:
                    r.add(("raton", p.boton))
        return r

    def copia_inmutable(self):
        """Copia profunda para que el motor no vea ediciones a medias desde la UI."""
        return copy.deepcopy(self)


@dataclass
class Ajustes:
    hotkey_panico: Hotkey = field(
        default_factory=lambda: Hotkey(sc=88, ext=0, vk=0x7B, nombre="F12"))
    debounce_ms: int = 150
    seguir_foco: bool = True
    sonidos: bool = True
    indicador: bool = True


@dataclass
class Config:
    version: int = VERSION_CONFIG
    ajustes: Ajustes = field(default_factory=Ajustes)
    macros: list = field(default_factory=list)

    def por_id(self, id_macro):
        for m in self.macros:
            if m.id == id_macro:
                return m
        return None


# --------------------------------------------------------------------------- validación
def _entero(bruto, campo, minimo, maximo, defecto):
    """Entero estricto: `True` no cuela como 1, ni "5" como 5."""
    v = bruto.get(campo, defecto)
    if isinstance(v, bool) or not isinstance(v, int):
        return defecto, "«%s» debe ser un número entero" % campo
    if v < minimo or v > maximo:
        return defecto, "«%s» fuera de rango (%d..%d)" % (campo, minimo, maximo)
    return v, None


def _booleano(bruto, campo, defecto):
    v = bruto.get(campo, defecto)
    return (v if isinstance(v, bool) else defecto)


def _texto(bruto, campo, defecto, tope=120):
    v = bruto.get(campo, defecto)
    if not isinstance(v, str):
        return defecto
    return v[:tope]


def _validar_hotkey(bruto, fallos):
    hk = Hotkey()
    if not isinstance(bruto, dict):
        fallos.append("la hotkey no es un objeto")
        return hk
    hk.sc, e = _entero(bruto, "sc", 0, 255, 0)
    if e:
        fallos.append(e)
    hk.ext, e = _entero(bruto, "ext", 0, 1, 0)
    if e:
        fallos.append(e)
    hk.vk, e = _entero(bruto, "vk", 0, 254, 0)
    if e:
        fallos.append(e)
    hk.mods, e = _entero(bruto, "mods", 0, 7, 0)
    if e:
        fallos.append(e)
    hk.nombre = _texto(bruto, "nombre", "", 40)
    modo = _texto(bruto, "modo", "toggle", 10)
    if modo not in MODOS:
        fallos.append("modo de hotkey desconocido: %r" % modo)
        modo = "toggle"
    hk.modo = modo
    hk.tragar_tecla = _booleano(bruto, "tragar_tecla", False)
    return hk


def _validar_objetivo(bruto, fallos):
    o = Objetivo()
    if not isinstance(bruto, dict):
        fallos.append("el objetivo no es un objeto")
        return o
    tipo = _texto(bruto, "tipo", "raton", 10)
    if tipo not in ("raton", "tecla"):
        fallos.append("tipo de objetivo desconocido: %r" % tipo)
        return o
    o.tipo = tipo
    if tipo == "raton":
        boton = _texto(bruto, "boton", "izq", 10)
        if boton not in BOTONES_VALIDOS:
            fallos.append("botón desconocido: %r" % boton)
            boton = "izq"
        o.boton = boton
    else:
        o.vk, e = _entero(bruto, "vk", 1, 254, 0)
        if e or not o.vk:
            fallos.append(e or "falta el «vk» del objetivo")
    return o


def _validar_paso(bruto, fallos):
    if not isinstance(bruto, dict):
        fallos.append("un paso no es un objeto")
        return None
    op = _texto(bruto, "op", "", 20)
    if op not in OPS:
        fallos.append("operación de paso desconocida: %r" % op)
        return None
    p = Paso(op=op)
    if op in (OP_TECLA_ABAJO, OP_TECLA_ARRIBA):
        p.vk, e = _entero(bruto, "vk", 1, 254, 0)
        if e or not p.vk:
            fallos.append(e or "falta el «vk» de un paso de tecla")
            return None
    elif op == OP_CLIC:
        boton = _texto(bruto, "boton", "izq", 10)
        if boton not in BOTONES_VALIDOS:
            fallos.append("botón desconocido en un paso: %r" % boton)
            return None
        p.boton = boton
        p.duracion_ms, e = _entero(bruto, "duracion_ms", MIN_DURACION_MS, MAX_MS, 30)
        if e:
            fallos.append(e)
    else:  # esperar
        p.ms, e = _entero(bruto, "ms", 0, MAX_MS, 100)
        if e:
            fallos.append(e)
        p.jitter_ms, e = _entero(bruto, "jitter_ms", 0, MAX_MS, 0)
        if e:
            fallos.append(e)
    return p


def _validar_accion(bruto, fallos):
    a = Accion()
    if not isinstance(bruto, dict):
        fallos.append("la acción no es un objeto")
        return a
    tipo = _texto(bruto, "tipo", "", 20)
    if tipo not in TIPOS_ACCION:
        fallos.append("tipo de acción desconocido: %r" % tipo)
        return a
    a.tipo = tipo

    if tipo in (TIPO_MANTENER, TIPO_CLIC_AUTO):
        a.objetivo = _validar_objetivo(bruto.get("objetivo"), fallos)

    if tipo == TIPO_CLIC_AUTO:
        a.duracion_ms, e = _entero(bruto, "duracion_ms", MIN_DURACION_MS, MAX_MS, 30)
        if e:
            fallos.append(e)
        a.jitter_duracion_ms, e = _entero(bruto, "jitter_duracion_ms", 0, MAX_MS, 0)
        if e:
            fallos.append(e)
        a.intervalo_ms, e = _entero(bruto, "intervalo_ms", 1, MAX_MS, 100)
        if e:
            fallos.append(e)
        a.jitter_intervalo_ms, e = _entero(bruto, "jitter_intervalo_ms", 0, MAX_MS, 0)
        if e:
            fallos.append(e)
        minimo = a.duracion_ms + HOLGURA_INTERVALO_MS
        if a.intervalo_ms < minimo:
            a.intervalo_ms = minimo   # regla dura: el intervalo no puede comerse la duración
        a.repeticiones, e = _entero(bruto, "repeticiones", 0, MAX_REPETICIONES, 0)
        if e:
            fallos.append(e)

    if tipo == TIPO_SECUENCIA:
        pasos = bruto.get("pasos")
        if not isinstance(pasos, list) or not pasos:
            fallos.append("la secuencia no tiene pasos")
            return a
        if len(pasos) > MAX_PASOS:
            fallos.append("la secuencia tiene más de %d pasos" % MAX_PASOS)
            return a
        limpios = []
        for p in pasos:
            v = _validar_paso(p, fallos)
            if v is None:
                return a
            limpios.append(v)
        a.pasos = limpios
        a.repeticiones, e = _entero(bruto, "repeticiones", 0, MAX_REPETICIONES, 0)
        if e:
            fallos.append(e)
    return a


def validar_macro(bruto):
    """Devuelve una `Macro` SIEMPRE. Si algo falla, viene con `soportada=False` y motivo."""
    fallos = []
    m = Macro()
    if not isinstance(bruto, dict):
        m.soportada = False
        m.motivo = "la macro no es un objeto"
        m.habilitada = False
        m.id = uuid.uuid4().hex[:8]
        return m
    m.id = _texto(bruto, "id", "", 40) or uuid.uuid4().hex[:8]
    m.nombre = _texto(bruto, "nombre", "Macro sin nombre") or "Macro sin nombre"
    m.habilitada = _booleano(bruto, "habilitada", True)
    m.hotkey = _validar_hotkey(bruto.get("hotkey"), fallos)
    m.accion = _validar_accion(bruto.get("accion"), fallos)
    m.auto_soltar_min, e = _entero(bruto, "auto_soltar_min", 0, MAX_AUTO_SOLTAR_MIN, 0)
    if e:
        fallos.append(e)
    m.retardo_inicial_ms, e = _entero(bruto, "retardo_inicial_ms", 0, MAX_MS, 0)
    if e:
        fallos.append(e)

    if not m.hotkey.asignada():
        fallos.append("no tiene tecla asignada")
    if fallos:
        m.soportada = False
        m.habilitada = False
        m.motivo = "; ".join(fallos[:3])
    return m


def validar_config(bruto):
    """(Config, avisos). Nunca lanza. `avisos` es texto para la barra de estado."""
    avisos = []
    cfg = Config()
    if not isinstance(bruto, dict):
        return cfg, ["El fichero de configuración no es válido; se empieza de cero."]

    version = bruto.get("version", VERSION_CONFIG)
    if isinstance(version, int) and not isinstance(version, bool):
        cfg.version = version
    else:
        avisos.append("Versión de configuración ilegible; se asume la %d." % VERSION_CONFIG)
        cfg.version = VERSION_CONFIG

    aj = bruto.get("ajustes")
    if isinstance(aj, dict):
        if "hotkey_panico" in aj:
            # Solo se avisa si venía y era ilegible; que falte es normal (se usa F12).
            fallos_aj = []
            panico = _validar_hotkey(aj.get("hotkey_panico"), fallos_aj)
            if fallos_aj or not panico.asignada():
                avisos.append("Tecla de pánico ilegible; se restaura F12.")
            else:
                cfg.ajustes.hotkey_panico = panico
        cfg.ajustes.debounce_ms, e = _entero(aj, "debounce_ms", 0, 5000, 150)
        if e:
            avisos.append(e)
        cfg.ajustes.seguir_foco = _booleano(aj, "seguir_foco", True)
        cfg.ajustes.sonidos = _booleano(aj, "sonidos", True)
        cfg.ajustes.indicador = _booleano(aj, "indicador", True)

    macros = bruto.get("macros")
    if isinstance(macros, list):
        if len(macros) > MAX_MACROS:
            avisos.append("Había más de %d macros; se cargan las primeras." % MAX_MACROS)
            macros = macros[:MAX_MACROS]
        vistos = set()
        for b in macros:
            m = validar_macro(b)
            while m.id in vistos:
                m.id = uuid.uuid4().hex[:8]
            vistos.add(m.id)
            if not m.soportada:
                avisos.append("«%s» se ha deshabilitado: %s" % (m.nombre, m.motivo))
            cfg.macros.append(m)
    return cfg, avisos


# --------------------------------------------------------------------------- serialización
def hotkey_a_json(hk):
    return {"sc": hk.sc, "ext": hk.ext, "vk": hk.vk, "mods": hk.mods,
            "nombre": hk.nombre, "modo": hk.modo, "tragar_tecla": hk.tragar_tecla}


def accion_a_json(a):
    d = {"tipo": a.tipo}
    if a.tipo in (TIPO_MANTENER, TIPO_CLIC_AUTO):
        o = a.objetivo
        d["objetivo"] = ({"tipo": "raton", "boton": o.boton} if o.tipo == "raton"
                         else {"tipo": "tecla", "vk": o.vk})
    if a.tipo == TIPO_CLIC_AUTO:
        d.update({"intervalo_ms": a.intervalo_ms,
                  "jitter_intervalo_ms": a.jitter_intervalo_ms,
                  "duracion_ms": a.duracion_ms,
                  "jitter_duracion_ms": a.jitter_duracion_ms,
                  "repeticiones": a.repeticiones})
    if a.tipo == TIPO_SECUENCIA:
        d["repeticiones"] = a.repeticiones
        d["pasos"] = [paso_a_json(p) for p in a.pasos]
    return d


def paso_a_json(p):
    if p.op in (OP_TECLA_ABAJO, OP_TECLA_ARRIBA):
        return {"op": p.op, "vk": p.vk}
    if p.op == OP_CLIC:
        return {"op": p.op, "boton": p.boton, "duracion_ms": p.duracion_ms}
    return {"op": p.op, "ms": p.ms, "jitter_ms": p.jitter_ms}


def macro_a_json(m):
    return {"id": m.id, "nombre": m.nombre, "habilitada": m.habilitada,
            "hotkey": hotkey_a_json(m.hotkey), "accion": accion_a_json(m.accion),
            "auto_soltar_min": m.auto_soltar_min,
            "retardo_inicial_ms": m.retardo_inicial_ms}


def config_a_json(cfg):
    aj = cfg.ajustes
    return {"version": VERSION_CONFIG,
            "ajustes": {"hotkey_panico": hotkey_a_json(aj.hotkey_panico),
                        "debounce_ms": aj.debounce_ms,
                        "seguir_foco": aj.seguir_foco,
                        "sonidos": aj.sonidos,
                        "indicador": aj.indicador},
            "macros": [macro_a_json(m) for m in cfg.macros if m.soportada]}


def nueva_macro(nombre="Macro nueva"):
    return Macro(id=uuid.uuid4().hex[:8], nombre=nombre)
