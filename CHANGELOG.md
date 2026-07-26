# Changelog

Todos los cambios reseñables del proyecto. Formato basado en
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/), y las versiones siguen
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Corregido

- Una macro que el validador marcaba como «No soportada» desaparecía del `config.json` en el
  siguiente guardado, porque solo se serializaban las que se habían entendido. Ahora se guarda
  su JSON original y se devuelve intacto al escribir, así que sobrevive tanto a un dedazo
  editando el fichero a mano como a volver a una versión anterior del programa.

### Cambiado

- Portada del README con enlace de descarga directo a la última release.
- Documentación de arquitectura, decisiones y contribución
  ([`ARQUITECTURA.md`](ARQUITECTURA.md), [`CONTRIBUIR.md`](CONTRIBUIR.md), este changelog).

## [1.0.0] — 2026-07-26

Primera versión.

### Añadido

- Tres tipos de macro: **mantener pulsado** (interruptor), **clic automático** con ritmo en
  clics/s o milisegundos y variación aleatoria, y **secuencias de pasos** repetibles.
- Objetivo configurable: cualquier botón del ratón o cualquier tecla.
- Hotkeys globales por posición física de la tecla, así que no dependen de la distribución del
  teclado. Opción de que la tecla no llegue a la aplicación de destino.
- Dos modos de hotkey: **interruptor** (pulsar para empezar, pulsar para parar) y **un disparo
  por pulsación**.
- **Interruptor maestro** (`Ctrl+M`) para activar o parar todas las macros de golpe.
- Botón **Probar** en el diálogo de macro: la ejecuta tres segundos, con cuenta atrás y sin
  disparar si la ventana del programa tiene el foco.
- Importar y exportar la configuración desde el menú Archivo.
- Vigilante del hook de teclado: si Windows lo tumba, se detecta y el hilo del hook lo
  reinstala solo.
- **Tecla de pánico** (F12 por defecto, reasignable) que suelta todo y para todas las macros
  aunque la interfaz no responda.
- Seguro de tiempo por macro: soltar todo pasados N minutos, avisando 10 segundos antes.
- Árbitro de recursos: dos macros no pueden pelearse por el mismo botón; la segunda se rechaza
  diciendo cuál lo tiene ocupado.
- Al perder el foco la aplicación de destino se suelta la entrada, y al recuperarlo se vuelve a
  pulsar solo lo que siga en marcha.
- Avisos que llegan con otra aplicación a pantalla completa: sonidos distintos por evento e
  indicador flotante con la macro activa.
- Interfaz en español operable solo con teclado, con espejo de estado en texto, acciones
  duplicadas en la barra de menú y confirmación al eliminar.
- Escalado de DPI por monitor y sin colores fijos: los tamaños de la ventana principal salen
  del ancho de carácter de la fuente, no de píxeles.
- Configuración en `%APPDATA%\Autoclicker\config.json`, editable a mano, con escritura atómica,
  copia de seguridad y validador que nunca revienta: lo que no entiende lo deshabilita, lo
  explica y deja de persistirlo.
- Detección de bloqueo por UIPI cuando la aplicación de destino va como administrador, que si
  no falla en silencio.
- Instancia única: al abrirlo dos veces, la segunda trae al frente la que ya estaba.
- 72 pruebas automáticas sin ratón ni ventanas.

### Detalles técnicos

- Sin dependencias en tiempo de ejecución: biblioteca estándar de Python y `ctypes` sobre Win32.
- Temporizador de alta resolución de Windows en lugar de `Event.wait`, que en este intérprete se
  pasa 10,27 ms de mediana frente a 0,13 ms.
- Un único hilo emisor de `SendInput` con scheduler cooperativo de generadores y vencimientos
  absolutos, para que no se acumule deriva.
- El hook de teclado compara dentro de su propio callback y no deja salir de ahí ningún código
  de tecla que no sea una hotkey registrada.
- Empaquetado con PyInstaller en modo carpeta, sin UPX y con metadatos de versión, para no
  disparar las heurísticas de los antivirus.

[Sin publicar]: https://github.com/Riiuk/Autoclicker/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Riiuk/Autoclicker/releases/tag/v1.0.0
