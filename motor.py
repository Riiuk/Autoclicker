# -*- coding: utf-8 -*-
"""Motor de macros: un solo hilo, un solo emisor, un solo dueño del estado pulsado.

========================== INVARIANTE PRINCIPAL — NO LO ROMPAS ==========================
`EstadoPulsado` es el ÚNICO que sabe qué está físicamente pulsado, y solo se muta desde este
hilo. Las nueve rutas capaces de soltar o pulsar pasan por él:

  1. el `finally` del bucle             6. `release_all()` al arrancar
  2. `atexit`                           7. el dead-man switch
  3. `sys`/`threading.excepthook`       8. el interruptor maestro
  4. cierre de la ventana               9. "Probar 3 s"
  5. la tecla de pánico

Y una décima que NO es una capa de suelta sino de REPULSA: el vigilante de foco. Al volver de
un alt-tab repulsa **solo lo que `debe_estar_pulsado()` siga devolviendo**. Si el pánico saltó
mientras el juego estaba en segundo plano, volver al juego no debe pulsar nada.
=========================================================================================

El scheduler es cooperativo: cada macro es un generador que hace `yield <segundos>`. Los
vencimientos son absolutos para que no se acumule deriva. Las tareas periódicas (foco cada
150 ms, sonda del hook cada 2 s, dead-man) son generadores más, no hilos aparte: así el
recuento de hilos del proceso se queda en tres honestos y sigue habiendo un único emisor.
"""

import collections
import random
import sys
import threading

import winapi
from modelo import (OP_CLIC, OP_ESPERAR, OP_TECLA_ABAJO, OP_TECLA_ARRIBA, TIPO_CLIC_AUTO,
                    TIPO_MANTENER)

PERIODO_FOCO = 0.15
PERIODO_SONDA = 2.0
PERIODO_VIGILANCIA = 1.0
ESPERA_MAXIMA = 0.25        # el bucle nunca duerme más: el pánico entra como muy tarde aquí
AVISO_AUTO_SOLTAR = 10.0    # segundos de cortesía antes de que salte el dead-man


def instalar_redes_de_seguridad(motor):
    """Capas 2 y 3 de las nueve: `atexit` y los dos excepthooks.

    Un UP sin su DOWN es inocuo, así que estas rutas pueden dispararse de más sin daño. Lo
    que no se puede es que el proceso muera dejando el botón izquierdo pulsado a nivel de
    sistema: a partir de ahí el escritorio queda inutilizable.
    """
    import atexit

    atexit.register(motor.emergencia)

    anterior_sys = sys.excepthook

    def _sys(tipo, valor, tb):
        motor.emergencia()
        try:
            import almacen
            almacen.registrar_excepcion(tipo, valor, tb, "principal")
        except Exception:
            pass
        anterior_sys(tipo, valor, tb)

    sys.excepthook = _sys

    if hasattr(threading, "excepthook"):
        anterior_hilo = threading.excepthook

        def _hilo(args):
            motor.emergencia()
            try:
                import almacen
                almacen.registrar_excepcion(args.exc_type, args.exc_value,
                                            args.exc_traceback, "hilo")
            except Exception:
                pass
            anterior_hilo(args)

        threading.excepthook = _hilo


class EstadoPulsado(object):
    """Dueño único de lo que está físicamente pulsado."""

    def __init__(self, inyector):
        self._iny = inyector
        self._deseado_botones = {}    # boton -> id_macro
        self._deseado_teclas = {}     # vk -> id_macro
        self._fisico_botones = set()
        self._fisico_teclas = set()
        self.inhibido = False         # True mientras el juego no está en primer plano

    # --- pulsar / soltar ---
    def pulsar_boton(self, boton, duenyo):
        self._deseado_botones[boton] = duenyo
        if not self.inhibido and boton not in self._fisico_botones:
            self._fisico_botones.add(boton)
            self._iny.raton_abajo(boton)

    def soltar_boton(self, boton):
        self._deseado_botones.pop(boton, None)
        if boton in self._fisico_botones:
            self._fisico_botones.discard(boton)
            self._iny.raton_arriba(boton)

    def pulsar_tecla(self, vk, duenyo):
        self._deseado_teclas[vk] = duenyo
        if not self.inhibido and vk not in self._fisico_teclas:
            self._fisico_teclas.add(vk)
            self._iny.tecla_abajo(vk)

    def soltar_tecla(self, vk):
        self._deseado_teclas.pop(vk, None)
        if vk in self._fisico_teclas:
            self._fisico_teclas.discard(vk)
            self._iny.tecla_arriba(vk)

    # --- consultas ---
    def debe_estar_pulsado(self):
        return (set(self._deseado_botones), set(self._deseado_teclas))

    def hay_algo_pulsado(self):
        return bool(self._fisico_botones or self._fisico_teclas)

    def teclas_deseadas(self):
        return list(self._deseado_teclas)

    # --- transiciones ---
    def inhibir(self):
        """Alt-tab fuera: suelta lo físico, conserva lo deseado."""
        if self.inhibido:
            return
        self.inhibido = True
        for b in list(self._fisico_botones):
            self._iny.raton_arriba(b)
        self._fisico_botones.clear()
        for vk in list(self._fisico_teclas):
            self._iny.tecla_arriba(vk)
        self._fisico_teclas.clear()

    def restaurar(self):
        """Alt-tab dentro: repulsa SOLO lo que siga deseado."""
        if not self.inhibido:
            return
        self.inhibido = False
        for b in list(self._deseado_botones):
            self._fisico_botones.add(b)
            self._iny.raton_abajo(b)
        for vk in list(self._deseado_teclas):
            self._fisico_teclas.add(vk)
            self._iny.tecla_abajo(vk)

    def soltar_de(self, duenyo):
        for b in [k for k, v in self._deseado_botones.items() if v == duenyo]:
            self.soltar_boton(b)
        for vk in [k for k, v in self._deseado_teclas.items() if v == duenyo]:
            self.soltar_tecla(vk)

    def soltar_todo(self):
        """Pánico y cierre: se va lo deseado Y lo físico."""
        self._deseado_botones.clear()
        self._deseado_teclas.clear()
        self.inhibido = False
        for b in list(self._fisico_botones):
            self._iny.raton_arriba(b)
        self._fisico_botones.clear()
        for vk in list(self._fisico_teclas):
            self._iny.tecla_arriba(vk)
        self._fisico_teclas.clear()


class Arbitro(object):
    """Tabla de propietarios por recurso físico.

    Un MANTENER y un CLIC_AUTO sobre el botón izquierdo se pisan: el UP del segundo suelta el
    DOWN del primero y el primero ni se entera. Se rechaza el segundo y se dice quién manda.
    """

    def __init__(self):
        self._duenyo = {}

    def reservar(self, id_macro, recursos):
        for r in recursos:
            otro = self._duenyo.get(r)
            if otro is not None and otro != id_macro:
                return False, otro
        for r in recursos:
            self._duenyo[r] = id_macro
        return True, None

    def liberar(self, id_macro):
        for r in [k for k, v in self._duenyo.items() if v == id_macro]:
            del self._duenyo[r]

    def limpiar(self):
        self._duenyo.clear()


class Tarea(object):
    __slots__ = ("gen", "vencimiento", "id_macro", "inicio", "avisado")

    def __init__(self, gen, vencimiento, id_macro, inicio):
        self.gen = gen
        self.vencimiento = vencimiento
        self.id_macro = id_macro
        self.inicio = inicio
        self.avisado = False


class Motor(object):
    """Firma `Motor(inyector, reloj)` a propósito: las dos costuras que hacen que esto se
    pueda probar sin GPU, sin juego y sin ratón real."""

    def __init__(self, inyector, reloj, notificar=None):
        self._iny = inyector
        self._reloj = reloj
        self._notificar = notificar or (lambda tipo, texto: None)
        self.estado = EstadoPulsado(inyector)
        self.arbitro = Arbitro()

        self._macros = {}            # id -> Macro (copias inmutables)
        self._tareas = {}            # id_macro -> Tarea (None como id = tarea periódica)
        self._periodicas = []
        self._ultimo_disparo = {}    # id -> instante, para el debounce
        self._debounce = 0.15
        self._seguir_foco = True

        self._comandos = collections.deque()
        self._panico_pedido = threading.Event()
        self._parar_pedido = threading.Event()
        self._hilo = None
        self._maestro = True
        self._hwnd_objetivo = None
        self._hook = None
        self._sondas_perdidas = 0
        self._sonda_lanzada = False
        self._fin_prueba = None

    # ------------------------------------------------------------------ API pública
    def preparar(self):
        """Deja el motor listo SIN arrancar el hilo. Las pruebas se quedan aquí y usan
        `tick()` con un reloj falso; la aplicación llama a `arrancar()`."""
        ahora = self._reloj.ahora()
        self._periodicas = [Tarea(self._gen_foco(), ahora, None, ahora),
                            Tarea(self._gen_sonda(), ahora, None, ahora),
                            Tarea(self._gen_vigilancia(), ahora, None, ahora)]

    def tick(self, ahora=None):
        """Un ciclo del bucle. Devuelve el instante del próximo vencimiento."""
        ahora = self._reloj.ahora() if ahora is None else ahora
        self._procesar_comandos()
        if self._panico_pedido.is_set():
            self._panico_pedido.clear()
            self._hacer_panico()
        return self._avanzar(ahora)

    def arrancar(self):
        self.preparar()
        self._hilo = threading.Thread(target=self._bucle, name="motor", daemon=True)
        self._hilo.start()

    def parar(self, timeout=2.0):
        self._parar_pedido.set()
        self._reloj.despertar()
        if self._hilo:
            self._hilo.join(timeout)

    def vigilar_hook(self, hilo_hook):
        self._hook = hilo_hook

    def aplicar_config(self, cfg):
        self._encolar(("config", cfg))

    def comando_hotkey(self, id_macro, abajo):
        """Lo llama el callback del hook. Tiene que ser O(1) y no bloquear jamás."""
        self._comandos.append(("hotkey", id_macro, abajo))
        self._reloj.despertar()

    def panico(self):
        """Lo llama el callback del hook. Aquí SOLO se marca; nada de inyectar ni de E/S."""
        self._panico_pedido.set()
        self._reloj.despertar()

    def activar_maestro(self, activo):
        self._encolar(("maestro", activo))

    def parar_todas(self):
        self._encolar(("parar_todas",))

    def probar(self, macro, segundos=3.0):
        self._encolar(("probar", macro, segundos))

    def estado_macros(self):
        """{id: True/False} — si está corriendo. Solo lectura, para la UI."""
        return dict((i, i in self._tareas) for i in self._macros)

    def emergencia(self):
        """Suelta todo YA, aunque el hilo motor esté muerto o colgado.

        Es el único punto donde se admite emitir desde otro hilo: al llegar aquí, dejar el
        botón izquierdo pulsado a nivel de sistema es peor que romper el invariante.
        """
        self._panico_pedido.set()
        try:
            self._reloj.despertar()
        except Exception:
            pass
        winapi.soltar_todo_ciego(self._iny, self.estado.teclas_deseadas())

    # ------------------------------------------------------------------ bucle
    def _encolar(self, cmd):
        self._comandos.append(cmd)
        self._reloj.despertar()

    def _bucle(self):
        try:
            while not self._parar_pedido.is_set():
                ahora = self._reloj.ahora()
                proximo = self.tick(ahora)
                self._reloj.esperar_hasta(min(proximo, ahora + ESPERA_MAXIMA))
        except BaseException:
            self._registrar(sys.exc_info(), "motor")
            raise
        finally:
            # Capa 1 de las nueve: pase lo que pase, aquí se suelta todo.
            self.estado.soltar_todo()

    def _paso(self, tarea, ahora):
        """Avanza una tarea si le toca. Devuelve su próximo vencimiento, o None si terminó."""
        if tarea.vencimiento > ahora:
            return tarea.vencimiento
        try:
            dt = next(tarea.gen)
        except StopIteration:
            return None
        except Exception:
            self._registrar(sys.exc_info(), "generador")
            return None
        dt = 0.0005 if dt is None or dt < 0.0005 else float(dt)
        tarea.vencimiento += dt
        if tarea.vencimiento < ahora:
            tarea.vencimiento = ahora + dt   # nos quedamos atrás: no acumular deuda
        return tarea.vencimiento

    def _avanzar(self, ahora):
        proximo = ahora + ESPERA_MAXIMA
        for tarea in list(self._tareas.values()):
            v = self._paso(tarea, ahora)
            if v is None:
                self._terminar(tarea.id_macro)
            else:
                proximo = min(proximo, v)
        for tarea in list(self._periodicas):
            v = self._paso(tarea, ahora)
            if v is None:
                # No debería ocurrir nunca; si ocurre, se retira para no girar en vacío.
                self._periodicas.remove(tarea)
            else:
                proximo = min(proximo, v)
        return proximo

    def _procesar_comandos(self):
        while True:
            try:
                cmd = self._comandos.popleft()
            except IndexError:
                return
            try:
                self._ejecutar_comando(cmd)
            except Exception:
                self._registrar(sys.exc_info(), "comando")

    def _ejecutar_comando(self, cmd):
        tipo = cmd[0]
        if tipo == "hotkey":
            self._al_pulsar_hotkey(cmd[1], cmd[2])
        elif tipo == "config":
            self._aplicar_config(cmd[1])
        elif tipo == "maestro":
            self._maestro = bool(cmd[1])
            if not self._maestro:
                self._parar_todas()
            self._notificar("maestro", "ACTIVO" if self._maestro else "PARADO")
        elif tipo == "parar_todas":
            self._parar_todas()
        elif tipo == "probar":
            self._probar(cmd[1], cmd[2])

    # ------------------------------------------------------------------ macros
    def _aplicar_config(self, cfg):
        self._parar_todas()
        self._debounce = max(0.0, cfg.ajustes.debounce_ms / 1000.0)
        self._seguir_foco = cfg.ajustes.seguir_foco
        self._macros = dict((m.id, m.copia_inmutable()) for m in cfg.macros)

    def _al_pulsar_hotkey(self, id_macro, abajo):
        if not abajo:
            return                      # el flanco de subida no hace nada en toggle ni en pulso
        if not self._maestro:
            self._notificar("aviso", "El interruptor maestro está en PARADO.")
            return
        ahora = self._reloj.ahora()
        if ahora - self._ultimo_disparo.get(id_macro, 0.0) < self._debounce:
            return
        self._ultimo_disparo[id_macro] = ahora
        macro = self._macros.get(id_macro)
        if macro is None:
            return
        if id_macro in self._tareas:
            if macro.hotkey.modo == "toggle":
                self._terminar(id_macro, "parada")
            return
        self._lanzar(macro)

    def _lanzar(self, macro):
        ok, conflicto = self.arbitro.reservar(macro.id, macro.recursos())
        if not ok:
            otro = self._macros.get(conflicto)
            self._notificar("conflicto", "«%s» usa el mismo botón que «%s»." % (
                macro.nombre, otro.nombre if otro else conflicto))
            return
        if self._hwnd_objetivo is None:
            self._hwnd_objetivo = winapi.ventana_primer_plano()
            if winapi.ventana_primer_plano_elevada():
                self._notificar("uipi", "La ventana en primer plano es de administrador: "
                                        "Windows bloquea los clics. Reinicia como admin.")
        gen = self._generador(macro)
        ahora = self._reloj.ahora()
        self._tareas[macro.id] = Tarea(gen, ahora, macro.id, ahora)
        self._notificar("arranca", macro.nombre)

    def _terminar(self, id_macro, motivo=""):
        if id_macro is None:
            return
        tarea = self._tareas.pop(id_macro, None)
        if tarea is not None:
            tarea.gen.close()
        self.estado.soltar_de(id_macro)
        self.arbitro.liberar(id_macro)
        if not self._tareas:
            self._hwnd_objetivo = None
            if self.estado.inhibido:
                self.estado.inhibido = False
        macro = self._macros.pop(id_macro) if id_macro == "__prueba__" else \
            self._macros.get(id_macro)
        self._notificar("para", (macro.nombre if macro else "") + (
            (" — " + motivo) if motivo else ""))

    def _parar_todas(self):
        for i in list(self._tareas):
            self._terminar(i)
        self.estado.soltar_todo()
        self.arbitro.limpiar()

    def _hacer_panico(self):
        for i in list(self._tareas):
            tarea = self._tareas.pop(i)
            tarea.gen.close()
        self.arbitro.limpiar()
        self.estado.soltar_todo()
        self._hwnd_objetivo = None
        self._maestro = False
        self._notificar("panico", "PÁNICO: todo suelto y macros paradas.")

    def _probar(self, macro, segundos):
        """Arranca una macro un rato desde el diálogo. La UI ya ha comprobado que el foco no
        está en nuestra propia ventana; aquí solo se ejecuta y se corta sola."""
        copia = macro.copia_inmutable()
        copia.id = "__prueba__"
        copia.auto_soltar_min = 0
        self._macros[copia.id] = copia
        self._lanzar(copia)
        if copia.id in self._tareas:
            self._fin_prueba = self._reloj.ahora() + segundos

    # ------------------------------------------------------------------ generadores
    def _generador(self, macro):
        if macro.accion.tipo == TIPO_MANTENER:
            return self._gen_mantener(macro)
        if macro.accion.tipo == TIPO_CLIC_AUTO:
            return self._gen_clic_auto(macro)
        return self._gen_secuencia(macro)

    @staticmethod
    def _con_jitter(base_ms, jitter_ms):
        if jitter_ms <= 0:
            return max(0.0, base_ms / 1000.0)
        d = random.uniform(-jitter_ms, jitter_ms)
        return max(0.001, (base_ms + d) / 1000.0)

    def _pulsar_objetivo(self, objetivo, duenyo):
        if objetivo.tipo == "raton":
            self.estado.pulsar_boton(objetivo.boton, duenyo)
        else:
            self.estado.pulsar_tecla(objetivo.vk, duenyo)

    def _soltar_objetivo(self, objetivo):
        if objetivo.tipo == "raton":
            self.estado.soltar_boton(objetivo.boton)
        else:
            self.estado.soltar_tecla(objetivo.vk)

    def _gen_mantener(self, m):
        if m.retardo_inicial_ms:
            yield m.retardo_inicial_ms / 1000.0
        self._pulsar_objetivo(m.accion.objetivo, m.id)
        # Un solo DOWN, nunca reafirmado: en Minecraft un segundo DOWN reinicia el progreso
        # de rotura del bloque, o sea que "reforzar" la pulsación hace que mines más lento.
        while True:
            yield 3600.0

    def _gen_clic_auto(self, m):
        a = m.accion
        if m.retardo_inicial_ms:
            yield m.retardo_inicial_ms / 1000.0
        hechas = 0
        while True:
            dur = self._con_jitter(a.duracion_ms, a.jitter_duracion_ms)
            self._pulsar_objetivo(a.objetivo, m.id)
            yield dur
            self._soltar_objetivo(a.objetivo)
            hechas += 1
            if a.repeticiones and hechas >= a.repeticiones:
                return
            intervalo = self._con_jitter(a.intervalo_ms, a.jitter_intervalo_ms)
            yield max(0.001, intervalo - dur)

    def _gen_secuencia(self, m):
        a = m.accion
        if m.retardo_inicial_ms:
            yield m.retardo_inicial_ms / 1000.0
        vueltas = 0
        while True:
            for p in a.pasos:
                if p.op == OP_TECLA_ABAJO:
                    self.estado.pulsar_tecla(p.vk, m.id)
                elif p.op == OP_TECLA_ARRIBA:
                    self.estado.soltar_tecla(p.vk)
                elif p.op == OP_CLIC:
                    self.estado.pulsar_boton(p.boton, m.id)
                    yield p.duracion_ms / 1000.0
                    self.estado.soltar_boton(p.boton)
                elif p.op == OP_ESPERAR:
                    yield self._con_jitter(p.ms, p.jitter_ms)
            vueltas += 1
            if a.repeticiones and vueltas >= a.repeticiones:
                return
            yield 0.005     # cede el hilo: una secuencia sin esperas no puede girar en vacío

    # ------------------------------------------------------------------ tareas periódicas
    def _gen_foco(self):
        """Alt-tab: soltar al salir, repulsar SOLO lo deseado al volver."""
        while True:
            yield PERIODO_FOCO
            if not self._seguir_foco or self._hwnd_objetivo is None:
                continue
            actual = winapi.ventana_primer_plano()
            if actual != self._hwnd_objetivo:
                if not self.estado.inhibido and self.estado.hay_algo_pulsado():
                    self.estado.inhibir()
                    self._notificar("foco", "Fuera del juego: entrada suelta.")
            elif self.estado.inhibido:
                self.estado.restaurar()
                self._notificar("foco", "De vuelta al juego: entrada restaurada.")

    def _gen_sonda(self):
        """Salud del hook. Detecta aquí; reinstalar lo hace el hilo del hook."""
        while True:
            yield PERIODO_SONDA
            if self._hook is None:
                continue
            if self._sonda_lanzada:
                if self._hook.lanzar_sonda_recibida():
                    self._sondas_perdidas = 0
                else:
                    self._sondas_perdidas += 1
                    if self._sondas_perdidas >= 2:
                        self._sondas_perdidas = 0
                        self._hook.pedir_reinstalacion()
                        self._notificar("hook", "El hook de teclado había muerto; reinstalado.")
            self._iny.enviar_sonda()
            self._sonda_lanzada = True

    def _gen_vigilancia(self):
        """Dead-man por macro y corte de las pruebas."""
        while True:
            yield PERIODO_VIGILANCIA
            ahora = self._reloj.ahora()
            if self._fin_prueba is not None and ahora >= self._fin_prueba:
                self._fin_prueba = None
                if "__prueba__" in self._tareas:
                    self._terminar("__prueba__", "fin de la prueba")
            for id_macro in list(self._tareas):
                macro = self._macros.get(id_macro)
                if macro is None or not macro.auto_soltar_min:
                    continue
                tarea = self._tareas[id_macro]
                limite = tarea.inicio + macro.auto_soltar_min * 60.0
                if ahora >= limite:
                    self._terminar(id_macro, "se cumplió el tiempo máximo")
                elif not tarea.avisado and ahora >= limite - AVISO_AUTO_SOLTAR:
                    tarea.avisado = True
                    self._notificar("aviso_auto", "«%s» se soltará en %d s."
                                    % (macro.nombre, int(AVISO_AUTO_SOLTAR)))

    # ------------------------------------------------------------------ varios
    def _registrar(self, info, contexto):
        try:
            import almacen
            almacen.registrar_excepcion(info[0], info[1], info[2], contexto)
        except Exception:
            pass
