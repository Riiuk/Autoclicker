# Decisiones técnicas — por qué esto está hecho así

Este documento existe para quien herede el proyecto (incluido yo mismo dentro de un año). Cada fila es
una decisión que ya se tomó a conciencia; si vas a cambiar alguna, lee primero el porqué.

## Convención de nombres

**Identificadores de dominio, textos de UI y claves/valores JSON en español. Nombres, constantes y flags
de Win32 literales de MSDN.**

Es decir: `MANTENER`, `CLIC_AUTO`, `SECUENCIA`, `tecla_abajo`, `clic`, `esperar`, `habilitada`,
`EstadoPulsado`, `Inyector`... pero `SendInput`, `KEYEVENTF_SCANCODE`, `WH_KEYBOARD_LL`,
`MOUSEEVENTF_LEFTDOWN` tal cual los escribe Microsoft. Mezclar los dos idiomas *dentro* de un mismo enum
es lo que hay que evitar: los valores del JSON están persistidos y renombrarlos después es una migración.

En la UI se usa el patrón "término llano (jerga)": "Variación aleatoria (jitter)", "Tiempo mínimo entre
pulsaciones (debounce)". Y **Activo/Parado** se reserva para el interruptor maestro;
**Habilitada/Deshabilitada** es lo de cada macro. Antes esas dos cosas se llamaban igual y confundían.

## Decisiones

| Área | Decisión | Por qué |
|---|---|---|
| Inyección de input | `SendInput` vía ctypes. Nunca `keybd_event`, `mouse_event`, `PostMessage`, `pynput`, `pyautogui` ni `keyboard` | Es la única vía que permite fijar `dwExtraInfo`. Sin ese campo, nuestro propio hook no puede distinguir nuestros eventos sintéticos de los del usuario y se autodispara en bucle. Ninguna librería de terceros lo expone. |
| Teclado | Enviar siempre `wVk` **y** `wScan = MapVirtualKeyW(vk, 0)`, más `KEYEVENTF_EXTENDEDKEY` según `EXTENDED_VKS` | GLFW (Minecraft Java) y DirectInput indexan por scancode, no por virtual-key. Con solo `wVk` hay juegos que no reaccionan, y sin el flag de extendida las flechas se confunden con el teclado numérico. |
| Firma | `EXTRA_SIG = 0x4D43414C` ("MCAL") en todo lo que inyectamos; `EXTRA_SONDA = 0x4D43414D` para la sonda del watchdog | Fuera del rango `0xFF5157xx` que Windows reserva. La sonda lleva firma distinta porque el hook debe *reconocerla y tragársela*, mientras que lo demás pasa de largo. |
| Hotkeys | Hook `WH_KEYBOARD_LL` en un hilo dedicado con bucle de mensajes propio | `RegisterHotKey` le robaría la tecla al juego y no admite botones laterales. Sondear con `GetAsyncKeyState` pierde pulsaciones y no distingue nuestro propio input. |
| Identidad de una tecla | Canónica `(scanCode, ext)`. El `vk` se guarda solo para mostrar | Es la posición física de la tecla: independiente de la distribución del teclado, que es lo que importa jugando. Además distingue Intro de Intro-del-numpad y Supr del `.` del numpad. |
| Frontera del hook | La comparación contra las hotkeys registradas ocurre **dentro** del callback; solo sale `(id_macro, flanco)` | Un `WH_KEYBOARD_LL` ve *todas* las pulsaciones de la máquina: contraseñas incluidas. Si encolásemos todo para filtrarlo fuera, el proceso mantendría un búfer rodante de lo que teclea el usuario, visible en cualquier volcado de memoria. Esto es lo que separa una herramienta de macros de un keylogger. |
| Canales entre hilos | hotkey→motor por `deque` + evento Win32 propiedad del motor. motor→UI por `Queue(256)` con pérdidas drenada con `after(30)` | Apagar una macro **no puede** depender del bucle de Tk: Windows congela los `after()` mientras arrastras o redimensionas la ventana, que es justo cuando querrías soltar un botón atascado. |
| Watchdog | Solo **detecta**; la reinstalación la hace el hilo del hook al recibir un `PostThreadMessageW` | Un hook de bajo nivel se despacha al bucle de mensajes del hilo que lo instaló. Si otro hilo llama a `SetWindowsHookEx`, devuelve un handle válido y el callback **no vuelve a dispararse nunca**: la capa de recuperación parece sana y está muerta. |
| Detección de hook muerto | Sonda: cada 2 s se inyecta una tecla indefinida (VK 0x07) con `EXTRA_SONDA`; si el hook vive, la ve y la traga | No existe API para preguntar "¿sigue instalado mi hook?". Y "no llegan eventos" no significa nada: puede que el usuario no esté tecleando. La sonda nunca llega a ninguna aplicación porque nuestro propio hook la suprime. |
| Concurrencia | **Un solo hilo motor** con scheduler cooperativo de generadores. 3 hilos en total: Tk, hook, motor | Un único emisor de `SendInput` da orden determinista, un solo `finally` que lo suelta todo y ninguna carrera entre generadores. El vigilante de foco y la sonda son tareas del mismo scheduler, no hilos aparte. |
| Temporización | Temporizador de alta resolución de Win32 (`CreateWaitableTimerExW` + `CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`) esperado con `WaitForMultipleObjects`, más un spin final de 0,3 ms. **Sin `timeBeginPeriod`** | Medido en `C:\python39\python.exe`: `threading.Event.wait(0.005)` se pasa **10,27 ms de mediana**, y `timeBeginPeriod(1)` no mejora esa mediana en absoluto (la cuantización está en el camino de timeout de los locks de CPython 3.9, no en el temporizador de la plataforma). El temporizador de alta resolución se pasa **0,13 ms**. Con `Event.wait` habría que spinear 10 ms por evento, lo que fija un núcleo entero al 100 % durante horas compitiendo con el juego. |
| Mantener el clic | **Un solo `LEFTDOWN`**, nunca reafirmarlo por temporizador | Parece que falta un keep-alive, pero no: en Minecraft un segundo `DOWN` reinicia el progreso de rotura del bloque, o sea que "reforzar" la pulsación hace que mines **más lento**. Es trivia del juego que nadie va a redescubrir leyendo el código. |
| Alt-tab | Tarea del motor cada 150 ms: al perder el foco la ventana objetivo se suelta todo físicamente; al recuperarlo se repulsa **solo lo que `EstadoPulsado.debe_estar_pulsado()` siga devolviendo** | GLFW suelta todos los botones cuando la ventana pierde el foco y no los vuelve a pulsar al recuperarlo, así que sin esto el botón queda pulsado a nivel de sistema y te pones a arrastrar iconos del escritorio. El "solo lo que siga deseado" es imprescindible: si el pánico saltó mientras el juego estaba en segundo plano, volver al juego **no** debe repulsar nada. |
| Modificadores de una hotkey | Una hotkey **sin** modificadores dispara aunque haya modificadores pulsados. Una **con** modificadores los exige (y gana frente a la versión sin ellos) | La regla intuitiva ("sin modificadores = ningún modificador pulsado") rompe el caso de uso: en Minecraft se juega con Mayús (agacharse) y Ctrl (correr) pulsados a ratos, así que F8 dejaría de responder justo mientras minas agachado. Se detectó porque las pruebas end-to-end fallaban 2 de cada 3 veces con Mayús marcada como pulsada. Además, el flanco de subida se despacha a la MISMA macro que arrancó el de bajada, no se vuelve a resolver: si no, soltar un modificador entre medias dejaba la macro encendida para siempre. |
| Dueño del estado | `EstadoPulsado` es el único que sabe qué está físicamente pulsado, y solo se muta en el hilo motor | Había nueve rutas capaces de soltar o pulsar (motor, `atexit`, dos excepthooks, cierre de ventana, pánico, arranque, dead-man, interruptor maestro y "Probar 3 s"). Sin un dueño único no son capas de seguridad, son un montón sin ordenar en el que una deshace a otra. |
| Árbitro de recursos | Tabla de propietarios por recurso `(botón\|vk)`. La segunda macro que pida un recurso ocupado **se rechaza**, nombrando a la primera | Un MANTENER y un CLIC_AUTO sobre el botón izquierdo: el `UP` del segundo suelta el `DOWN` del primero y el generador del primero ni se entera. Rechazar es más honesto que un comportamiento a medias. |
| Copia al activar | El motor ejecuta una copia inmutable de la macro tomada en el momento de armarla | El diálogo de edición y el motor podrían tocar el mismo objeto a la vez; cada lectura de atributo es atómica pero el conjunto no, así que el motor vería una macro medio actualizada. |
| Persistencia | `%APPDATA%\Autoclicker\config.json`, escritura atómica (tmp + `os.replace`) con `.bak`, guardado solo en ediciones del usuario y con debounce | Junto al `.exe` la carpeta puede ser de solo lectura, y `sys._MEIPASS` se borra al salir. El debounce evita que cada activación por hotkey dispare una escritura que Defender escanea de forma síncrona. |
| Validación | Un único validador estricto en `modelo.py` que usan disco, `.bak` e Importar. Nunca lanza: degrada a `soportada=False` | El `config.json` es entrada no confiable por diseño (se edita a mano y hay menú de importar). Un `vk` fuera de rango va directo a un `WORD` de `SendInput`; un `{"op":"esperar","ms":999999999}` aparca el motor con teclas pulsadas. |
| Empaquetado | `--onedir`, `upx=False`, `--noconsole`, version info real, icono propio, **sin** `--uac-admin` | onefile + hook global es la firma heurística de dropper + keylogger: cuarentena de Defender casi garantizada, y 1–3 s de arranque de propina. |
| Elevación | `asInvoker`. Si detectamos que la ventana en primer plano está elevada, avisamos y ofrecemos relanzar con `ShellExecuteW runas` usando ruta **absoluta desde `sys.executable`** | Minecraft corre a integridad media, así que elevar siempre solo añade UAC en cada arranque. Y relanzar por `argv[0]` o por algo resuelto por PATH/CWD es un secuestro esperando a ocurrir, porque la carpeta de instalación es escribible por el usuario. |
| Firma del binario | Diferido | Es una herramienta personal. Lo que sí se hace es publicar el SHA-256 del `.exe` y del zip, para que exista una identidad que sobreviva a copiarlo. |

## Lo que se probó y se descartó

- **`pynput` / `keyboard` / `pyautogui`**: no exponen `dwExtraInfo`. Sin eso no hay forma limpia de que el
  hook ignore nuestros propios eventos.
- **C# / .NET**: en esta máquina hay runtimes pero **no SDK**, así que no se puede compilar.
- **Electron**: el input global y el mantener-pulsado en juegos es doloroso, y el binario pesa 20 veces más.
- **`--onefile`**: ver la fila de empaquetado.
- **`timeBeginPeriod(1)`**: medido, no aporta nada al camino que usamos, y sube la frecuencia global del
  temporizador de la plataforma (batería). Si alguien lo reintroduce, tiene que llevar refcount y su
  `timeEndPeriod` emparejado en un `finally`.
- **`sys.setswitchinterval(0.002)` como mitigación del GIL**: medido, el peor bloqueo de un hilo compitiendo
  con el motor fue ~30 ms contra un presupuesto de 300 ms del hook. El callback se mantiene mínimo por
  privacidad, no por el GIL.
