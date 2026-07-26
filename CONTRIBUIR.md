# Trabajar en este proyecto

Guía práctica: montar el entorno, ejecutar las pruebas, las convenciones que sigue el código y
cómo publicar una versión. Para entender cómo funciona por dentro, primero
[`ARQUITECTURA.md`](ARQUITECTURA.md).

Esto es una herramienta personal: los issues se leen, los pull requests se valoran caso a caso
y van contra `main`.

## Montar el entorno

Hace falta **Python 3.9 x64** en `C:\python39` y Windows 10/11. No hay que instalar nada más
para desarrollar: el programa no tiene dependencias en tiempo de ejecución.

```powershell
git clone https://github.com/Riiuk/Autoclicker
cd Autoclicker
C:\python39\python.exe main.py                       # arrancar desde el código fuente
C:\python39\python.exe -m unittest discover -s pruebas -t .
```

El entorno virtual (`.venv`) solo hace falta para compilar el `.exe`, y lo crea `build.ps1`
solo la primera vez.

> Si tu Python está en otro sitio, pásaselo al compilar: `.\build.ps1 -Python C:\ruta\python.exe`.
> Si la ruta por defecto no existe, el script coge el `python` del PATH y avisa. El código no
> depende de ninguna ruta concreta.

## Pruebas

72 pruebas que corren en menos de un segundo, sin ratón, sin ventanas y sin tocar tu
configuración: solo lecturas de Win32 (`MapVirtualKey` y compañía) y ficheros en un directorio
temporal. Cubren lo que de otro modo habría que comprobar a mano una y otra vez:

| Fichero | Qué asegura |
|---|---|
| `test_motor.py` | El invariante de suelta, la temporización sin deriva, el jitter dentro de rango, el árbitro, el dead-man y el alt-tab. |
| `test_modelo.py` | Que el validador nunca lanza, degrada bien, la ida y vuelta a JSON conserva las macros y el cálculo de recursos para el árbitro. |
| `test_almacen.py` | Escritura atómica, recuperación desde `.bak`, migración, BOM, rotación del registro, redacción de mensajes del hook y el guardado diferido. |
| `test_hotkeys.py` | El emparejamiento de modificadores y la construcción del registro. |
| `test_teclas.py` | Identidad `(sc, ext)`, nombres en español, la tabla única de botones y las teclas reservadas que nunca se tragan. |

Lo que las hace posibles son dos costuras que hay que respetar: **`Motor(inyector, reloj)`**.
`pruebas/falso.py` le pasa un `InyectorFalso` que apunta cada evento en vez de mandarlo a
Windows, y un `RelojFalso` con tiempo virtual, que es lo que permite simular doce horas de
sesión en milisegundos.

Si añades algo al motor, la prueba mínima es siempre la misma: arrancarlo, pararlo y comprobar
que `iny.pendientes()` está vacío.

### Integración continua

Cada push a `main` y cada pull request lanzan
[`.github/workflows/pruebas.yml`](.github/workflows/pruebas.yml) sobre una máquina Windows
limpia. Son dos trabajos:

- **Batería en Windows** — importa los nueve módulos con un Python recién instalado y **sin
  hacer un solo `pip install`**, que es la forma honesta de comprobar que sigue sin
  dependencias en ejecución; luego ejecuta las pruebas.
- **Compilar el .exe** — solo si pasa el anterior. Corre `build.ps1` completo y sube el
  resultado como artefacto descargable durante 14 días. Coge fallos de empaquetado, que no se
  ven ejecutando desde el código fuente.

Si algo se rompe sale un aspa roja en el commit y llega un correo. Lo que falle ahí y no en tu
máquina suele ser una dependencia de tu entorno que no está declarada.

### Lo que las pruebas no cubren

Hay cosas que no se pueden verificar sin ojos y sin la aplicación de destino delante. Antes de
publicar una versión, a mano:

1. Una macro de mantener pulsado sobre una aplicación real, **en ventana, sin bordes y a
   pantalla completa**.
2. Alt-tab con la macro activa: se suelta al salir y se repulsa al entrar. Con el pánico
   disparado estando fuera, al volver **no** debe repulsar.
3. Pánico (F12) con todo corriendo.
4. `taskkill /F` con un botón mantenido, y reabrir: el ratón tiene que quedar usable.
5. La ventana al **100 %, 150 % y 200 %** de escalado, en tamaño mínimo, maximizada y en modo
   de alto contraste.
6. El `.exe` compilado, repitiendo lo anterior.

## Convenciones

**Identificadores de dominio, textos de la interfaz y claves del JSON en español. Nombres,
constantes y flags de Win32 literales de MSDN.** Es decir `MANTENER`, `EstadoPulsado`,
`tecla_abajo`, pero `SendInput`, `KEYEVENTF_SCANCODE`, `WH_KEYBOARD_LL`. Lo que hay que evitar
es mezclar los dos idiomas *dentro* de un mismo enum: esos valores están persistidos en el
`config.json` de la gente y renombrarlos después es una migración.

- Líneas de 99 columnas. Hoy hay una sola excepción, `hotkeys.py:136`, de 103; si la tocas,
  pártela.
- Nada de dependencias nuevas en tiempo de ejecución. Es la característica del proyecto, no una
  casualidad.
- `place()` está prohibido en la interfaz: los diseños van con `grid` y pesos. `pack()` se
  tolera en botoneras pequeñas de una sola fila (`ui_macro`, `indicador`).
- Ningún color fijo: el estado se dice con palabra **y** glifo, para que funcione en alto
  contraste y sin distinguir colores.
- Los comentarios explican **por qué**, no qué. Si un comentario se limita a repetir la línea de
  abajo, sobra.
- Las decisiones no obvias van a [`DECISIONES.md`](DECISIONES.md) con su porqué. Ese fichero es
  el que evita que dentro de un año alguien «arregle» algo que estaba bien.

## Antes de hacer commit

```powershell
C:\python39\python.exe -m unittest discover -s pruebas -t .
```

Y comprobar que sigue arrancando: `C:\python39\python.exe main.py`.

Mensajes de commit en inglés siguiendo [Conventional Commits](https://www.conventionalcommits.org):
`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## Publicar una versión

1. Actualizar [`CHANGELOG.md`](CHANGELOG.md).
2. Subir el número en `version_info.txt` (`filevers`, `prodvers`, `FileVersion`,
   `ProductVersion`).
3. Compilar. El script pasa las pruebas primero y aborta si alguna falla:
   ```powershell
   .\build.ps1
   ```
4. Probar el `.exe` de `dist\Autoclicker\` con la lista manual de más arriba.
5. Etiquetar, renombrar el zip y publicar:
   ```powershell
   git tag -a v1.1.0 -m "v1.1.0"
   git push origin main --tags
   Copy-Item dist\Autoclicker.zip dist\Autoclicker-v1.1.0-win64.zip
   gh release create v1.1.0 dist\Autoclicker-v1.1.0-win64.zip --title "v1.1.0" --notes-file notas.md
   ```
   En las notas van los SHA-256 que imprime `build.ps1`, para que quien descargue pueda
   comprobar que el binario es el publicado.

El enlace de descarga del README apunta a `releases/latest`, así que **no hay que tocarlo** al
sacar una versión nueva.

### Si cambian las dependencias de compilación

`requirements-build.lock` fija el árbol completo con hashes. Para regenerarlo:

```powershell
.\build.ps1 -Relock
```

Y se commitea el lock resultante. Si la instalación no coincide con los hashes, el build aborta
en vez de seguir con algo que no es lo que se revisó.

## Dónde tocar cada cosa

Un mapa rápido; las recetas completas están en
[`ARQUITECTURA.md`](ARQUITECTURA.md#recetas).

| Quiero… | Fichero |
|---|---|
| Añadir un botón de ratón | `winapi.py` (una línea en `TABLA_BOTONES`) |
| Añadir un tipo de acción | `modelo.py` + `motor.py` + `ui_macro.py` + `ui.py` + `pruebas/test_motor.py` ([receta completa](ARQUITECTURA.md#recetas)) |
| Añadir un ajuste | `modelo.py` + `ui.py` |
| Cambiar cómo se detectan las teclas | `hotkeys.py` |
| Cambiar nombres de teclas o las reservadas | `teclas.py` |
| Cambiar la temporización | `winapi.RelojWin32` y `motor.Motor._paso` |
| Cambiar la ventana principal | `ui.py` |
| Cambiar el diálogo de macro | `ui_macro.py` |
| Cambiar el empaquetado | `autoclicker.spec` y `build.ps1` |
| Regenerar el icono | `python assets\generar_icono.py` |
