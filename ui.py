# -*- coding: utf-8 -*-
"""Ventana principal.

Reglas del layout, escritas para que no se improvisen por fichero:
  * `place()` está prohibido. Solo `grid`, y con pesos.
  * La única celda elástica es la del `Treeview`; botonera, interruptor y barra de estado son
    de alto fijo y ancho completo.
  * Ningún color fijo: el estado se dice con PALABRA y GLIFO, para que se entienda en modo de
    alto contraste y sin distinguir colores.
  * Todos los tamaños salen de las métricas de la fuente ya escalada por DPI, nunca de
    píxeles a pelo.
"""

import datetime
import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import almacen
import hotkeys
import modelo
import teclas
import ui_macro
import winapi
from indicador import Indicador, Sonidos

TITULO_BASE = "Autoclicker"
GLIFOS = {"marcha": "●", "habilitada": "○",
          "deshabilitada": "■", "rota": "⚠"}


def ruta_icono():
    """El mismo `.ico` para el recurso del ejecutable y para la ventana de Tk.

    En el build empaquetado los datos viven bajo `sys._MEIPASS`; ejecutando desde el código
    fuente, junto a este fichero.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    ruta = os.path.join(base, "assets", "autoclicker.ico")
    return ruta if os.path.exists(ruta) else None


class Aplicacion(object):

    def __init__(self, raiz, motor, hook, cfg, cola, avisos_inicio=()):
        self.raiz = raiz
        self.motor = motor
        self.hook = hook
        self.cfg = cfg
        self.cola = cola
        self.dialogo_captura = None
        self.guardado = almacen.GuardadoDiferido(al_fallar=self._fallo_guardado)
        self.sonidos = Sonidos(cfg.ajustes.sonidos)
        self.indicador = Indicador(raiz, cfg.ajustes.indicador)
        self._maestro_activo = True

        self._configurar_dpi()
        self._construir()
        self._refrescar_titulo()
        self._refrescar_lista()
        self.aplicar_a_motor()
        for aviso in avisos_inicio:
            self._anotar(aviso)
        self.raiz.after(30, self._drenar)
        self.raiz.after(400, self._refrescar_estado)

    # ------------------------------------------------------------------ DPI y estilo
    def _configurar_dpi(self):
        self.raiz.update_idletasks()
        dpi = winapi.dpi_de_ventana(self.raiz.winfo_id())
        self.escala = dpi / 96.0
        try:
            self.raiz.tk.call("tk", "scaling", dpi / 72.0)
        except tk.TclError:
            pass
        fuente = tkfont.nametofont("TkDefaultFont")
        self.alto_linea = fuente.metrics("linespace")
        self.ancho_car = fuente.measure("0")
        estilo = ttk.Style()
        # rowheight se congela al crear el estilo: si solo escalara la fuente, las filas
        # quedarían cortadas por arriba y por abajo a 150 %.
        estilo.configure("Treeview", rowheight=int(self.alto_linea * 1.5))
        estilo.configure("Maestro.TCheckbutton", font=(fuente.actual("family"),
                                                       int(fuente.actual("size") * 1.2),
                                                       "bold"))

    def _cars(self, n):
        return int(self.ancho_car * n)

    # ------------------------------------------------------------------ construcción
    def _construir(self):
        r = self.raiz
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)      # solo la lista crece
        icono = ruta_icono()
        if icono:
            try:
                r.iconbitmap(icono)
            except tk.TclError:
                pass
        self._construir_menu()

        marco_lista = ttk.Frame(r, padding=(8, 8, 8, 0))
        marco_lista.grid(row=0, column=0, sticky="nsew")
        marco_lista.columnconfigure(0, weight=1)
        marco_lista.rowconfigure(0, weight=1)

        self.arbol = ttk.Treeview(marco_lista, columns=("nombre", "tecla", "accion", "estado"),
                                  show="headings", selectmode="browse")
        for clave, texto, ancho, estira in (("nombre", "Nombre", 26, True),
                                            ("tecla", "Tecla", 14, False),
                                            ("accion", "Acción", 20, False),
                                            ("estado", "Estado", 16, False)):
            self.arbol.heading(clave, text=texto)
            self.arbol.column(clave, width=self._cars(ancho), minwidth=self._cars(8),
                              stretch=estira)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(marco_lista, orient="vertical", command=self.arbol.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.arbol.configure(yscrollcommand=barra.set)
        self.arbol.bind("<Double-1>", lambda e: self.editar())
        self.arbol.bind("<<TreeviewSelect>>", lambda e: self._refrescar_espejo())

        # Espejo en texto: un `Treeview` casi no se anuncia a las herramientas de
        # accesibilidad, y además es cómodo para leer la macro entera de un vistazo.
        self.var_espejo = tk.StringVar(value="")
        espejo = ttk.Entry(marco_lista, textvariable=self.var_espejo, state="readonly")
        espejo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.botonera = ttk.Frame(r, padding=(8, 8, 8, 0))
        self.botonera.grid(row=1, column=0, sticky="ew")
        self.botones = {}
        for i, (clave, texto, sub, orden) in enumerate((
                ("nueva", "Nueva", 0, self.nueva),
                ("editar", "Editar", 0, self.editar),
                ("duplicar", "Duplicar", 0, self.duplicar),
                ("alternar", "Habilitar/Deshabilitar", 0, self.alternar_habilitada))):
            b = ttk.Button(self.botonera, text=texto, underline=sub, command=orden)
            b.grid(row=0, column=i, padx=(0, 6))
            self.botones[clave] = b
        self.botonera.columnconfigure(4, weight=1)      # empuja Eliminar a la derecha
        self.botones["eliminar"] = ttk.Button(self.botonera, text="Eliminar", underline=0,
                                              command=self.eliminar)
        self.botones["eliminar"].grid(row=0, column=5, sticky="e")

        marco_maestro = ttk.Frame(r, padding=(8, 8, 8, 0))
        marco_maestro.grid(row=2, column=0, sticky="ew")
        marco_maestro.columnconfigure(1, weight=1)
        self.var_maestro = tk.BooleanVar(value=True)
        self.chk_maestro = ttk.Checkbutton(marco_maestro, style="Maestro.TCheckbutton",
                                           variable=self.var_maestro,
                                           command=self.alternar_maestro)
        self.chk_maestro.grid(row=0, column=0, sticky="w")
        ttk.Label(marco_maestro,
                  text="Las macros siguen funcionando con la ventana minimizada.",
                  anchor="e").grid(row=0, column=1, sticky="e")

        pie = ttk.Frame(r, padding=8)
        pie.grid(row=3, column=0, sticky="ew")
        pie.columnconfigure(0, weight=1)
        self.var_estado = tk.StringVar(value="Listo.")
        ttk.Label(pie, textvariable=self.var_estado, anchor="w").grid(row=0, column=0,
                                                                     sticky="ew")
        self.var_ayuda = tk.StringVar()
        ttk.Label(pie, textvariable=self.var_ayuda, anchor="w").grid(row=1, column=0,
                                                                    sticky="ew")

        r.bind("<Control-n>", lambda e: self.nueva())
        r.bind("<Control-m>", lambda e: (self.var_maestro.set(not self.var_maestro.get()),
                                         self.alternar_maestro()))
        self.arbol.bind("<Return>", lambda e: self.editar())
        self.arbol.bind("<Delete>", lambda e: self.eliminar())
        self.arbol.bind("<space>", lambda e: (self.alternar_habilitada(), "break")[1])
        self._refrescar_maestro()

        self.raiz.update_idletasks()
        ancho_min = self.botonera.winfo_reqwidth() + self._cars(6)
        alto_min = int(self.alto_linea * 16)
        self.raiz.minsize(ancho_min, alto_min)
        self.raiz.geometry("%dx%d" % (max(ancho_min, self._cars(78)),
                                      max(alto_min, int(self.alto_linea * 22))))

    def _construir_menu(self):
        barra = tk.Menu(self.raiz)
        archivo = tk.Menu(barra, tearoff=False)
        archivo.add_command(label="Nueva macro", accelerator="Ctrl+N", command=self.nueva)
        archivo.add_separator()
        archivo.add_command(label="Importar configuración…", command=self.importar)
        archivo.add_command(label="Exportar configuración…", command=self.exportar)
        archivo.add_command(label="Abrir la carpeta de configuración",
                            command=self.abrir_carpeta)
        archivo.add_separator()
        archivo.add_command(label="Salir", command=self.cerrar)
        barra.add_cascade(label="Archivo", menu=archivo)

        # Las mismas acciones también en el menú: el menú de Windows sí lo exponen las
        # herramientas de accesibilidad, al contrario que un Treeview.
        macro = tk.Menu(barra, tearoff=False)
        macro.add_command(label="Editar", accelerator="Intro", command=self.editar)
        macro.add_command(label="Duplicar", command=self.duplicar)
        macro.add_command(label="Habilitar / Deshabilitar", accelerator="Espacio",
                          command=self.alternar_habilitada)
        macro.add_separator()
        macro.add_command(label="Eliminar", accelerator="Supr", command=self.eliminar)
        barra.add_cascade(label="Macro", menu=macro)

        ejecucion = tk.Menu(barra, tearoff=False)
        ejecucion.add_command(label="Activar / Parar todo", accelerator="Ctrl+M",
                              command=lambda: (self.var_maestro.set(
                                  not self.var_maestro.get()), self.alternar_maestro()))
        ejecucion.add_command(label="Parar las macros en marcha",
                              command=self.motor.parar_todas)
        ejecucion.add_separator()
        ejecucion.add_command(label="Ajustes…", command=self.ajustes)
        barra.add_cascade(label="Ejecución", menu=ejecucion)

        ayuda = tk.Menu(barra, tearoff=False)
        ayuda.add_command(label="Cómo funciona", command=self.mostrar_ayuda)
        barra.add_cascade(label="Ayuda", menu=ayuda)
        self.raiz.configure(menu=barra)

    # ------------------------------------------------------------------ refrescos
    def _refrescar_titulo(self):
        self.raiz.title("%s — Pánico: %s" % (
            TITULO_BASE, teclas.descripcion_hotkey(self.cfg.ajustes.hotkey_panico)))
        self.var_ayuda.set(
            "Pánico: %s suelta todo y para las macros. Si un botón se queda pegado, un clic "
            "físico de verdad también lo suelta."
            % teclas.descripcion_hotkey(self.cfg.ajustes.hotkey_panico))

    def _refrescar_maestro(self):
        activo = self.var_maestro.get()
        self.chk_maestro.configure(
            text="%s  ACTIVO" % GLIFOS["marcha"] if activo else "%s  PARADO"
            % GLIFOS["deshabilitada"])

    def _estado_de(self, macro, en_marcha):
        if not macro.soportada:
            return "%s No soportada" % GLIFOS["rota"]
        if en_marcha:
            return "%s En marcha" % GLIFOS["marcha"]
        if macro.habilitada:
            return "%s Habilitada" % GLIFOS["habilitada"]
        return "%s Deshabilitada" % GLIFOS["deshabilitada"]

    def _refrescar_lista(self):
        seleccion = self.seleccionada_id()
        self.arbol.delete(*self.arbol.get_children())
        estados = self.motor.estado_macros()
        for m in self.cfg.macros:
            self.arbol.insert("", "end", iid=m.id, values=(
                m.nombre, teclas.descripcion_hotkey(m.hotkey),
                modelo.ETIQUETAS_TIPO.get(m.accion.tipo, m.accion.tipo),
                self._estado_de(m, estados.get(m.id, False))))
        if seleccion and self.arbol.exists(seleccion):
            self.arbol.selection_set(seleccion)
        elif self.cfg.macros:
            self.arbol.selection_set(self.cfg.macros[0].id)
        self._refrescar_espejo()
        self._refrescar_botones()

    def _refrescar_botones(self):
        hay = self.seleccionada() is not None
        for clave in ("editar", "duplicar", "alternar", "eliminar"):
            self.botones[clave].configure(state="normal" if hay else "disabled")
        if not hay and self.cfg.macros:
            self._decir("Selecciona una macro de la lista para editarla.")

    def _refrescar_espejo(self):
        m = self.seleccionada()
        if m is None:
            self.var_espejo.set("No hay ninguna macro seleccionada."
                                if self.cfg.macros else
                                "Todavía no hay macros. Pulsa «Nueva» (Ctrl+N).")
            self._refrescar_botones()
            return
        estados = self.motor.estado_macros()
        objetivo = ""
        if m.accion.tipo in (modelo.TIPO_MANTENER, modelo.TIPO_CLIC_AUTO):
            o = m.accion.objetivo
            objetivo = (winapi.TABLA_BOTONES[o.boton].etiqueta if o.tipo == "raton"
                        else "tecla " + teclas.nombre_de_tecla(
                            *teclas.scancode_desde_vk(o.vk), vk=o.vk))
        elif m.accion.pasos:
            objetivo = "%d pasos" % len(m.accion.pasos)
        self.var_espejo.set("%s — %s — %s%s — %s" % (
            m.nombre, teclas.descripcion_hotkey(m.hotkey),
            modelo.ETIQUETAS_TIPO.get(m.accion.tipo, m.accion.tipo),
            (" sobre " + objetivo) if objetivo else "",
            self._estado_de(m, estados.get(m.id, False))))
        self._refrescar_botones()

    def _refrescar_estado(self):
        estados = self.motor.estado_macros()
        for m in self.cfg.macros:
            if self.arbol.exists(m.id):
                self.arbol.set(m.id, "estado", self._estado_de(m, estados.get(m.id, False)))
        activas = [m.nombre for m in self.cfg.macros if estados.get(m.id)]
        if activas:
            self.indicador.mostrar("  ".join(activas))
        else:
            self.indicador.ocultar()
        self.raiz.after(400, self._refrescar_estado)

    def _decir(self, texto):
        self.var_estado.set(texto)

    def _anotar(self, texto):
        """Línea fechada: los cambios que ocurren solos tienen que dejar rastro."""
        self._decir("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), texto))

    def _fallo_guardado(self, error):
        self.raiz.after(0, lambda: self._anotar(error))

    # ------------------------------------------------------------------ cola
    def _drenar(self):
        try:
            for _ in range(64):
                tipo, dato = self.cola.get_nowait()
                self._atender(tipo, dato)
        except queue.Empty:
            pass
        except Exception:
            pass
        self.raiz.after(30, self._drenar)

    def _atender(self, tipo, dato):
        if tipo == "captura":
            if self.dialogo_captura is not None:
                self.dialogo_captura.recibir_captura(dato)
            return
        self.sonidos.evento(tipo)
        if tipo == "panico":
            self.var_maestro.set(False)
            self._refrescar_maestro()
            self._anotar(dato)
        elif tipo == "maestro":
            self._anotar("Interruptor maestro: %s" % dato)
        elif tipo == "arranca":
            self._anotar("En marcha: %s" % dato)
        elif tipo == "para":
            self._anotar("Parada: %s" % dato)
        elif tipo:
            self._anotar(dato)
        self._refrescar_espejo()

    # ------------------------------------------------------------------ acciones
    def seleccionada_id(self):
        sel = self.arbol.selection()
        return sel[0] if sel else None

    def seleccionada(self):
        i = self.seleccionada_id()
        return self.cfg.por_id(i) if i else None

    def nueva(self):
        macro = modelo.nueva_macro()
        dlg = ui_macro.DialogoMacro(self, macro, "Nueva macro")
        self.raiz.wait_window(dlg)
        if dlg.resultado is not None:
            self.cfg.macros.append(dlg.resultado)
            self.guardar_y_aplicar("Macro «%s» creada." % dlg.resultado.nombre,
                                   dlg.resultado.id)

    def editar(self):
        macro = self.seleccionada()
        if macro is None:
            return
        dlg = ui_macro.DialogoMacro(self, macro)
        self.raiz.wait_window(dlg)
        if dlg.resultado is not None:
            indice = self.cfg.macros.index(macro)
            dlg.resultado.id = macro.id
            self.cfg.macros[indice] = dlg.resultado
            self.guardar_y_aplicar("Macro «%s» guardada." % dlg.resultado.nombre, macro.id)

    def duplicar(self):
        macro = self.seleccionada()
        if macro is None:
            return
        copia = macro.copia_inmutable()
        copia.id = modelo.nueva_macro().id
        copia.nombre = macro.nombre + " (copia)"
        copia.habilitada = False        # sin tecla propia todavía: no debe competir
        copia.hotkey = modelo.Hotkey(modo=macro.hotkey.modo)
        self.cfg.macros.append(copia)
        self.guardar_y_aplicar("Duplicada. Asígnale una tecla y habilítala.", copia.id)

    def eliminar(self):
        macro = self.seleccionada()
        if macro is None:
            return
        vecinos = [m.id for m in self.cfg.macros if m.id != macro.id]
        indice = self.cfg.macros.index(macro)
        if not messagebox.askokcancel(
                "Eliminar macro",
                "¿Eliminar la macro «%s»?\n\nEsto no se puede deshacer." % macro.nombre,
                default=messagebox.CANCEL, icon=messagebox.WARNING, parent=self.raiz):
            return
        del self.cfg.macros[indice]
        # El foco no puede quedarse en el limbo: se va a la fila vecina.
        siguiente = vecinos[min(indice, len(vecinos) - 1)] if vecinos else None
        self.guardar_y_aplicar("Macro «%s» eliminada." % macro.nombre, siguiente)
        if siguiente is None:
            self.botones["nueva"].focus_set()
        else:
            self.arbol.focus_set()

    def alternar_habilitada(self):
        macro = self.seleccionada()
        if macro is None:
            return
        if not macro.soportada:
            self._decir("«%s» no se puede habilitar: %s" % (macro.nombre, macro.motivo))
            return
        if not macro.habilitada and not macro.hotkey.asignada():
            self._decir("Asígnale una tecla antes de habilitarla.")
            return
        macro.habilitada = not macro.habilitada
        self.guardar_y_aplicar("«%s»: %s." % (
            macro.nombre, "habilitada" if macro.habilitada else "deshabilitada"), macro.id)

    def alternar_maestro(self):
        activo = self.var_maestro.get()
        self._maestro_activo = activo
        self._refrescar_maestro()
        self.motor.activar_maestro(activo)

    def ajustes(self):
        DialogoAjustes(self)

    def mostrar_ayuda(self):
        messagebox.showinfo(
            "Cómo funciona",
            "1. Crea una macro con «Nueva» y asígnale una tecla.\n"
            "2. Deja el programa abierto (puede estar minimizado) y entra al juego.\n"
            "3. Pulsa tu tecla para arrancar la macro y vuélvela a pulsar para pararla.\n\n"
            "Pánico: %s suelta todo al instante, aunque la ventana no responda.\n"
            "Si un botón se queda pegado, un clic físico de verdad también lo suelta.\n\n"
            "Los avisos suenan aunque el juego esté a pantalla completa, y la macro activa "
            "aparece en una esquina de la pantalla.\n\n"
            "La configuración es un fichero de texto que puedes editar a mano:\n%s"
            % (teclas.descripcion_hotkey(self.cfg.ajustes.hotkey_panico),
               almacen.ruta_config() or "(no disponible)"), parent=self.raiz)

    def abrir_carpeta(self):
        carpeta = almacen.carpeta_config()
        if not carpeta:
            self._decir("No hay carpeta de configuración disponible.")
            return
        import os
        import subprocess
        try:
            os.makedirs(carpeta, exist_ok=True)
            subprocess.Popen(["explorer", carpeta])
        except OSError:
            self._decir("No se pudo abrir la carpeta.")

    def importar(self):
        ruta = filedialog.askopenfilename(parent=self.raiz, title="Importar configuración",
                                          filetypes=[("Configuración", "*.json"),
                                                     ("Todos", "*.*")])
        if not ruta:
            return
        bruto, error = almacen.leer_json(ruta)
        if error:
            self._anotar(error)
            return
        bruto, aviso = almacen.migrar(bruto)
        if aviso:
            self._anotar(aviso)
            return
        cfg, avisos = modelo.validar_config(bruto)   # el MISMO validador que el disco
        self.cfg = cfg
        for a in avisos:
            self._anotar(a)
        self._refrescar_titulo()
        self.guardar_y_aplicar("Configuración importada.")

    def exportar(self):
        ruta = filedialog.asksaveasfilename(parent=self.raiz, title="Exportar configuración",
                                            defaultextension=".json",
                                            filetypes=[("Configuración", "*.json")])
        if not ruta:
            return
        import json
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(modelo.config_a_json(self.cfg), f, ensure_ascii=False, indent=2)
            self._anotar("Configuración exportada.")
        except OSError as exc:
            self._anotar("No se pudo exportar (%s)." % type(exc).__name__)

    # ------------------------------------------------------------------ servicios
    def hotkey_en_conflicto(self, macro):
        """Texto del conflicto, o None. Se comprueba al guardar, no al ejecutar."""
        if macro.hotkey.clave == self.cfg.ajustes.hotkey_panico.clave:
            return ("Esa es la tecla de pánico (%s). Elige otra o cambia el pánico en "
                    "Ejecución → Ajustes."
                    % teclas.descripcion_hotkey(self.cfg.ajustes.hotkey_panico))
        for otra in self.cfg.macros:
            if otra.id == macro.id or not otra.habilitada:
                continue
            if (otra.hotkey.clave == macro.hotkey.clave
                    and otra.hotkey.mods == macro.hotkey.mods):
                return "Esa combinación ya la usa la macro «%s»." % otra.nombre
        return None

    def armar_captura(self, dialogo):
        self.dialogo_captura = dialogo
        self.hook.armar_captura()

    def desarmar_captura(self):
        self.hook.desarmar_captura()
        self.dialogo_captura = None

    def aplicar_a_motor(self):
        self.hook.registrar(hotkeys.registro_desde_macros(self.cfg.macros),
                            self.cfg.ajustes.hotkey_panico.clave)
        self.motor.aplicar_config(self.cfg)

    def guardar_y_aplicar(self, mensaje=None, seleccionar=None):
        self.aplicar_a_motor()
        self.guardado.pedir(self.cfg)     # solo en ediciones del usuario
        self._refrescar_lista()
        if seleccionar and self.arbol.exists(seleccionar):
            self.arbol.selection_set(seleccionar)
            self.arbol.see(seleccionar)
        if mensaje:
            self._anotar(mensaje)

    def cerrar(self):
        self.desarmar_captura()
        self.indicador.destruir()
        error = self.guardado.vaciar()
        if error:
            pass                          # ya no hay dónde enseñarlo; la app se está yendo
        self.raiz.destroy()


class DialogoAjustes(tk.Toplevel):

    def __init__(self, app):
        tk.Toplevel.__init__(self, app.raiz)
        self.app = app
        self.title("Ajustes")
        self.transient(app.raiz)
        self.resizable(False, False)
        self._capturando = False
        aj = app.cfg.ajustes

        c = ttk.Frame(self, padding=10)
        c.grid(sticky="nsew")
        c.columnconfigure(1, weight=1)

        ttk.Label(c, text="Tecla de pánico:").grid(row=0, column=0, sticky="w", pady=4)
        self.var_panico = tk.StringVar(value=teclas.descripcion_hotkey(aj.hotkey_panico))
        self.btn_panico = ttk.Button(c, textvariable=self.var_panico, command=self._capturar)
        self.btn_panico.grid(row=0, column=1, sticky="ew", pady=4)
        self._panico = modelo.Hotkey(sc=aj.hotkey_panico.sc, ext=aj.hotkey_panico.ext,
                                     vk=aj.hotkey_panico.vk, nombre=aj.hotkey_panico.nombre)

        ttk.Label(c, text="Tiempo mínimo entre pulsaciones (debounce):").grid(
            row=1, column=0, sticky="w", pady=4)
        self.var_debounce = tk.StringVar(value=str(aj.debounce_ms))
        ttk.Spinbox(c, from_=0, to=2000, increment=10, width=8,
                    textvariable=self.var_debounce).grid(row=1, column=1, sticky="w", pady=4)

        self.var_foco = tk.BooleanVar(value=aj.seguir_foco)
        ttk.Checkbutton(c, variable=self.var_foco,
                        text="Soltar todo al salir del juego y volver a pulsar al entrar"
                        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        self.var_sonidos = tk.BooleanVar(value=aj.sonidos)
        ttk.Checkbutton(c, variable=self.var_sonidos,
                        text="Avisar con sonidos (se oyen con el juego delante)"
                        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        self.var_indicador = tk.BooleanVar(value=aj.indicador)
        ttk.Checkbutton(c, variable=self.var_indicador,
                        text="Mostrar la macro activa en una esquina de la pantalla"
                        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)

        self.var_msg = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.var_msg).grid(row=5, column=0, columnspan=2,
                                                     sticky="w", pady=(8, 4))
        botones = ttk.Frame(c)
        botones.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(botones, text="Aceptar", command=self._aceptar).grid(row=0, column=0,
                                                                       padx=(0, 6))
        ttk.Button(botones, text="Cancelar", command=self._cerrar).grid(row=0, column=1)

        self.bind("<Escape>", lambda e: self._cerrar())
        self.bind("<Return>", lambda e: self._aceptar())
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.bind("<FocusOut>", lambda e: self._desarmar())
        self.grab_set()
        self.btn_panico.focus_set()

    def _capturar(self):
        self._capturando = True
        self.app.armar_captura(self)
        self.var_panico.set("Pulsa una tecla…")
        self.var_msg.set("Esc cancela. Se desarma solo en 10 s.")
        self.after(ui_macro.TIMEOUT_CAPTURA_MS, self._desarmar)

    def _desarmar(self):
        if not self._capturando:
            return
        self._capturando = False
        self.app.desarmar_captura()
        self.var_panico.set(teclas.descripcion_hotkey(self._panico))

    def recibir_captura(self, datos):
        armado = self._capturando
        self._desarmar()
        if not armado or datos is None:
            return
        sc, ext, vk = datos
        self._panico = modelo.Hotkey(sc=sc, ext=ext, vk=vk,
                                     nombre=teclas.nombre_de_tecla(sc, ext, vk))
        self.var_panico.set(teclas.descripcion_hotkey(self._panico))
        self.var_msg.set("")

    def _aceptar(self):
        for m in self.app.cfg.macros:
            if m.habilitada and m.hotkey.clave == self._panico.clave:
                self.var_msg.set("Esa tecla ya la usa la macro «%s»." % m.nombre)
                return
        try:
            debounce = int(self.var_debounce.get())
        except ValueError:
            self.var_msg.set("El debounce tiene que ser un número de milisegundos.")
            return
        aj = self.app.cfg.ajustes
        aj.hotkey_panico = self._panico
        aj.debounce_ms = max(0, min(2000, debounce))
        aj.seguir_foco = self.var_foco.get()
        aj.sonidos = self.var_sonidos.get()
        aj.indicador = self.var_indicador.get()
        self.app.sonidos.activos = aj.sonidos
        self.app.indicador.activo = aj.indicador
        if not aj.indicador:
            self.app.indicador.ocultar()
        self.app._refrescar_titulo()
        self.app.guardar_y_aplicar("Ajustes guardados.")
        self._cerrar()

    def _cerrar(self):
        self._desarmar()
        self.grab_release()
        self.destroy()
