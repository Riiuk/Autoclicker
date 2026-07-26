# -*- coding: utf-8 -*-
"""Diálogo modal de edición de una macro.

Lo que no es obvio:
  * La captura de tecla va por el hook, no por `bind` de Tk, porque hay teclas que Tk no ve.
    Por eso está acotada: de un solo disparo, Esc cancela, 10 s de timeout y desarme
    incondicional si el diálogo se cierra o pierde el foco. Durante la captura el hook NUNCA
    traga: si tragara, un lector de pantalla se quedaría mudo a mitad de diálogo.
  * "Probar 3 s" inyecta entrada REAL del sistema. Si nuestra ventana tiene el foco, los
    clics caerían sobre los propios botones del diálogo, así que no se inyecta: se cuenta
    atrás para que dé tiempo a poner el cursor donde toca, y si al terminar seguimos en
    primer plano, se avisa en vez de disparar.
  * Todo el contenido va en un canvas con scroll y la botonera vive fuera de él: a 150 % en
    un portátil de 1080p, si no, la fila Aceptar/Cancelar se sale de la pantalla y el diálogo
    deja de poder cerrarse con el ratón.
"""

import tkinter as tk
from tkinter import ttk

import modelo
import teclas
import winapi

TIMEOUT_CAPTURA_MS = 10000

ETIQUETAS_MODO = {"toggle": "Interruptor (pulsar para empezar, pulsar para parar)",
                  "pulso": "Un disparo por pulsación"}
MODO_POR_ETIQUETA = dict((v, k) for k, v in ETIQUETAS_MODO.items())

ETIQUETAS_OP = {modelo.OP_TECLA_ABAJO: "Pulsar tecla",
                modelo.OP_TECLA_ARRIBA: "Soltar tecla",
                modelo.OP_CLIC: "Clic",
                modelo.OP_ESPERAR: "Esperar"}
OP_POR_ETIQUETA = dict((v, k) for k, v in ETIQUETAS_OP.items())


def marco_desplazable(padre):
    """Canvas + frame interior con scroll vertical. Devuelve (contenedor, interior)."""
    contenedor = ttk.Frame(padre)
    contenedor.rowconfigure(0, weight=1)
    contenedor.columnconfigure(0, weight=1)
    lienzo = tk.Canvas(contenedor, highlightthickness=0)
    barra = ttk.Scrollbar(contenedor, orient="vertical", command=lienzo.yview)
    interior = ttk.Frame(lienzo)
    ventana = lienzo.create_window((0, 0), window=interior, anchor="nw")
    lienzo.configure(yscrollcommand=barra.set)
    lienzo.grid(row=0, column=0, sticky="nsew")
    barra.grid(row=0, column=1, sticky="ns")

    def _al_cambiar(_e=None):
        lienzo.configure(scrollregion=lienzo.bbox("all"))
        lienzo.itemconfigure(ventana, width=lienzo.winfo_width())

    interior.bind("<Configure>", _al_cambiar)
    lienzo.bind("<Configure>", _al_cambiar)

    # En Windows la rueda va al widget con el foco, no al de debajo del cursor, así que hace
    # falta `bind_all`. Se engancha al entrar y se suelta al salir: si no, el manejador
    # sobrevive al diálogo y peta con TclError la próxima vez que alguien mueva la rueda.
    def _rodar(evento):
        lienzo.yview_scroll(-1 * (evento.delta // 120), "units")

    interior.bind("<Enter>", lambda e: lienzo.bind_all("<MouseWheel>", _rodar))
    interior.bind("<Leave>", lambda e: lienzo.unbind_all("<MouseWheel>"))
    contenedor.bind("<Destroy>", lambda e: lienzo.unbind_all("<MouseWheel>"))
    return contenedor, interior


class DialogoMacro(tk.Toplevel):

    def __init__(self, app, macro, titulo="Editar macro"):
        tk.Toplevel.__init__(self, app.raiz)
        self.app = app
        self.original = macro
        self.macro = macro.copia_inmutable()
        self.resultado = None
        self._capturando = None       # None | "hotkey" | "objetivo" | "paso"
        self._tarea_timeout = None
        self._tarea_cuenta = None
        self._sincronizando = False

        self.title(titulo)
        self.transient(app.raiz)
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        contenedor, cuerpo = marco_desplazable(self)
        contenedor.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 0))
        self._construir_cuerpo(cuerpo)
        self._construir_pie()

        self._cargar_desde_macro()
        self._colocar()
        self.bind("<Escape>", lambda e: self._cancelar())
        self.bind("<Return>", self._al_intro)
        self.bind("<FocusOut>", lambda e: self._desarmar_captura("foco"))
        self.bind("<Unmap>", lambda e: self._desarmar_captura("minimizado"))
        self.grab_set()
        self.ent_nombre.focus_set()

    # ------------------------------------------------------------------ construcción
    def _fila(self, padre, fila, etiqueta):
        lb = ttk.Label(padre, text=etiqueta)
        lb.grid(row=fila, column=0, sticky="w", padx=(0, 8), pady=3)
        return lb

    def _describir(self, widget, texto):
        """Tk no asocia etiquetas con campos, así que se compensa: al enfocar un control se
        escribe qué es y cuánto vale en una línea fija."""
        widget.bind("<FocusIn>", lambda e, t=texto: self._decir(t), add="+")

    def _construir_cuerpo(self, c):
        c.columnconfigure(1, weight=1)
        fila = 0

        self._fila(c, fila, "Nombre:")
        self.var_nombre = tk.StringVar()
        self.ent_nombre = ttk.Entry(c, textvariable=self.var_nombre)
        self.ent_nombre.grid(row=fila, column=1, sticky="ew", pady=3)
        self._describir(self.ent_nombre, "Nombre de la macro")
        fila += 1

        # --- tecla ---
        self._fila(c, fila, "Tecla:")
        marco_tecla = ttk.Frame(c)
        marco_tecla.grid(row=fila, column=1, sticky="ew", pady=3)
        marco_tecla.columnconfigure(0, weight=1)
        self.var_tecla = tk.StringVar(value="(sin asignar)")
        self.btn_tecla = ttk.Button(marco_tecla, textvariable=self.var_tecla, underline=0,
                                    command=lambda: self._armar_captura("hotkey"))
        self.btn_tecla.grid(row=0, column=0, sticky="ew")
        self._describir(self.btn_tecla, "Tecla que activa la macro. Intro para cambiarla")
        fila += 1

        self._fila(c, fila, "Al pulsarla:")
        self.var_modo = tk.StringVar()
        self.cmb_modo = ttk.Combobox(c, textvariable=self.var_modo, state="readonly",
                                     values=list(ETIQUETAS_MODO.values()))
        self.cmb_modo.grid(row=fila, column=1, sticky="ew", pady=3)
        self._describir(self.cmb_modo, "Comportamiento de la tecla")
        fila += 1

        self.var_tragar = tk.BooleanVar()
        self.chk_tragar = ttk.Checkbutton(
            c, text="No dejar que la tecla llegue al juego (tragarla)",
            variable=self.var_tragar, command=self._al_cambiar_tragar)
        self.chk_tragar.grid(row=fila, column=1, sticky="w", pady=3)
        self._describir(self.chk_tragar, "Si se traga, el juego no verá esa tecla")
        fila += 1

        ttk.Separator(c, orient="horizontal").grid(row=fila, column=0, columnspan=2,
                                                   sticky="ew", pady=6)
        fila += 1

        # --- acción ---
        self._fila(c, fila, "Acción:")
        self.var_tipo = tk.StringVar()
        self.cmb_tipo = ttk.Combobox(c, textvariable=self.var_tipo, state="readonly",
                                     values=[modelo.ETIQUETAS_TIPO[t]
                                             for t in modelo.TIPOS_ACCION])
        self.cmb_tipo.grid(row=fila, column=1, sticky="ew", pady=3)
        self.cmb_tipo.bind("<<ComboboxSelected>>", lambda e: self._al_cambiar_tipo())
        self._describir(self.cmb_tipo, "Qué hace la macro")
        fila += 1

        self.marco_objetivo = ttk.Frame(c)
        self.marco_objetivo.grid(row=fila, column=0, columnspan=2, sticky="ew")
        self._construir_objetivo(self.marco_objetivo)
        fila += 1

        self.marco_clic = ttk.Frame(c)
        self.marco_clic.grid(row=fila, column=0, columnspan=2, sticky="ew")
        self._construir_clic(self.marco_clic)
        fila += 1

        self.marco_pasos = ttk.Frame(c)
        self.marco_pasos.grid(row=fila, column=0, columnspan=2, sticky="ew")
        self._construir_pasos(self.marco_pasos)
        fila += 1

        ttk.Separator(c, orient="horizontal").grid(row=fila, column=0, columnspan=2,
                                                   sticky="ew", pady=6)
        fila += 1

        self._fila(c, fila, "Soltar todo a los:")
        marco_dm = ttk.Frame(c)
        marco_dm.grid(row=fila, column=1, sticky="w", pady=3)
        self.var_auto = tk.StringVar(value="0")
        self.spn_auto = ttk.Spinbox(marco_dm, from_=0, to=modelo.MAX_AUTO_SOLTAR_MIN,
                                    width=6, textvariable=self.var_auto)
        self.spn_auto.grid(row=0, column=0)
        ttk.Label(marco_dm, text="minutos (0 = sin límite)").grid(row=0, column=1,
                                                                  padx=(6, 0))
        self._describir(self.spn_auto, "Seguro: suelta todo pasado ese tiempo")
        fila += 1

        self._fila(c, fila, "Esperar antes de empezar:")
        marco_ret = ttk.Frame(c)
        marco_ret.grid(row=fila, column=1, sticky="w", pady=3)
        self.var_retardo = tk.StringVar(value="0")
        self.spn_retardo = ttk.Spinbox(marco_ret, from_=0, to=60000, increment=100,
                                       width=8, textvariable=self.var_retardo)
        self.spn_retardo.grid(row=0, column=0)
        ttk.Label(marco_ret, text="ms").grid(row=0, column=1, padx=(6, 0))
        self._describir(self.spn_retardo, "Retardo inicial en milisegundos")

    def _construir_objetivo(self, m):
        m.columnconfigure(1, weight=1)
        ttk.Label(m, text="Sobre:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        interior = ttk.Frame(m)
        interior.grid(row=0, column=1, sticky="ew", pady=3)
        self.var_obj_tipo = tk.StringVar(value="raton")
        ttk.Radiobutton(interior, text="Botón del ratón", value="raton",
                        variable=self.var_obj_tipo,
                        command=self._al_cambiar_objetivo).grid(row=0, column=0)
        self.cmb_boton = ttk.Combobox(interior, state="readonly", width=18,
                                      values=[b.etiqueta for b in
                                              winapi.TABLA_BOTONES.values()])
        self.cmb_boton.grid(row=0, column=1, padx=(6, 16))
        self._describir(self.cmb_boton, "Botón del ratón que se va a usar")
        ttk.Radiobutton(interior, text="Tecla", value="tecla", variable=self.var_obj_tipo,
                        command=self._al_cambiar_objetivo).grid(row=0, column=2)
        self.var_obj_tecla = tk.StringVar(value="(ninguna)")
        self.btn_obj_tecla = ttk.Button(interior, textvariable=self.var_obj_tecla, width=16,
                                        command=lambda: self._armar_captura("objetivo"))
        self.btn_obj_tecla.grid(row=0, column=3, padx=(6, 0))
        self._describir(self.btn_obj_tecla, "Tecla que se mantendrá o pulsará")

    def _construir_clic(self, m):
        m.columnconfigure(1, weight=1)
        ttk.Label(m, text="Ritmo:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        interior = ttk.Frame(m)
        interior.grid(row=0, column=1, sticky="w", pady=3)
        self.var_cps = tk.StringVar(value="12")
        self.var_intervalo = tk.StringVar(value="83")
        self.spn_cps = ttk.Spinbox(interior, from_=1, to=100, width=6,
                                   textvariable=self.var_cps)
        self.spn_cps.grid(row=0, column=0)
        ttk.Label(interior, text="clics/s   =").grid(row=0, column=1, padx=6)
        self.spn_intervalo = ttk.Spinbox(interior, from_=1, to=60000, width=8,
                                         textvariable=self.var_intervalo)
        self.spn_intervalo.grid(row=0, column=2)
        ttk.Label(interior, text="ms entre clics").grid(row=0, column=3, padx=(6, 0))
        self.var_cps.trace_add("write", lambda *a: self._sincronizar("cps"))
        self.var_intervalo.trace_add("write", lambda *a: self._sincronizar("intervalo"))
        self._describir(self.spn_cps, "Clics por segundo")
        self._describir(self.spn_intervalo, "Milisegundos entre clic y clic")

        ttk.Label(m, text="Variación aleatoria (jitter):").grid(row=1, column=0, sticky="w",
                                                                padx=(0, 8), pady=3)
        int2 = ttk.Frame(m)
        int2.grid(row=1, column=1, sticky="w", pady=3)
        self.var_jit_int = tk.StringVar(value="0")
        self.spn_jit_int = ttk.Spinbox(int2, from_=0, to=5000, width=6,
                                       textvariable=self.var_jit_int)
        self.spn_jit_int.grid(row=0, column=0)
        ttk.Label(int2, text="ms sobre el intervalo").grid(row=0, column=1, padx=(6, 0))
        self._describir(self.spn_jit_int, "Cuánto puede variar el intervalo, arriba o abajo")

        ttk.Label(m, text="Duración de cada clic:").grid(row=2, column=0, sticky="w",
                                                         padx=(0, 8), pady=3)
        int3 = ttk.Frame(m)
        int3.grid(row=2, column=1, sticky="w", pady=3)
        self.var_duracion = tk.StringVar(value="30")
        self.spn_duracion = ttk.Spinbox(int3, from_=modelo.MIN_DURACION_MS, to=5000, width=6,
                                        textvariable=self.var_duracion)
        self.spn_duracion.grid(row=0, column=0)
        ttk.Label(int3, text="ms   ±").grid(row=0, column=1, padx=6)
        self.var_jit_dur = tk.StringVar(value="0")
        self.spn_jit_dur = ttk.Spinbox(int3, from_=0, to=5000, width=6,
                                       textvariable=self.var_jit_dur)
        self.spn_jit_dur.grid(row=0, column=2)
        ttk.Label(int3, text="ms").grid(row=0, column=3, padx=(6, 0))
        self._describir(self.spn_duracion,
                        "Cuánto se mantiene pulsado cada clic (mínimo %d ms)"
                        % modelo.MIN_DURACION_MS)

        ttk.Label(m, text="Repeticiones:").grid(row=3, column=0, sticky="w", padx=(0, 8),
                                                pady=3)
        int4 = ttk.Frame(m)
        int4.grid(row=3, column=1, sticky="w", pady=3)
        self.var_reps = tk.StringVar(value="0")
        self.spn_reps = ttk.Spinbox(int4, from_=0, to=modelo.MAX_REPETICIONES, width=8,
                                    textvariable=self.var_reps)
        self.spn_reps.grid(row=0, column=0)
        ttk.Label(int4, text="(0 = sin parar)").grid(row=0, column=1, padx=(6, 0))
        self._describir(self.spn_reps, "Cuántas veces repetir; 0 es indefinido")

    def _construir_pasos(self, m):
        m.columnconfigure(0, weight=1)
        self.arbol_pasos = ttk.Treeview(m, columns=("op", "detalle"), show="headings",
                                        height=5, selectmode="browse")
        self.arbol_pasos.heading("op", text="Operación")
        self.arbol_pasos.heading("detalle", text="Detalle")
        self.arbol_pasos.column("op", width=140, minwidth=100, stretch=False)
        self.arbol_pasos.column("detalle", width=220, minwidth=120, stretch=True)
        self.arbol_pasos.grid(row=0, column=0, sticky="ew", pady=3)
        barra = ttk.Scrollbar(m, orient="vertical", command=self.arbol_pasos.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.arbol_pasos.configure(yscrollcommand=barra.set)
        self._describir(self.arbol_pasos, "Lista de pasos de la secuencia")

        edicion = ttk.Frame(m)
        edicion.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        self.var_op = tk.StringVar(value=ETIQUETAS_OP[modelo.OP_ESPERAR])
        cmb = ttk.Combobox(edicion, textvariable=self.var_op, state="readonly", width=14,
                           values=list(ETIQUETAS_OP.values()))
        cmb.grid(row=0, column=0)
        cmb.bind("<<ComboboxSelected>>", lambda e: self._al_cambiar_op())
        self.var_paso_valor = tk.StringVar(value="100")
        self.spn_paso = ttk.Spinbox(edicion, from_=0, to=modelo.MAX_MS, width=8,
                                    textvariable=self.var_paso_valor)
        self.spn_paso.grid(row=0, column=1, padx=6)
        self.lbl_paso = ttk.Label(edicion, text="ms")
        self.lbl_paso.grid(row=0, column=2)
        self.cmb_paso_boton = ttk.Combobox(edicion, state="readonly", width=16,
                                           values=[b.etiqueta for b in
                                                   winapi.TABLA_BOTONES.values()])
        self.cmb_paso_boton.grid(row=0, column=3, padx=6)
        self.var_paso_tecla = tk.StringVar(value="(ninguna)")
        self.btn_paso_tecla = ttk.Button(edicion, textvariable=self.var_paso_tecla, width=14,
                                         command=lambda: self._armar_captura("paso"))
        self.btn_paso_tecla.grid(row=0, column=4, padx=6)

        botones = ttk.Frame(m)
        botones.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
        for texto, orden in (("Añadir", "añadir"), ("Reemplazar", "reemplazar"),
                             ("Quitar", "quitar"), ("Subir", "subir"), ("Bajar", "bajar")):
            ttk.Button(botones, text=texto, width=11,
                       command=lambda o=orden: self._editar_pasos(o)).pack(side="left",
                                                                          padx=(0, 4))
        self._pasos = []

    def _construir_pie(self):
        pie = ttk.Frame(self)
        pie.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        pie.columnconfigure(0, weight=1)
        self.var_estado = tk.StringVar(value="")
        # Línea fija: descripción del campo enfocado y errores de validación.
        ttk.Label(pie, textvariable=self.var_estado, anchor="w").grid(row=0, column=0,
                                                                     columnspan=4,
                                                                     sticky="ew",
                                                                     pady=(0, 6))
        self.btn_probar = ttk.Button(pie, text="Probar 3 s", command=self._probar)
        self.btn_probar.grid(row=1, column=0, sticky="w")
        ttk.Button(pie, text="Aceptar", command=self._aceptar).grid(row=1, column=2,
                                                                   padx=(0, 6))
        ttk.Button(pie, text="Cancelar", command=self._cancelar).grid(row=1, column=3)

    def _colocar(self):
        """Centra en el monitor del padre y recorta a su área de trabajo."""
        self.update_idletasks()
        x0, y0, ancho_t, alto_t = winapi.area_trabajo(self.app.raiz.winfo_id())
        ancho = min(self.winfo_reqwidth() + 24, ancho_t - 40)
        alto = min(self.winfo_reqheight() + 12, alto_t - 60)
        x = x0 + (ancho_t - ancho) // 2
        y = y0 + (alto_t - alto) // 2
        self.geometry("%dx%d+%d+%d" % (ancho, alto, x, y))
        self.minsize(min(480, ancho), min(320, alto))

    # ------------------------------------------------------------------ carga y volcado
    def _cargar_desde_macro(self):
        m = self.macro
        self.var_nombre.set(m.nombre)
        self.var_modo.set(ETIQUETAS_MODO.get(m.hotkey.modo, ETIQUETAS_MODO["toggle"]))
        self.var_tragar.set(m.hotkey.tragar_tecla)
        self._refrescar_tecla()
        self.var_tipo.set(modelo.ETIQUETAS_TIPO[m.accion.tipo])
        o = m.accion.objetivo
        self.var_obj_tipo.set(o.tipo)
        self.cmb_boton.set(winapi.TABLA_BOTONES[o.boton].etiqueta)
        self.var_obj_tecla.set(teclas.nombre_de_tecla(*teclas.scancode_desde_vk(o.vk), vk=o.vk)
                               if o.vk else "(ninguna)")
        self._obj_vk = o.vk
        a = m.accion
        self.var_intervalo.set(str(a.intervalo_ms))
        self.var_jit_int.set(str(a.jitter_intervalo_ms))
        self.var_duracion.set(str(a.duracion_ms))
        self.var_jit_dur.set(str(a.jitter_duracion_ms))
        self.var_reps.set(str(a.repeticiones))
        self.var_auto.set(str(m.auto_soltar_min))
        self.var_retardo.set(str(m.retardo_inicial_ms))
        self._pasos = [modelo.Paso(op=p.op, vk=p.vk, boton=p.boton, ms=p.ms,
                                   jitter_ms=p.jitter_ms, duracion_ms=p.duracion_ms)
                       for p in a.pasos]
        self._paso_vk = 0
        self.cmb_paso_boton.set(winapi.TABLA_BOTONES["izq"].etiqueta)
        self._refrescar_pasos()
        self._al_cambiar_tipo()
        self._al_cambiar_objetivo()
        self._al_cambiar_op()

    def _refrescar_tecla(self):
        hk = self.macro.hotkey
        self.var_tecla.set(teclas.descripcion_hotkey(hk) if hk.asignada()
                           else "(sin asignar) — pulsa aquí")

    def _refrescar_pasos(self):
        self.arbol_pasos.delete(*self.arbol_pasos.get_children())
        for i, p in enumerate(self._pasos):
            self.arbol_pasos.insert("", "end", iid=str(i),
                                    values=(ETIQUETAS_OP[p.op], self._detalle_paso(p)))

    @staticmethod
    def _detalle_paso(p):
        if p.op in (modelo.OP_TECLA_ABAJO, modelo.OP_TECLA_ARRIBA):
            sc, ext = teclas.scancode_desde_vk(p.vk)
            return teclas.nombre_de_tecla(sc, ext, p.vk)
        if p.op == modelo.OP_CLIC:
            return "%s, %d ms" % (winapi.TABLA_BOTONES[p.boton].etiqueta, p.duracion_ms)
        return "%d ms ±%d" % (p.ms, p.jitter_ms)

    # ------------------------------------------------------------------ reacciones
    def _decir(self, texto):
        self.var_estado.set(texto)

    def _al_cambiar_tipo(self):
        tipo = self._tipo_actual()
        self.marco_objetivo.grid_remove()
        self.marco_clic.grid_remove()
        self.marco_pasos.grid_remove()
        if tipo in (modelo.TIPO_MANTENER, modelo.TIPO_CLIC_AUTO):
            self.marco_objetivo.grid()
        if tipo == modelo.TIPO_CLIC_AUTO:
            self.marco_clic.grid()
        if tipo == modelo.TIPO_SECUENCIA:
            self.marco_pasos.grid()

    def _al_cambiar_objetivo(self):
        de_raton = self.var_obj_tipo.get() == "raton"
        self.cmb_boton.configure(state="readonly" if de_raton else "disabled")
        self.btn_obj_tecla.configure(state="disabled" if de_raton else "normal")

    def _al_cambiar_op(self):
        op = OP_POR_ETIQUETA[self.var_op.get()]
        es_tecla = op in (modelo.OP_TECLA_ABAJO, modelo.OP_TECLA_ARRIBA)
        self.btn_paso_tecla.configure(state="normal" if es_tecla else "disabled")
        self.cmb_paso_boton.configure(state="readonly" if op == modelo.OP_CLIC
                                      else "disabled")
        self.spn_paso.configure(state="disabled" if es_tecla else "normal")
        self.lbl_paso.configure(text="" if es_tecla else "ms")

    def _al_cambiar_tragar(self):
        if not self.var_tragar.get():
            return
        vk = self.macro.hotkey.vk
        if vk in teclas.RESERVADAS_NO_TRAGABLES:
            self.var_tragar.set(False)
            self._decir("«%s» no se puede tragar: el sistema y los lectores de pantalla "
                        "la necesitan." % teclas.nombre_de_tecla(
                            self.macro.hotkey.sc, self.macro.hotkey.ext, vk))

    def _sincronizar(self, origen):
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            if origen == "cps":
                cps = float(self.var_cps.get() or 0)
                if cps > 0:
                    ms = int(round(1000.0 / cps))
                    self.var_intervalo.set(str(ms))
                    self._decir("Ritmo: %s clics/s = %d ms entre clics" %
                                (self.var_cps.get(), ms))
            else:
                ms = float(self.var_intervalo.get() or 0)
                if ms > 0:
                    self.var_cps.set("%.10g" % round(1000.0 / ms, 2))
                    self._decir("Ritmo: %d ms entre clics = %s clics/s" %
                                (int(ms), self.var_cps.get()))
        except ValueError:
            pass
        finally:
            self._sincronizando = False

    def _tipo_actual(self):
        for clave, etiqueta in modelo.ETIQUETAS_TIPO.items():
            if etiqueta == self.var_tipo.get():
                return clave
        return modelo.TIPO_MANTENER

    def _boton_por_etiqueta(self, etiqueta):
        for clave, b in winapi.TABLA_BOTONES.items():
            if b.etiqueta == etiqueta:
                return clave
        return "izq"

    # ------------------------------------------------------------------ captura
    def _armar_captura(self, destino):
        self._desarmar_captura()
        self._capturando = destino
        self.app.armar_captura(self)
        self._decir("Pulsa una tecla…  (Esc cancela; se desarma solo en 10 s)")
        if destino == "hotkey":
            self.var_tecla.set("Pulsa una tecla…")
        self._tarea_timeout = self.after(TIMEOUT_CAPTURA_MS,
                                         lambda: self._desarmar_captura("tiempo agotado"))

    def _desarmar_captura(self, motivo=None):
        if self._tarea_timeout is not None:
            self.after_cancel(self._tarea_timeout)
            self._tarea_timeout = None
        if self._capturando is None:
            return
        self._capturando = None
        self.app.desarmar_captura()
        self._refrescar_tecla()
        if motivo:
            self._decir("Captura cancelada (%s). La tecla anterior sigue puesta." % motivo)

    def recibir_captura(self, datos):
        """Lo llama la ventana principal al drenar la cola. `datos` None = Esc."""
        destino = self._capturando
        self._desarmar_captura()
        if destino is None:
            return
        if datos is None:
            self._decir("Captura cancelada. La tecla anterior sigue puesta.")
            return
        sc, ext, vk = datos
        nombre = teclas.nombre_de_tecla(sc, ext, vk)
        if destino == "hotkey":
            self.macro.hotkey.sc = sc
            self.macro.hotkey.ext = ext
            self.macro.hotkey.vk = vk
            self.macro.hotkey.mods = 0
            self.macro.hotkey.nombre = nombre
            self._refrescar_tecla()
            self._al_cambiar_tragar()
            self.btn_tecla.focus_set()
            self._decir("Tecla asignada: %s" % nombre)
        elif destino == "objetivo":
            self._obj_vk = vk
            self.var_obj_tecla.set(nombre)
            self.btn_obj_tecla.focus_set()
            self._decir("Objetivo: %s" % nombre)
        else:
            self._paso_vk = vk
            self.var_paso_tecla.set(nombre)
            self.btn_paso_tecla.focus_set()
            self._decir("Tecla del paso: %s" % nombre)

    # ------------------------------------------------------------------ pasos
    def _editar_pasos(self, orden):
        sel = self.arbol_pasos.selection()
        indice = int(sel[0]) if sel else None
        if orden in ("añadir", "reemplazar"):
            paso = self._paso_desde_controles()
            if paso is None:
                return
            if orden == "añadir":
                self._pasos.append(paso)
                indice = len(self._pasos) - 1
            elif indice is not None:
                self._pasos[indice] = paso
        elif orden == "quitar" and indice is not None:
            del self._pasos[indice]
            indice = min(indice, len(self._pasos) - 1)
        elif orden in ("subir", "bajar") and indice is not None:
            destino = indice - 1 if orden == "subir" else indice + 1
            if 0 <= destino < len(self._pasos):
                self._pasos[indice], self._pasos[destino] = (self._pasos[destino],
                                                             self._pasos[indice])
                indice = destino
        self._refrescar_pasos()
        if indice is not None and 0 <= indice < len(self._pasos):
            self.arbol_pasos.selection_set(str(indice))

    def _paso_desde_controles(self):
        op = OP_POR_ETIQUETA[self.var_op.get()]
        if op in (modelo.OP_TECLA_ABAJO, modelo.OP_TECLA_ARRIBA):
            if not getattr(self, "_paso_vk", 0):
                self._decir("Elige primero la tecla del paso.")
                return None
            return modelo.Paso(op=op, vk=self._paso_vk)
        try:
            valor = int(self.var_paso_valor.get())
        except ValueError:
            self._decir("El valor del paso tiene que ser un número de milisegundos.")
            return None
        if op == modelo.OP_CLIC:
            if valor < modelo.MIN_DURACION_MS:
                self._decir("Un clic tiene que durar al menos %d ms."
                            % modelo.MIN_DURACION_MS)
                return None
            return modelo.Paso(op=op, boton=self._boton_por_etiqueta(
                self.cmb_paso_boton.get()), duracion_ms=valor)
        return modelo.Paso(op=op, ms=valor)

    # ------------------------------------------------------------------ probar
    def _probar(self):
        macro, error = self._recoger(validar_hotkey=False)
        if error:
            self._decir(error)
            return
        self.btn_probar.configure(state="disabled")
        self._cuenta_atras(3, macro)

    def _cuenta_atras(self, quedan, macro):
        if quedan > 0:
            self._decir("Probando en %d…  (pon el cursor donde quieras)" % quedan)
            self._tarea_cuenta = self.after(1000,
                                            lambda: self._cuenta_atras(quedan - 1, macro))
            return
        propio = winapi.ventana_primer_plano()
        if propio in (self.winfo_id(), self.app.raiz.winfo_id()):
            # Si inyectáramos ahora, los clics caerían sobre este mismo diálogo.
            self._decir("La prueba no se lanza con esta ventana en primer plano. "
                        "Cambia a la ventana destino y vuelve a probar.")
            self.btn_probar.configure(state="normal")
            return
        self._decir("Probando 3 segundos…")
        self.app.motor.probar(macro, 3.0)
        self.after(3200, lambda: (self.btn_probar.configure(state="normal"),
                                  self._decir("Prueba terminada.")))

    # ------------------------------------------------------------------ aceptar
    def _al_intro(self, evento):
        if isinstance(evento.widget, (ttk.Button, tk.Button)):
            return None          # Intro sobre un botón lo pulsa; no aceptamos el diálogo
        self._aceptar()
        return "break"

    def _recoger(self, validar_hotkey=True):
        """(Macro, error). Valida en la propia UI, además de en el motor."""
        m = self.macro.copia_inmutable()
        m.nombre = self.var_nombre.get().strip()
        if not m.nombre:
            return None, "Ponle un nombre a la macro."
        m.hotkey.modo = MODO_POR_ETIQUETA.get(self.var_modo.get(), "toggle")
        m.hotkey.tragar_tecla = bool(self.var_tragar.get())
        if validar_hotkey and not m.hotkey.asignada():
            return None, "Asigna una tecla: pulsa el botón «Tecla»."
        if m.hotkey.tragar_tecla and m.hotkey.vk in teclas.RESERVADAS_NO_TRAGABLES:
            return None, "Esa tecla no se puede tragar."

        tipo = self._tipo_actual()
        a = modelo.Accion(tipo=tipo)
        if tipo in (modelo.TIPO_MANTENER, modelo.TIPO_CLIC_AUTO):
            if self.var_obj_tipo.get() == "raton":
                a.objetivo = modelo.Objetivo(
                    tipo="raton", boton=self._boton_por_etiqueta(self.cmb_boton.get()))
            else:
                if not getattr(self, "_obj_vk", 0):
                    return None, "Elige la tecla sobre la que actúa la macro."
                a.objetivo = modelo.Objetivo(tipo="tecla", vk=self._obj_vk)
        if tipo == modelo.TIPO_CLIC_AUTO:
            try:
                a.intervalo_ms = int(self.var_intervalo.get())
                a.jitter_intervalo_ms = int(self.var_jit_int.get())
                a.duracion_ms = int(self.var_duracion.get())
                a.jitter_duracion_ms = int(self.var_jit_dur.get())
                a.repeticiones = int(self.var_reps.get())
            except ValueError:
                return None, "Los números del ritmo tienen que ser enteros."
            if a.duracion_ms < modelo.MIN_DURACION_MS:
                return None, ("Cada clic tiene que durar al menos %d ms para que el juego "
                              "lo vea." % modelo.MIN_DURACION_MS)
            minimo = a.duracion_ms + modelo.HOLGURA_INTERVALO_MS
            if a.intervalo_ms < minimo:
                return None, ("Con clics de %d ms, el intervalo no puede bajar de %d ms."
                              % (a.duracion_ms, minimo))
        if tipo == modelo.TIPO_SECUENCIA:
            if not self._pasos:
                return None, "Una secuencia necesita al menos un paso."
            a.pasos = list(self._pasos)
            try:
                a.repeticiones = int(self.var_reps.get())
            except ValueError:
                a.repeticiones = 0
        m.accion = a
        try:
            m.auto_soltar_min = int(self.var_auto.get())
            m.retardo_inicial_ms = int(self.var_retardo.get())
        except ValueError:
            return None, "Los minutos y el retardo tienen que ser números."
        m.soportada = True
        return m, None

    def _aceptar(self):
        macro, error = self._recoger()
        if error:
            self._decir(error)
            return
        choque = self.app.hotkey_en_conflicto(macro)
        if choque:
            self._decir(choque)
            return
        self.resultado = macro
        self._cerrar()

    def _cancelar(self):
        self.resultado = None
        self._cerrar()

    def _cerrar(self):
        self._desarmar_captura()
        if self._tarea_cuenta is not None:
            try:
                self.after_cancel(self._tarea_cuenta)
            except tk.TclError:
                pass
        self.grab_release()
        self.destroy()
