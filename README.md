# Autoclicker

Autoclicker con **macros configurables** para Windows. Pulsas la tecla que tú elijas y el
programa mantiene pulsado un botón del ratón, hace clics a un ritmo fijo o ejecuta una
secuencia de pasos. Vuelves a pulsarla y para (o, si prefieres, cada pulsación la lanza una
sola vez).

Sirve para cualquier cosa que exija tener un botón apretado mucho rato o repetir la misma
pulsación cientos de veces: juegos, herramientas de dibujo, pruebas de interfaces, tareas
repetitivas de escritorio, o simplemente ahorrarle la muñeca a quien no puede estar
machacando el ratón.

### ⬇ [Descargar la última versión](https://github.com/Riiuk/Autoclicker/releases/latest)

Windows 10/11 de 64 bits · 7,8 MB · sin instalador ·
[todas las versiones](https://github.com/Riiuk/Autoclicker/releases)

- **Cero dependencias en tiempo de ejecución.** Todo sale de la biblioteca estándar de Python
  y de `ctypes` hablando con Win32 directamente. Nada de `pynput`, `keyboard` ni `pyautogui`.
- **No se queda pegado.** Nueve rutas distintas garantizan que ningún botón sobreviva a un
  cierre o a un fallo, y hay una tecla de pánico que funciona aunque la ventana esté colgada.
  Si el proceso muere de golpe (`taskkill /F`), basta con volver a abrir el programa: suelta
  todo al arrancar.
- **Avisa aunque la otra aplicación esté a pantalla completa**, con sonidos y un indicador
  flotante.
- **No es un keylogger**, y eso está garantizado por diseño, no por promesa. Ver
  [Privacidad](#privacidad).

## Instalar

Baja el `.zip` de la [última versión](https://github.com/Riiuk/Autoclicker/releases/latest),
descomprímelo y ejecuta **`Autoclicker\Autoclicker.exe`**. El ejecutable necesita la carpeta
`lib` que tiene al lado, así que muévelos siempre juntos.

No hay instalador y no toca el registro. Para desinstalar, borra la carpeta (y
`%APPDATA%\Autoclicker` si quieres llevarte también la configuración).

Cada versión publica el SHA-256 de sus ficheros en las notas de la release, por si quieres
comprobar que lo que has bajado es lo que se publicó.

## Cómo se usa

1. **Nueva** → ponle nombre, pulsa el botón **Tecla** y aprieta la tecla que quieras.
2. Elige la acción y acepta.
3. Deja el programa abierto —puede estar minimizado— y ve a lo tuyo. **Las macros siguen
   funcionando con la ventana minimizada.**

### Tipos de macro

| Tipo | Qué hace |
|---|---|
| **Mantener pulsado** | Deja el botón o la tecla apretados hasta que vuelvas a pulsar tu tecla. |
| **Clic automático** | Clics repetidos al ritmo que digas (clics/s o milisegundos), con variación aleatoria opcional para que no salgan clavados. |
| **Secuencia de pasos** | Lista de pasos —pulsar tecla, esperar, clic, soltar— que se repite N veces o sin parar. |

Cada macro elige además cómo se comporta su tecla: **interruptor** (una pulsación arranca, otra
para) o **un disparo por pulsación**.

Puedes crear hasta 200 macros, cada una con su tecla. Si dos intentan usar el mismo botón a la
vez, la segunda se rechaza diciéndote cuál lo tiene ocupado.

### Atajos de teclado

| Tecla | Qué hace |
|---|---|
| `Ctrl+N` | Nueva macro |
| `Intro` | Editar la macro seleccionada |
| `Supr` | Eliminar (pide confirmación) |
| `Espacio` | Habilitar / deshabilitar |
| `Ctrl+M` | Interruptor maestro (activar / parar todo) |
| `Esc` | Cancelar en cualquier diálogo, y cancelar la captura de tecla |
| `F12` | **Pánico** (configurable) |

## Si algo se queda pegado

**F12 suelta todo y para todas las macros al instante.** Funciona aunque la interfaz no
responda, porque no depende de ella: la tecla se atiende en el hook y lo único que hace es
levantar una bandera.

Y si aun así un botón se quedara pulsado, **un clic físico de verdad también lo suelta**. El
programa además suelta todo al arrancar, así que basta con volver a abrirlo.

## Si la aplicación de destino va como administrador

Windows no deja que un programa normal envíe clics a una ventana de administrador, y lo peor
es que **no avisa**: la macro se arma y no pasa nada. El programa detecta ese caso y lo dice.

Lo mejor es abrir la aplicación de destino sin permisos de administrador si no los necesita.
Si prefieres elevar el Autoclicker, **antes mueve su carpeta a `C:\Program Files\`**: en una
carpeta que cualquiera puede escribir, ejecutar como administrador es una puerta abierta a
que otro programa cuele una DLL a su lado.

## Si el antivirus se queja

Es un falso positivo previsible: cualquier programa que lea el teclado de forma global y
envíe clics se parece a un keylogger desde fuera. Por eso se distribuye como carpeta en vez
de un único `.exe` autoextraíble, sin comprimir con UPX y con los metadatos de versión
puestos, que es lo que menos sospechas levanta.

Si Windows Defender lo pone en cuarentena, añade la exclusión **al fichero `Autoclicker.exe`,
nunca a la carpeta entera**: una carpeta excluida deja sin escanear todo lo que se escriba
después en ella.

Para comprobar que tu copia es la que compilaste tú:

```powershell
Get-FileHash .\Autoclicker.exe -Algorithm SHA256
```

`build.ps1` imprime los SHA-256 del `.exe` y del zip al terminar cada compilación.

## Configuración

Todo se guarda en un fichero de texto que puedes editar a mano:

```
%APPDATA%\Autoclicker\config.json
```

(*Archivo → Abrir la carpeta de configuración* te lleva ahí.) El programa **nunca** revienta
por un fichero mal escrito: lo que no entiende lo marca como «No soportada», deshabilita esa
macro y te lo dice en la barra de estado. Eso sí, una macro «No soportada» ya no se vuelve a
guardar: en cuanto edites cualquier otra cosa desaparece del `config.json` —queda la copia
`config.json.bak`—, así que si quieres conservarla, sácala antes con *Archivo → Exportar*.

Ejemplo de una macro que mantiene el clic izquierdo:

```json
{
  "version": 1,
  "ajustes": { "hotkey_panico": {"sc": 88, "ext": 0, "vk": 123, "nombre": "F12"} },
  "macros": [
    {
      "id": "b3f1c8a2",
      "nombre": "Mantener clic izquierdo",
      "habilitada": true,
      "hotkey": {"sc": 66, "ext": 0, "vk": 119, "mods": 0, "nombre": "F8", "modo": "toggle"},
      "accion": {"tipo": "MANTENER", "objetivo": {"tipo": "raton", "boton": "izq"}}
    }
  ]
}
```

`sc` es el **scancode**: la posición física de la tecla, que no depende de la distribución
del teclado. `mods` es una máscara: 1 = Ctrl, 2 = Alt, 4 = Mayús. Una hotkey **sin**
modificadores dispara aunque tengas Mayús o Ctrl apretados; si exigiera lo contrario, dejaría
de responder en cuanto la aplicación de destino usara esas teclas para otra cosa.

El resto del formato:

| Campo | Valores |
|---|---|
| `hotkey.modo` | `"toggle"` (interruptor) o `"pulso"` (un disparo por pulsación) |
| `hotkey.tragar_tecla` | `true` para que la tecla no llegue a la otra aplicación. Hay teclas que **nunca** se tragan por accesibilidad: Tab, Bloq Mayús, Esc, Insert, Windows, F1 y las flechas |
| `accion.tipo` | `"MANTENER"`, `"CLIC_AUTO"` o `"SECUENCIA"` |
| `accion.objetivo` | `{"tipo":"raton","boton":"izq\|der\|medio\|x1\|x2"}` o `{"tipo":"tecla","vk":87}` |
| `CLIC_AUTO` | `intervalo_ms`, `jitter_intervalo_ms`, `duracion_ms`, `jitter_duracion_ms`, `repeticiones` (0 = sin parar) |
| `SECUENCIA` | `repeticiones` y `pasos`, con `op` igual a `tecla_abajo`, `tecla_arriba`, `clic` o `esperar` |
| `auto_soltar_min` | Suelta todo pasados N minutos. 0 = sin límite |
| `retardo_inicial_ms` | Espera antes de empezar |
| `ajustes` | `debounce_ms`, `seguir_foco`, `sonidos`, `indicador` |

Topes de seguridad del validador: 200 macros, 200 pasos por secuencia, 1 MB de fichero y 12
horas de auto-soltar.

## Privacidad

El programa instala un hook global de teclado (`WH_KEYBOARD_LL`), que técnicamente ve todo lo
que escribes en cualquier aplicación. La regla que lo separa de un keylogger está escrita en
el código y es lo primero que se lee en [`hotkeys.py`](hotkeys.py):

> La comparación contra las teclas registradas ocurre **dentro** del callback. Lo único que
> sale de ahí es el identificador de la macro. Ninguna tecla que no sea una de tus hotkeys se
> copia fuera del frame, ni se guarda, ni se registra, ni acaba en el mensaje de un error.

El fichero de errores (`%APPDATA%\Autoclicker\error.log`) redacta expresamente el texto de
cualquier excepción que venga del hook, por si arrastrara un código de tecla. No hay red, no
hay telemetría, no se manda nada a ninguna parte.

## Cómo está hecho

Python 3.9 + tkinter + `ctypes`/Win32. Unas 4.000 líneas de programa (5.000 contando las
pruebas) y ninguna dependencia en ejecución. Tres hilos en el camino de entrada —interfaz, hook
y motor—, más uno para los sonidos y otro efímero para guardar en disco.

| Fichero | Qué hace |
|---|---|
| `winapi.py` | Capa Win32: `SendInput` con buffer preasignado, tabla única de botones, temporizador de alta resolución, DPI, mutex, elevación. |
| `teclas.py` | Nombres legibles de tecla en español, identidad `(sc, ext)` y las teclas que nunca se tragan. |
| `hotkeys.py` | Hook `WH_KEYBOARD_LL` en su propio hilo con bucle de mensajes. Frontera cerrada, anti-autorepeat, captura acotada. |
| `motor.py` | Un solo hilo con scheduler cooperativo de generadores. `EstadoPulsado` es el dueño único de qué está pulsado. |
| `modelo.py` / `almacen.py` | Modelo, validador estricto y persistencia atómica. |
| `ui.py` / `ui_macro.py` / `indicador.py` | Interfaz ttk, diálogo de edición e indicador flotante. |
| `main.py` | Arranque y cableado: DPI, instancia única y redes de seguridad. |

El recorrido completo de una pulsación, las fronteras entre capas, los invariantes que no se
pueden romper y las recetas para los cambios más habituales están en
[`ARQUITECTURA.md`](ARQUITECTURA.md).

Tres decisiones que parecen raras y no lo son, explicadas al detalle en
[`DECISIONES.md`](DECISIONES.md):

- **Nunca se reafirma el botón mientras está mantenido.** Parece que falta un keep-alive,
  pero muchas aplicaciones tratan un segundo *button down* como el comienzo de una acción
  nueva y reinician el progreso de la que estaba a medias: «reforzar» la pulsación consigue
  justo lo contrario de lo que parece.
- **No se usa `Event.wait` para temporizar.** Medido en este intérprete se pasa 10,27 ms de
  mediana, y `timeBeginPeriod(1)` no lo arregla. El temporizador de alta resolución de Win32
  se pasa 0,13 ms.
- **El watchdog no reinstala el hook, solo lo detecta.** Un hook de bajo nivel se despacha al
  bucle de mensajes del hilo que lo instaló; reinstalarlo desde otro hilo devuelve un handle
  válido cuyo callback no se dispara nunca.

## Compilar

Hace falta Python 3.9 x64 en `C:\python39`. La única dependencia es PyInstaller, y solo para
compilar.

```powershell
.\build.ps1              # compila; deja dist\Autoclicker\ y dist\Autoclicker.zip
.\build.ps1 -Relock      # regenera requirements-build.lock (hace falta red)
```

`build.ps1` pasa las pruebas antes de compilar y aborta si alguna falla. El árbol completo de
dependencias de compilación va fijado con hashes en `requirements-build.lock`.

```powershell
C:\python39\python.exe -m unittest discover -s pruebas -t .   # la batería, sin ratón ni ventanas
C:\python39\python.exe motor_test.py                          # el motor sin interfaz, para depurar
```

Las pruebas cubren en headless lo que de otro modo exigiría probarlo a mano: el invariante de
que todo `down` acaba con su `up` tras parar o un pánico; la matemática de CPS y jitter; el
validador de configuración; la recuperación desde `.bak`; y el emparejamiento de teclas.

## Documentación

| | |
|---|---|
| [`ARQUITECTURA.md`](ARQUITECTURA.md) | Cómo funciona por dentro, los invariantes, las recetas para cambios habituales y qué falta por hacer. |
| [`DECISIONES.md`](DECISIONES.md) | Por qué está hecho así. Léelo antes de «arreglar» algo que parece raro. |
| [`CONTRIBUIR.md`](CONTRIBUIR.md) | Montar el entorno, ejecutar las pruebas, convenciones y cómo publicar una versión. |
| [`CHANGELOG.md`](CHANGELOG.md) | Qué cambió en cada versión. |

## Antes de usarlo

Automatizar entrada está prohibido en las condiciones de uso de bastantes juegos y servicios
en línea, y algunos lo detectan. Para tus propias cosas no hay problema; si es contra algo
de terceros, mírate sus reglas antes.

## Licencia

[MIT](LICENSE).
