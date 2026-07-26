# -*- coding: utf-8 -*-
"""Capa Win32 del autoclicker. Todo el ctypes crudo vive aquí y en ningún otro sitio.

Convención (ver DECISIONES.md): los nombres de Win32 se escriben literales de MSDN; el resto,
en español.

Piezas:
  - Estructuras de SendInput y el `Inyector`, único emisor de eventos sintéticos.
  - `TABLA_BOTONES`: la ÚNICA tabla de botones de ratón del proyecto. `soltar_todo_ciego()` la
    recorre, así que añadir un botón aquí lo añade también al camino de emergencia.
  - `RelojWin32`: temporizador de alta resolución + espera interrumpible.
  - DPI, mutex de instancia única, elevación y monitores.
"""

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

# --- Tipos que ctypes.wintypes no trae -------------------------------------------------------
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

# --- Firmas propias --------------------------------------------------------------------------
# Todo lo que inyectamos va marcado para que nuestro propio hook lo ignore y no se autodispare.
EXTRA_SIG = 0x4D43414C     # "MCAL" — input normal: el hook lo deja pasar
EXTRA_SONDA = 0x4D43414D   # "MCAM" — sonda del watchdog: el hook la reconoce y la TRAGA
VK_SONDA = 0x07            # virtual-key indefinido: si el hook estuviera muerto, nadie lo usa

# --- Constantes ------------------------------------------------------------------------------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0

ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

SW_RESTORE = 9
MONITOR_DEFAULTTONEAREST = 2

CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x00000002
TIMER_ALL_ACCESS = 0x1F0003
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0

# Teclas cuyo scancode necesita el prefijo E0. Sin esto, las flechas se confunden con el
# teclado numérico. `teclas.py` importa este conjunto en vez de tener el suyo.
EXTENDED_VKS = frozenset({
    0x21, 0x22, 0x23, 0x24,        # RePág, AvPág, Fin, Inicio
    0x25, 0x26, 0x27, 0x28,        # flechas
    0x2C, 0x2D, 0x2E,              # ImprPant, Insert, Supr
    0x5B, 0x5C, 0x5D,              # Windows izq/der, Menú contextual
    0x6F,                          # / del numpad
    0x90,                          # Bloq Num
    0xA3, 0xA5,                    # Ctrl der, Alt Gr
})


class Boton(object):
    """Una fila de TABLA_BOTONES."""

    __slots__ = ("clave", "etiqueta", "abajo", "arriba", "datos")

    def __init__(self, clave, etiqueta, abajo, arriba, datos):
        self.clave = clave
        self.etiqueta = etiqueta
        self.abajo = abajo      # MOUSEEVENTF_*DOWN
        self.arriba = arriba    # MOUSEEVENTF_*UP
        self.datos = datos      # mouseData (XBUTTON1/2)


# ÚNICA fuente de verdad para botones de ratón: flags, mouseData y etiqueta en español.
TABLA_BOTONES = {
    "izq":   Boton("izq",   "Clic izquierdo",   0x0002, 0x0004, 0),
    "der":   Boton("der",   "Clic derecho",     0x0008, 0x0010, 0),
    "medio": Boton("medio", "Clic central",     0x0020, 0x0040, 0),
    "x1":    Boton("x1",    "Botón lateral 1",  0x0080, 0x0100, 1),
    "x2":    Boton("x2",    "Botón lateral 2",  0x0080, 0x0100, 2),
}
BOTONES_VALIDOS = frozenset(TABLA_BOTONES)


# --- Estructuras -----------------------------------------------------------------------------
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    # OJO: dwExtraInfo es ULONG_PTR, no DWORD. Con DWORD, sizeof(INPUT) sale 28 en vez de 40
    # y SendInput devuelve 0 con ERROR_INVALID_PARAMETER sin más pistas.
    _fields_ = [("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _UNION_INPUT(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION_INPUT)]


_TAM_INPUT_ESPERADO = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
assert ctypes.sizeof(INPUT) == _TAM_INPUT_ESPERADO, (
    "sizeof(INPUT) == %d, se esperaba %d. Revisa ULONG_PTR en KEYBDINPUT/MOUSEINPUT."
    % (ctypes.sizeof(INPUT), _TAM_INPUT_ESPERADO))


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


# --- Prototipos ------------------------------------------------------------------------------
# Sin argtypes/restype explícitos, los handles de 64 bits se truncan a 32 y todo falla de
# formas creativas. Se declaran TODAS las funciones que usamos.
u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
sh32 = ctypes.WinDLL("shell32", use_last_error=True)

u32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
u32.SendInput.restype = wintypes.UINT
u32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
u32.MapVirtualKeyW.restype = wintypes.UINT
u32.GetForegroundWindow.argtypes = ()
u32.GetForegroundWindow.restype = wintypes.HWND
u32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
u32.GetAsyncKeyState.restype = ctypes.c_short
u32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
u32.MonitorFromWindow.restype = wintypes.HMONITOR
u32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
u32.GetMonitorInfoW.restype = wintypes.BOOL
u32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
u32.ShowWindow.restype = wintypes.BOOL
u32.SetForegroundWindow.argtypes = (wintypes.HWND,)
u32.SetForegroundWindow.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = (wintypes.HWND,)
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
u32.GetWindowTextW.restype = ctypes.c_int

k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
k32.OpenProcess.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = (wintypes.HANDLE,)
k32.CloseHandle.restype = wintypes.BOOL
k32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
k32.CreateMutexW.restype = wintypes.HANDLE
k32.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
k32.CreateEventW.restype = wintypes.HANDLE
k32.SetEvent.argtypes = (wintypes.HANDLE,)
k32.SetEvent.restype = wintypes.BOOL
k32.CreateWaitableTimerExW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR,
                                       wintypes.DWORD, wintypes.DWORD)
k32.CreateWaitableTimerExW.restype = wintypes.HANDLE
k32.CreateWaitableTimerW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
k32.CreateWaitableTimerW.restype = wintypes.HANDLE
k32.SetWaitableTimer.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.LARGE_INTEGER),
                                 wintypes.LONG, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL)
k32.SetWaitableTimer.restype = wintypes.BOOL
k32.CancelWaitableTimer.argtypes = (wintypes.HANDLE,)
k32.CancelWaitableTimer.restype = wintypes.BOOL
k32.WaitForMultipleObjects.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                       wintypes.BOOL, wintypes.DWORD)
k32.WaitForMultipleObjects.restype = wintypes.DWORD

sh32.ShellExecuteW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                               wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int)
sh32.ShellExecuteW.restype = wintypes.HINSTANCE


# --- Inyector --------------------------------------------------------------------------------
class Inyector(object):
    """Emite eventos sintéticos con SendInput. Único emisor del proceso.

    Usa un buffer `(INPUT * 1)` preasignado en vez de construir una estructura nueva por
    evento: medido, 0,31 us frente a 1,00 us, y sin basura para el GC en el camino caliente.
    """

    def __init__(self):
        self._buf = (INPUT * 1)()
        # El motor es el único que debería emitir, pero atexit/excepthook pueden entrar desde
        # otro hilo en una emergencia. El lock cuesta ~60 ns y evita corromper el buffer.
        self._lock = threading.Lock()
        self.enviados = 0
        self.fallidos = 0

    def _enviar(self):
        # OJO: si la ventana destino está elevada y nosotros no, UIPI bloquea el evento y
        # NI el valor de retorno NI GetLastError lo indican. Por eso existe
        # `ventana_primer_plano_elevada()`: es la única forma de avisar al usuario.
        n = u32.SendInput(1, self._buf, ctypes.sizeof(INPUT))
        if n != 1:
            self.fallidos += 1
            return False
        self.enviados += 1
        return True

    def _raton(self, flags, datos, firma):
        with self._lock:
            e = self._buf[0]
            e.type = INPUT_MOUSE
            mi = e.mi
            mi.dx = 0
            mi.dy = 0
            mi.mouseData = datos
            mi.dwFlags = flags
            mi.time = 0
            mi.dwExtraInfo = firma
            return self._enviar()

    def _tecla(self, vk, arriba, firma):
        with self._lock:
            e = self._buf[0]
            e.type = INPUT_KEYBOARD
            ki = e.ki
            ki.wVk = vk
            # Mandamos VK **y** scancode: GLFW (Minecraft Java) y DirectInput indexan por
            # scancode, y con solo el VK hay juegos que ni se enteran.
            ki.wScan = u32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
            flags = KEYEVENTF_KEYUP if arriba else 0
            if vk in EXTENDED_VKS:
                flags |= KEYEVENTF_EXTENDEDKEY
            ki.dwFlags = flags
            ki.time = 0
            ki.dwExtraInfo = firma
            return self._enviar()

    # --- API pública (la que ve el motor; `pruebas/falso.py` la imita) ---
    def raton_abajo(self, boton):
        b = TABLA_BOTONES[boton]
        return self._raton(b.abajo, b.datos, EXTRA_SIG)

    def raton_arriba(self, boton):
        b = TABLA_BOTONES[boton]
        return self._raton(b.arriba, b.datos, EXTRA_SIG)

    def tecla_abajo(self, vk):
        return self._tecla(vk, False, EXTRA_SIG)

    def tecla_arriba(self, vk):
        return self._tecla(vk, True, EXTRA_SIG)

    def enviar_sonda(self):
        """Latido del watchdog: una tecla indefinida que nuestro hook traga.

        Si el hook está vivo, el evento muere en nuestro callback y ninguna aplicación lo ve.
        Si el hook está muerto, llega al primer plano como VK 0x07, que nadie usa.
        """
        self._tecla(VK_SONDA, False, EXTRA_SONDA)
        self._tecla(VK_SONDA, True, EXTRA_SONDA)


def soltar_todo_ciego(inyector, vks=()):
    """Suelta TODOS los botones y las teclas indicadas, sin mirar el estado.

    Un UP sin su DOWN es inocuo, así que esto es seguro de llamar en cualquier momento: al
    arrancar (por si un crash anterior dejó algo pulsado), en `atexit` y en los excepthooks.
    Recorre TABLA_BOTONES en vez de una lista escrita a mano, para que añadir un botón no
    pueda olvidarse aquí.
    """
    for clave in TABLA_BOTONES:
        try:
            inyector.raton_arriba(clave)
        except Exception:
            pass
    for vk in vks:
        try:
            inyector.tecla_arriba(vk)
        except Exception:
            pass


# --- Reloj de alta resolución ----------------------------------------------------------------
def _crear_timer():
    h = k32.CreateWaitableTimerExW(None, None,
                                   CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS)
    if not h:
        # Windows anterior a 10 1803: temporizador normal (peor resolución, sigue funcionando).
        h = k32.CreateWaitableTimerW(None, False, None)
    return h


class RelojWin32(object):
    """Reloj del motor: espera hasta un instante absoluto, interrumpible.

    `threading.Event.wait()` NO sirve aquí: medido en Python 3.9 se pasa 10,27 ms de mediana
    (la cuantización está en el camino de timeout de los locks de CPython, no en el
    temporizador de Windows), y `timeBeginPeriod(1)` no lo mejora. Este camino mide 0,13 ms.
    """

    SPIN = 0.0003   # último tramo a base de perf_counter; 0,3 ms, no más

    def __init__(self):
        self._timer = _crear_timer()
        self._despertar_h = k32.CreateEventW(None, False, False, None)  # auto-reset
        self._handles = (wintypes.HANDLE * 2)(self._timer, self._despertar_h)

    def ahora(self):
        return time.perf_counter()

    def esperar_hasta(self, limite):
        """Duerme hasta `limite` (escala de `ahora()`). True si nos despertaron antes."""
        while True:
            restante = limite - time.perf_counter()
            if restante <= self.SPIN:
                break
            debido = wintypes.LARGE_INTEGER(int(-(restante - self.SPIN) * 10000000))
            if not k32.SetWaitableTimer(self._timer, ctypes.byref(debido), 0, None, None, False):
                time.sleep(max(0.0, restante - self.SPIN))
                break
            tope_ms = int(restante * 1000) + 50   # red de seguridad: nunca INFINITE
            r = k32.WaitForMultipleObjects(2, self._handles, False, tope_ms)
            if r == WAIT_OBJECT_0 + 1:
                k32.CancelWaitableTimer(self._timer)
                return True
            if r != WAIT_OBJECT_0:
                break
        while time.perf_counter() < limite:
            pass
        return False

    def despertar(self):
        """Interrumpe la espera. Seguro desde cualquier hilo (lo llama el hook)."""
        k32.SetEvent(self._despertar_h)


# --- DPI -------------------------------------------------------------------------------------
def activar_conciencia_dpi():
    """PER_MONITOR_AWARE_V2 con degradación ordenada. Devuelve el modo conseguido."""
    try:
        u32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        u32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):   # PER_MONITOR_AWARE_V2
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        if shcore.SetProcessDpiAwareness(2) == 0:                    # PER_MONITOR_DPI_AWARE
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        u32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError):
        return "ninguna"


def dpi_de_ventana(hwnd):
    """Devuelve los DPI de la ventana (96 = 100 %)."""
    try:
        u32.GetDpiForWindow.argtypes = (wintypes.HWND,)
        u32.GetDpiForWindow.restype = wintypes.UINT
        d = u32.GetDpiForWindow(wintypes.HWND(hwnd))
        if d:
            return int(d)
    except (AttributeError, OSError):
        pass
    return 96


def area_trabajo(hwnd):
    """Área utilizable del monitor donde está `hwnd`: (x, y, ancho, alto)."""
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    mon = u32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    if mon and u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        r = mi.rcWork
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    return (0, 0, u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))


# --- Instancia única, elevación y relanzado --------------------------------------------------
NOMBRE_MUTEX = "Local\\Autoclicker-{7f3a1c92-5e64-4b2d-9a10-6c8d2f4b7e31}"


def reclamar_instancia_unica():
    """(soy_la_primera, handle). El mutex va en Local\\ : en Global\\ cualquier proceso de la
    máquina podría okuparlo e impedirnos arrancar para siempre."""
    h = k32.CreateMutexW(None, True, NOMBRE_MUTEX)
    ya_existia = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    return (not ya_existia), h


def enfocar_ventana(prefijo_titulo):
    """Restaura y trae al frente la ventana de la instancia que ya estaba corriendo."""
    encontrada = []

    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _visitar(hwnd, _lparam):
        if not u32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith(prefijo_titulo):
            encontrada.append(hwnd)
            return False
        return True

    cb = ENUMPROC(_visitar)
    u32.EnumWindows.argtypes = (ENUMPROC, wintypes.LPARAM)
    u32.EnumWindows.restype = wintypes.BOOL
    u32.EnumWindows(cb, 0)
    if not encontrada:
        return False
    u32.ShowWindow(encontrada[0], SW_RESTORE)
    u32.SetForegroundWindow(encontrada[0])
    return True


def ventana_primer_plano_elevada():
    """True si la ventana en primer plano corre elevada y nosotros no.

    Es la única forma de avisar del bloqueo UIPI: `SendInput` devuelve éxito y no hace nada.
    Heurística estándar: un proceso elevado se deja abrir con QUERY_LIMITED_INFORMATION pero
    rechaza QUERY_INFORMATION.
    """
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD(0)
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or pid.value == os.getpid():
        return False
    h_lim = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h_lim:
        return False        # ni siquiera eso: no podemos afirmar nada
    k32.CloseHandle(h_lim)
    h_full = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid.value)
    if h_full:
        k32.CloseHandle(h_full)
        return False
    return ctypes.get_last_error() == ERROR_ACCESS_DENIED


def ventana_primer_plano():
    return u32.GetForegroundWindow()


def relanzar_como_admin():
    """Relanza el proceso pidiendo elevación. True si Windows aceptó lanzarlo.

    La ruta sale SIEMPRE de `sys.executable` en absoluto: usar `argv[0]`, un nombre suelto o
    cualquier cosa resuelta por PATH/CWD es un secuestro esperando a ocurrir, porque la
    carpeta de instalación es escribible por el usuario.
    """
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        params = ""
    else:
        guion = os.path.abspath(sys.argv[0])
        params = '"%s"' % guion
    r = sh32.ShellExecuteW(None, "runas", exe, params or None, os.path.dirname(exe), 1)
    return int(ctypes.cast(r, ctypes.c_void_p).value or 0) > 32


WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20


def hacer_ventana_no_activable(hwnd):
    """Marca una ventana para que NO robe el foco ni salga en la barra de tareas.

    El indicador flotante se dibuja encima de un juego a pantalla completa: si al aparecer
    le robara el foco al juego, sería peor el remedio que la enfermedad.
    """
    try:
        obtener = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
        poner = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
        obtener.argtypes = (wintypes.HWND, ctypes.c_int)
        obtener.restype = ctypes.c_ssize_t
        poner.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        poner.restype = ctypes.c_ssize_t
        h = wintypes.HWND(hwnd)
        estilo = obtener(h, GWL_EXSTYLE)
        poner(h, GWL_EXSTYLE, estilo | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        return True
    except (AttributeError, OSError, ctypes.ArgumentError):
        return False


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def carpeta_appdata():
    """Ruta de %APPDATA% (Roaming), o None. Sin fallback implícito al directorio actual.

    Se prueba la variable de entorno y, si no vale, `SHGetKnownFolderPath`. Si ninguna
    responde, devolvemos None y la app avisa de que no va a persistir nada, en vez de
    escribir en la carpeta de instalación.
    """
    base = os.environ.get("APPDATA")
    if base and os.path.isdir(base):
        return base
    try:
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        sh = ctypes.WinDLL("shell32", use_last_error=True)
        sh.SHGetKnownFolderPath.argtypes = (ctypes.POINTER(_GUID), wintypes.DWORD,
                                            wintypes.HANDLE, ctypes.POINTER(wintypes.LPWSTR))
        sh.SHGetKnownFolderPath.restype = ctypes.c_long
        # FOLDERID_RoamingAppData
        guid = _GUID(0x3EB685DB, 0x65F9, 0x4CF6,
                     (ctypes.c_ubyte * 8)(0xA0, 0x3A, 0xE3, 0xEF, 0x65, 0x72, 0x9F, 0x3D))
        salida = wintypes.LPWSTR()
        if sh.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(salida)) == 0:
            ruta = salida.value
            ole32.CoTaskMemFree(salida)
            if ruta and os.path.isdir(ruta):
                return ruta
    except (AttributeError, OSError):
        pass
    return None


def modificadores_pulsados():
    """Bitmask 1=Ctrl 2=Alt 4=Mayús leído del estado real del teclado.

    Se consulta en vivo en lugar de recordar pulsaciones: así el hook no necesita guardar
    ninguna tecla que no sea una hotkey registrada.
    """
    m = 0
    if u32.GetAsyncKeyState(0x11) & 0x8000:   # VK_CONTROL
        m |= 1
    if u32.GetAsyncKeyState(0x12) & 0x8000:   # VK_MENU
        m |= 2
    if u32.GetAsyncKeyState(0x10) & 0x8000:   # VK_SHIFT
        m |= 4
    return m
