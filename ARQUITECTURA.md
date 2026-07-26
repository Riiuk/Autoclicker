# Arquitectura

Cómo funciona esto por dentro, qué invariantes no se pueden romper y por dónde se toca para
los cambios más habituales. Para el *porqué* de cada decisión, ver [`DECISIONES.md`](DECISIONES.md).

## El recorrido de una pulsación

Este es el camino completo, de la tecla al clic. Si algo no funciona, se depura siguiéndolo en
orden:

```
   tecla física
        │
        ▼
 ┌──────────────────┐   hilo «hook-ll», con su propio bucle de mensajes
 │  hotkeys.py      │   compara (scanCode, ext) contra las hotkeys registradas AQUÍ DENTRO
 │  _al_llegar_tecla│   y solo deja salir (id_macro, flanco) — más la bandera de pánico,
 └────────┬─────────┘   que no lleva datos, y el (sc, ext, vk) del modo captura
          │  deque + SetEvent          ◄── canal de ÓRDENES, no pasa por Tk
          ▼
 ┌──────────────────┐   hilo «motor», único emisor de SendInput en el camino normal
 │  motor.py        │   scheduler cooperativo de generadores con vencimientos absolutos
 │  Motor._bucle    │
 └───┬──────────┬───┘
     │          │  Queue(256) con pérdidas   ──►  ui.py drena con after(30)   ◄── TELEMETRÍA
     ▼
 ┌──────────────────┐
 │  EstadoPulsado   │   dueño único de qué está físicamente pulsado
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │  winapi.Inyector │   SendInput con buffer preasignado y firma dwExtraInfo
 └────────┬─────────┘
          ▼
   la aplicación de destino
```

**Los dos canales son distintos a propósito.** Las órdenes (hotkey → motor) van por un `deque`
que el motor consume; la telemetría (motor → interfaz) va por una `Queue` con pérdidas. Apagar
una macro no puede depender del bucle de Tk, porque Windows congela los `after()` mientras
arrastras o redimensionas la ventana — que es justo cuando más te urge soltar un botón.

## Capas

Grafo de importaciones real. No hay ninguna arista hacia arriba ni ciclos; si alguna vez
necesitas una, es señal de que la responsabilidad está en el módulo equivocado.

```
winapi.py      (nada del proyecto)   ctypes, SendInput, tabla de botones, reloj, DPI, mutex
teclas.py      → winapi              nombres legibles, identidad (sc, ext), reservadas
modelo.py      → winapi              dataclasses + validador
hotkeys.py     → winapi              hook WH_KEYBOARD_LL
indicador.py   → winapi              sonidos e indicador flotante
almacen.py     → modelo, winapi      config.json, .bak, error.log
motor.py       → winapi, modelo      scheduler, EstadoPulsado, árbitro  (+ almacen en diferido)
ui_macro.py    → modelo, teclas, winapi
ui.py          → almacen, hotkeys, indicador, modelo, teclas, ui_macro, winapi
main.py        → almacen, hotkeys, motor, ui, winapi          cableado
motor_test.py  → almacen, hotkeys, modelo, motor, teclas      depuración sin interfaz
```

`ui.py` **no** importa `motor`: lo recibe como parámetro del constructor, y quien los une es
`main.py`.

Reglas de frontera:

- **`winapi.py` no importa nada del proyecto.** Es la única capa que habla con Windows.
- **`motor.py` no importa `tkinter`**, ni directa ni indirectamente.
- **El hook no sabe qué es una macro.** El callback y el registro solo manejan
  `Enlace(mods, id_macro, tragar)`; el significado lo pone el motor. La única excepción del
  módulo es el ayudante `registro_desde_macros()`, que lee la forma de una `Macro` por duck
  typing —sin `import modelo`— para que la interfaz y `motor_test.py` compartan una sola
  implementación.
- **Nadie toca un widget desde otro hilo que no sea el de Tk.** El único cruce es un
  `raiz.after(0, ...)` desde el hilo `guardado` cuando falla una escritura, y se hace así
  precisamente para devolver el trabajo al hilo de Tk. El hook y el motor solo escriben en la
  `Queue`.

## Hilos

| Hilo | Quién lo crea | Qué hace |
|---|---|---|
| principal (Tk) | `main.py` | interfaz y drenaje de la cola cada 30 ms |
| `hook-ll` | `hotkeys.HiloHook` | bucle de mensajes propio; atiende el hook y lo reinstala cuando se lo piden |
| `motor` | `motor.Motor.arrancar` | ejecuta las macros y las tareas periódicas; único emisor de `SendInput` en el camino normal |
| `sonidos` | `indicador.Sonidos` | `winsound.Beep` bloquea mientras suena, así que va aparte. Se crea siempre, aunque los sonidos estén apagados |
| `guardado` | `almacen.GuardadoDiferido` | efímero, uno por tanda de escrituras |

Los tres primeros son el camino de entrada; los otros dos existen solo para no bloquear a
nadie. **Las tareas periódicas no son hilos**: el vigilante de foco (150 ms), la sonda de salud
del hook (2 s) y el dead-man son generadores más dentro del scheduler del motor, precisamente
para que siga habiendo un único emisor.

## Invariantes

Estos son los que rompen cosas de verdad si se tocan sin pensar.

1. **Todo `down` acaba con su `up`.** Tras parar una macro, un pánico, cortar una secuencia a
   medias o apagar el interruptor maestro, no puede quedar nada pulsado a nivel de sistema. Un
   botón izquierdo pegado deja el escritorio inutilizable.
   → `pruebas/test_motor.py::InvarianteDeSuelta`. El cierre de la ventana y el `atexit` no se
   pueden probar en headless: van en la lista manual de [`CONTRIBUIR.md`](CONTRIBUIR.md).
2. **`EstadoPulsado` es el único que sabe qué está pulsado, y solo se muta en el hilo del
   motor.** Pasan por él las rutas **ordenadas** de suelta: el `finally` del bucle, el cierre de
   la ventana, el pánico, el dead-man, el interruptor maestro y «Probar 3 s».
   Las de **emergencia** —`atexit`, los dos excepthooks y la suelta preventiva al arrancar—
   **no** pasan por él a propósito: disparan a ciegas sobre el inyector, porque cuando el hilo
   del motor puede estar muerto o colgado, un `up` de más es inocuo y un botón pegado no. Por
   eso `winapi.soltar_todo_ciego()` no sobra, y por eso `Inyector` lleva un lock.
   → `pruebas/test_motor.py::AltTab`
3. **El vigilante de foco es la única ruta que *repulsa*.** Al volver de un alt-tab repulsa
   **solo lo que `debe_estar_pulsado()` siga devolviendo**, para que un pánico disparado en
   segundo plano no se deshaga al volver a la aplicación.
   → `pruebas/test_motor.py::AltTab::test_tras_el_panico_no_repulsa_nada`
4. **El callback del hook no saca de su frame ningún código de tecla que no sea una hotkey
   registrada.** Ni lo encola, ni lo guarda, ni lo mete en el conjunto anti-autorepeat, ni acaba
   en el texto de una excepción. Es lo que separa esto de un keylogger. La única excepción es el
   modo captura, acotado con timeout de 10 s y desarmado en cuanto el diálogo pierde el foco.
   **Este invariante no tiene prueba automática** —ninguna prueba ejecuta el callback—, así que
   se sostiene por revisión de código. Lo que sí está cubierto es la mitad del registro de
   errores: `pruebas/test_almacen.py::Registro`.
5. **El callback no propaga ninguna `Exception`.** Si se escapara, `PyErr_WriteUnraisable`
   formatearía un traceback dentro del hook y volvería sin llamar a `CallNextHookEx`, cortando
   la cadena para el resto del software del sistema.
6. **El hook se instala y se desinstala siempre desde su propio hilo.** `SetWindowsHookEx` desde
   otro hilo devuelve un handle válido cuyo callback no se dispara jamás.
7. **El validador nunca lanza, y nunca tira nada.** Cualquier `config.json` que no cuadre
   degrada la macro a `soportada=False` con un motivo legible, y su JSON original se conserva
   en `Macro.bruto` para devolverlo intacto al guardar. Perder la macro de alguien por no
   entenderla sería peor que el fallo que la hizo ilegible.
   → `pruebas/test_modelo.py::ValidadorNoLanza`, `::ConservaLoNoSoportado`,
   `pruebas/test_almacen.py::GuardarYCargar::test_una_macro_no_soportada_sobrevive_en_disco`
8. **Solo se persiste en ediciones del usuario**, nunca en transiciones por hotkey, y con
   debounce fuera del hilo de Tk.

## Recetas

Los cambios que más se van a pedir, con todos los sitios que hay que tocar.

### Añadir un botón de ratón

Una sola línea en `winapi.TABLA_BOTONES`. Nada más.

`winapi.soltar_todo_ciego()` recorre esa tabla, los dos combos de la interfaz —objetivo y paso
de secuencia— se construyen a partir de ella, y el validador usa `BOTONES_VALIDOS`, que sale de
la misma tabla. Esa es exactamente la razón de que exista una tabla única en vez de listas
repartidas: se podía añadir un botón y olvidarse de soltarlo en el camino de emergencia.

### Añadir un tipo de acción

1. `modelo.py`: constante `TIPO_X`, añadirla a `TIPOS_ACCION` y a `ETIQUETAS_TIPO`, extender
   `_validar_accion`, `accion_a_json` y `Macro.recursos()`.
2. `motor.py`: escribir `_gen_x(self, m)` como generador que hace `yield <segundos>` y
   engancharlo en `Motor._generador`. Dos obligaciones que no centraliza nadie: empezar con el
   prólogo del retardo inicial (`if m.retardo_inicial_ms: yield m.retardo_inicial_ms / 1000.0`,
   igual que los otros tres) y pulsar **siempre con `m.id` como dueño**, que es lo que permite a
   `_terminar` soltarlo.
3. `ui_macro.py`: un marco propio con sus campos, mostrarlo en `_al_cambiar_tipo`, **volcar sus
   campos en `_cargar_desde_macro`** y leerlo en `_recoger`. Si se olvida el volcado, abrir una
   macro existente y pulsar Aceptar sin tocar nada la sobrescribe con los valores por defecto
   de los widgets.
4. `ui.py`: añadir el tipo a la rama de objetivo de `_refrescar_espejo`, o el espejo de texto
   describirá la macro sin decir sobre qué actúa.
5. `pruebas/test_motor.py`: como mínimo, que tras pararlo no queda nada pulsado.

Sobre `VERSION_CONFIG`: **no hace falta subirlo** para añadir un tipo. Una versión anterior del
programa marcará el tipo desconocido como `soportada=False`, lo dirá, y al guardar devolverá su
JSON original intacto (`modelo.macros_a_json`), así que la macro sobrevive a la ida y a la
vuelta.

Súbelo cuando el cambio altere el significado de algo que las versiones antiguas **creen**
entender —renombrar un campo, cambiar unidades, reinterpretar un valor existente—, porque ahí
no hay degradación que valga: la versión antigua lo leería mal sin enterarse. En ese caso, la
rama correspondiente va en `almacen.migrar()`.

### Añadir un ajuste

`modelo.Ajustes` (campo con su valor por defecto) → leerlo en `validar_config` con su rango →
escribirlo en `config_a_json` → control en `ui.DialogoAjustes` y volcado en su `_aceptar` → y
consumirlo donde toque.

Ese último paso tiene truco: si lo consume el motor llega gratis por `aplicar_config`, pero hay
que recogerlo en `Motor._aplicar_config`; si lo consume la interfaz, hace falta además
empujarlo al objeto vivo en el propio `_aceptar` (como `self.app.sonidos.activos = aj.sonidos`),
o no surtirá efecto hasta reiniciar.

### Cambiar algo del `config.json` de forma incompatible

Subir `modelo.VERSION_CONFIG` y añadir la rama correspondiente en `almacen.migrar()`. Una
configuración de versión **mayor** que la del programa no se toca nunca, pero cada camino de
carga reacciona distinto:

- Al **cargar del disco** se renombra a `.futuro` y se empieza de cero (`almacen.cargar`).
- Al **importar** desde el menú se rechaza el fichero y se deja la configuración actual intacta,
  sin copia ni renombrado (`ui.importar`).
- `motor_test.py` imprime el aviso y sale con código 2.

Ojo: el texto que devuelve `almacen.migrar` —«se ha guardado una copia y se empieza de cero»—
solo es cierto en el primer caso.

### Depurar sin interfaz

`C:\python39\python.exe motor_test.py [config.json]` levanta hook y motor sin Tk e imprime cada
**notificación del motor**: arranca, para, pánico, conflicto, foco, hook y avisos. No imprime
pulsaciones; el callback de captura es un no-op.

Si algo falla ahí, el problema está en las capas de abajo; si funciona ahí y no en la aplicación
completa, está en la interfaz o en el cableado de `main.py`. Y si la aplicación completa se
cierra sola, el primer sitio donde mirar es **`%APPDATA%\Autoclicker\error.log`**: compilado con
`--noconsole` el `stderr` es `None`, así que ese fichero es el único rastro de un fallo de la
interfaz.

## Qué falta

Ideas ordenadas por relación entre lo que aportan y lo que cuestan. Cada una lleva anotado por
dónde se empieza.

| Idea | Por dónde |
|---|---|
| Integración continua | Un workflow de GitHub Actions sobre `windows-latest` que ejecute las pruebas en cada push. Es lo más barato de todo y lo que más protege. |
| Icono en la bandeja del sistema con menú de activar/parar | `Shell_NotifyIconW` por ctypes sobre una ventana oculta en el hilo del hook. Cuidado: si el GC se lleva el `WNDPROC`, el proceso muere sin traceback. |
| Arrancar con Windows | Valor en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, con casilla en Ajustes. |
| Modo «mantener mientras aprieto» | El modelo casi lo tiene: aceptar `modo="mientras"` en `modelo.MODOS`, tratarlo en `Motor._al_pulsar_hotkey` (que el flanco de subida pare la macro) y exponerlo en el combo del diálogo. |
| Grabadora de secuencias | Reutilizar el modo captura del hook y un `WH_MOUSE_LL` nuevo, volcando a `Paso`. Lo caro no es grabar, es editar lo grabado. |
| Perfiles por aplicación | Un perfil es una lista de macros; el vigilante de foco ya sabe qué ventana está delante, así que puede cambiar de perfil solo. |
| Hotkeys con botones laterales del ratón | Hace falta un `WH_MOUSE_LL` que conviva con el de teclado. `Enlace` y el registro ya sirven tal cual. |
| Prueba automática del callback del hook | Cerraría el único invariante que hoy se sostiene solo por revisión. Se puede inyectar entrada firmada y comprobar qué sale del despachador. |
| Firmar el binario | Quita casi todos los falsos positivos de Defender. Cuesta dinero y papeleo. |
| Pasada con lector de pantalla | La interfaz ya tiene espejo de texto, atajos y acciones duplicadas en el menú; falta comprobarlo de verdad con NVDA o Narrador. |

## Cosas que parecen bugs y no lo son

Antes de «arreglar» cualquiera de estas, lee su fila en [`DECISIONES.md`](DECISIONES.md):

- El botón mantenido **no se reafirma nunca**. No falta un keep-alive.
- El watchdog detecta que el hook ha muerto, pero **no lo reinstala él**: se lo pide al hilo del
  hook con `PostThreadMessageW`, porque `SetWindowsHookEx` desde otro hilo devuelve un handle
  que no dispara nunca.
- No se usa `Event.wait` para temporizar, ni `timeBeginPeriod`.
- Una hotkey **sin** modificadores dispara aunque haya modificadores pulsados.
- El `.exe` se distribuye como carpeta, no como fichero único.
- La sonda de salud inyecta una tecla cada 2 segundos. Nuestro propio hook se la traga, así que
  ninguna aplicación la ve.
- Las rutas de emergencia sueltan a ciegas sin consultar `EstadoPulsado`. Es deliberado: ver el
  invariante 2.
