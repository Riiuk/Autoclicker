# -*- coding: utf-8 -*-
"""Las dos costuras que hacen esto probable sin juego, sin ratón y sin GPU.

`Motor(inyector, reloj)` recibe estos dos en las pruebas en vez de `winapi.Inyector` y
`winapi.RelojWin32`. Nada más cambia.
"""


class InyectorFalso(object):
    """Registra cada evento en vez de mandarlo a Windows."""

    def __init__(self, reloj=None):
        self.eventos = []          # [("raton_abajo", "izq"), ("tecla_arriba", 87), ...]
        self.tiempos = []          # instante de cada evento, para medir la deriva
        self.sondas = 0
        self._reloj = reloj

    def _anotar(self, op, arg):
        self.eventos.append((op, arg))
        self.tiempos.append(self._reloj.ahora() if self._reloj else None)
        return True

    def raton_abajo(self, boton):
        return self._anotar("raton_abajo", boton)

    def raton_arriba(self, boton):
        return self._anotar("raton_arriba", boton)

    def tecla_abajo(self, vk):
        return self._anotar("tecla_abajo", vk)

    def tecla_arriba(self, vk):
        return self._anotar("tecla_arriba", vk)

    def enviar_sonda(self):
        self.sondas += 1

    # --- comprobaciones ---
    def pendientes(self):
        """Recursos que quedaron ABAJO sin su ARRIBA. Debe estar vacío tras parar."""
        abiertos = set()
        for op, arg in self.eventos:
            if op == "raton_abajo":
                abiertos.add(("raton", arg))
            elif op == "raton_arriba":
                abiertos.discard(("raton", arg))
            elif op == "tecla_abajo":
                abiertos.add(("tecla", arg))
            elif op == "tecla_arriba":
                abiertos.discard(("tecla", arg))
        return abiertos

    def cuenta(self, op, arg=None):
        return sum(1 for o, a in self.eventos if o == op and (arg is None or a == arg))

    def instantes_de(self, op, arg=None):
        """Instantes en que ocurrió un evento concreto."""
        return [t for (o, a), t in zip(self.eventos, self.tiempos)
                if o == op and (arg is None or a == arg)]


class RelojFalso(object):
    """Tiempo virtual: las pruebas simulan horas en milisegundos."""

    def __init__(self, inicio=1000.0):
        self.t = inicio
        self.despertares = 0

    def ahora(self):
        return self.t

    def esperar_hasta(self, limite):
        if limite > self.t:
            self.t = limite
        return False

    def despertar(self):
        self.despertares += 1


def correr(motor, reloj, duracion, tope_ciclos=200000):
    """Hace avanzar el motor `duracion` segundos de tiempo virtual."""
    fin = reloj.t + duracion
    ciclos = 0
    while reloj.t < fin and ciclos < tope_ciclos:
        proximo = motor.tick()
        ciclos += 1
        reloj.t = min(proximo, fin) if proximo > reloj.t else reloj.t + 0.0005
    return ciclos
