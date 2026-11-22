"""Interfaz de presentación. Ninguna tarea de red se ejecuta en el hilo Tkinter."""
from pathlib import Path
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from rpa.config import Settings
from rpa.demo_actions import DemoActions
from rpa.gmail_auth import authorize_with_audit
from rpa.gmail_campaign import load, summary, send_preview
from rpa.runtime import RPAError, profile_lock
from rpa.scenarios import CONTENT, TECHNICAL, ScenarioConfig, preset, save_config, load_config

ROOT = Path(__file__).resolve().parent
PRESETS = {'Rápida: 12 / 3 especiales':'quick', 'Real: 24 / 6 especiales':'real',
           'Carga local: 300 / 60 especiales':'load', 'Estrés local: 1.000 / 200 especiales':'stress',
           'Personalizado':None}
ERRORS = {
    'SCENARIO_TOTAL_MISMATCH':'El total debe ser normales + especiales (máximo local 1.000; Gmail 500).',
    'SCENARIO_QUANTITY_INVALID':'Usa cantidades enteras sin valores negativos.',
    'SCENARIO_DISTRIBUTION_MISMATCH':'La suma de escenarios debe coincidir con la cantidad de especiales.',
    'SCENARIO_SEND_LIMIT_INVALID':'Revisa el intervalo (1–60 segundos) y el máximo de intentos (1–total).',
    'TECHNICAL_SCENARIOS_LOCAL_ONLY':'Los fallos técnicos solo se permiten en simulación local.',
    'SIMULATION_MODE_REQUIRED':'Selecciona SIMULATION para ejecutar la prueba local.',
    'CAMPAIGN_CONFIG_MISMATCH':'Para preparar Gmail selecciona modalidad GMAIL y un máximo de 500.',
    'CAMPAIGN_REVIEW_REQUIRED':'Hay un envío incierto o bloqueado. Revisa recepción antes de continuar.',
    'AUTH_REQUIRED':'Autoriza la cuenta correspondiente desde Inicio.',
    'AUTH_TRANSIENT':'No se pudo comprobar la autorización por un problema de conexión.',
    'CAMPAIGN_RETRY_NOT_DUE':'Todavía no se cumple la espera de esta campaña.',
    'PROFILE_BUSY':'Otra tarea está usando estos datos. Espera a que termine.',
    'RESUME_ANALYSIS_FIRST':'Hay una lectura incompleta. Usa Solo analizar para continuar.',
    'BUDGET_EXHAUSTED':'Se agotó el tiempo permitido. El avance se conservó y requiere revisión.',
    'SCENARIO_CONFIG_NAME_INVALID':'El nombre permite letras sin tildes, números, guion y guion bajo.',
}


def friendly_error(code):
    return ERRORS.get(code, 'La tarea se detuvo. Consulta los logs. Código: '+code)


class DemoWindow:
    def __init__(self, window, settings):
        self.window,self.s,self.actions=window,settings,DemoActions(settings)
        self.messages,self.stop=queue.Queue(),threading.Event()
        self.busy,self.presentation=False,False
        self.report_path,self.campaign_id,self.last_result=None,None,None
        self.logs_path=settings.runtime/'logs'
        self.controls,self.inputs,self.campaigns,self.history=[],[],[],[]
        self.recent_events=[]
        self.live_received=0
        window.title('RPA EP3 · Presentación y pruebas')
        width,height=min(1160,window.winfo_screenwidth()-40),min(900,window.winfo_screenheight()-90)
        window.geometry(f'{width}x{height}');window.minsize(min(980,width),min(600,height))
        style=ttk.Style(window);style.theme_use('clam')
        style.configure('Title.TLabel',font=('Segoe UI',20,'bold'))
        style.configure('Count.TLabel',font=('Segoe UI',15,'bold'));style.configure('TButton',padding=6)
        root=ttk.Frame(window,padding=14);root.pack(fill='both',expand=True)
        header=ttk.Frame(root);header.pack(fill='x')
        ttk.Label(header,text='Gestión y pruebas de correos',style='Title.TLabel').pack(side='left')
        ttk.Button(header,text='Modo PRESENTACIÓN',command=self.toggle_presentation).pack(side='right')
        self.selected=tk.StringVar(value='Campaña: ninguna');self.stage=tk.StringVar(value='Selecciona una operación')
        self.status=tk.StringVar(value='Lista. Preparar y simular no envían correos.')
        self.counters=tk.StringVar(value='Preparados: 0   Aceptados: 0   Recibidos: 0   Clasificados: 0')
        self.special_counts=tk.StringVar(value='Especiales: 0   Comprobados: 0   Pendientes: 0')
        for var,style_name in [(self.selected,'TLabel'),(self.counters,'Count.TLabel'),(self.special_counts,'TLabel'),(self.stage,'TLabel')]:
            ttk.Label(root,textvariable=var,style=style_name,wraplength=1100).pack(anchor='w',pady=3)
        self.progress=ttk.Progressbar(root,maximum=100);self.progress.pack(fill='x',pady=4)
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,pady=6)
        self.pages=[]
        for title in ('1 Inicio','2 Simulación y cantidades','3 Preparar Gmail','4 Envío','5 Recepción','6 Excel e historial','7 Auditoría'):
            frame=ttk.Frame(self.tabs,padding=12);self.tabs.add(frame,text=title);self.pages.append(frame)
        self.build_sections()
        self.details=tk.Text(root,height=7,wrap='word',font=('Consolas',10));self.details.pack(fill='x',pady=6)
        footer=ttk.Frame(root);footer.pack(fill='x')
        for text,cmd in [('Abrir Excel',self.open_report),('Consultar logs',lambda:self.open_path(self.logs_path)),
                         ('Estado de Supabase',self.check_connections),('Resultados anteriores',self.show_history)]:
            ttk.Button(footer,text=text,command=cmd).pack(side='left',padx=3)
        self.stop_button=ttk.Button(footer,text='Detener nuevos envíos',command=self.stop.set,state='disabled');self.stop_button.pack(side='left',padx=3)
        status_label=ttk.Label(root,textvariable=self.status,wraplength=width-30)
        status_label.pack(side='bottom',fill='x',pady=5,before=self.tabs)
        footer.pack_forget();footer.pack(side='bottom',fill='x',before=self.tabs)
        self.details.pack_forget();self.details.pack(side='bottom',fill='x',pady=6,before=self.tabs)
        self.apply_config(preset('real'));self.preset_choice.set(list(PRESETS)[1])
        self.refresh_saved();self.refresh_campaigns();self.refresh_history()
        window.protocol('WM_DELETE_WINDOW',self.close);self.after_id=window.after(200,self.tick)

    def button(self,parent,text,command):
        button=ttk.Button(parent,text=text,command=command);self.controls.append(button);return button

    def field(self,parent,label,var,row,col=0,width=10):
        ttk.Label(parent,text=label).grid(row=row,column=col,sticky='w',padx=4,pady=3)
        widget=ttk.Entry(parent,textvariable=var,width=width);widget.grid(row=row,column=col+1,sticky='w',padx=4,pady=3)
        self.inputs.append((widget,'normal'));return widget

    def combo(self,parent,values=(),width=40,variable=None):
        widget=ttk.Combobox(parent,state='readonly',values=values,width=width,textvariable=variable)
        self.inputs.append((widget,'readonly'));return widget

    def build_sections(self):
        page=self.pages[0]
        ttk.Label(page,text='Remitente: '+(self.s.gmail_sender_address or 'Sin configurar')+'\nReceptor: '+(self.s.gmail_receiver_address or 'Sin configurar')).pack(anchor='w')
        self.connection_text=tk.StringVar(value='Estado no consultado. La revisión local no modifica tokens ni consulta servicios.')
        ttk.Label(page,textvariable=self.connection_text,wraplength=1050).pack(anchor='w',pady=12)
        for text,cmd in [('Revisar estado local',self.check_connections),('Autorizar remitente',lambda:self.authorize('remitente')),('Autorizar receptor',lambda:self.authorize('receptor'))]:
            self.button(page,text,cmd).pack(anchor='w',pady=4)
        ttk.Label(page,text='El estado local no demuestra disponibilidad remota. Autorizar abre Google.').pack(anchor='w',pady=8)
        self.build_configuration()
        page=self.pages[2]
        ttk.Label(page,text='Usa la configuración de la sección 2 en modalidad GMAIL. Máximo: 500 por campaña.').pack(anchor='w')
        self.button(page,'Preparar campaña (sin enviar)',self.prepare).pack(anchor='w',pady=6)
        self.selector=self.combo(page,width=95);self.selector.pack(fill='x');self.selector.bind('<<ComboboxSelected>>',self.select_campaign)
        bar=ttk.Frame(page);bar.pack(fill='x',pady=6)
        self.button(bar,'Actualizar campañas',self.refresh_campaigns).pack(side='left')
        self.button(bar,'VISTA PREVIA',self.preview).pack(side='left',padx=8)
        self.preview_tree=ttk.Treeview(page,columns=('n','type','category','subject'),show='headings',height=8)
        for key,title,width in [('n','Nº',45),('type','Escenario',130),('category','Esperada',110),('subject','Asunto único',650)]:
            self.preview_tree.heading(key,text=title);self.preview_tree.column(key,width=width,stretch=key=='subject')
        scroll=ttk.Scrollbar(page,command=self.preview_tree.yview);scroll.pack(side='right',fill='y')
        self.preview_tree.configure(yscrollcommand=scroll.set);self.preview_tree.pack(fill='both',expand=True)
        page=self.pages[3];self.send_interval,self.send_limit=tk.StringVar(value='1'),tk.StringVar(value='24')
        self.field(page,'Intervalo entre envíos (1–60 segundos)',self.send_interval,0)
        self.field(page,'Máximo de mensajes a intentar ahora',self.send_limit,1)
        self.button(page,'Enviar tanda y analizar / continuar',self.send).grid(row=2,column=0,columnspan=2,sticky='w',pady=12)
        ttk.Label(page,text='Se pide confirmación antes de enviar. Los aceptados se omiten.\nLos inciertos bloquean el reenvío automático. Esta operación no envía el Excel.').grid(row=3,column=0,columnspan=2,sticky='w')
        page=self.pages[4]
        ttk.Label(page,text='Comprueba recepción y clasificación de la campaña seleccionada.\nAceptado no equivale a recibido. La lectura puede incluir Spam.').pack(anchor='w',pady=10)
        self.button(page,'Solo analizar / reanudar lectura',self.analyze).pack(anchor='w',pady=8)
        self.button(page,'Ver último resultado guardado',self.select_campaign).pack(anchor='w',pady=8)
        self.validation_tree=ttk.Treeview(page,columns=('type','expected','actual','state'),show='headings',height=8)
        for key,title in [('type','Escenario'),('expected','Esperado'),('actual','Obtenido'),('state','Validación')]:
            self.validation_tree.heading(key,text=title);self.validation_tree.column(key,width=200)
        scroll=ttk.Scrollbar(page,command=self.validation_tree.yview);scroll.pack(side='right',fill='y')
        self.validation_tree.configure(yscrollcommand=scroll.set);self.validation_tree.pack(fill='both',expand=True)
        page=self.pages[5]
        ttk.Label(page,text='El Excel de pruebas conserva las cuatro hojas. Los escenarios se añaden a Resumen.').pack(anchor='w')
        ttk.Button(page,text='Abrir Excel disponible',command=self.open_report).pack(anchor='w',pady=8)
        self.history_selector=self.combo(page,width=95);self.history_selector.pack(fill='x',pady=8)
        self.button(page,'Actualizar historial de simulaciones',self.refresh_history).pack(anchor='w',pady=4)
        self.button(page,'Cargar resultado anterior',self.load_history).pack(anchor='w',pady=4)
        ttk.Button(page,text='Abrir carpeta de CSV, JSON y Excel',command=self.open_results).pack(anchor='w',pady=4)
        page=self.pages[6]
        ttk.Label(page,text='La simulación guarda logs aislados. Los errores esperados no son fallos reales.\nSupabase guarda auditoría; la recuperación permanece en SQLite.').pack(anchor='w',pady=8)
        ttk.Button(page,text='Abrir logs',command=lambda:self.open_path(self.logs_path)).pack(anchor='w',pady=4)
        self.button(page,'Estado local de Supabase',self.check_connections).pack(anchor='w',pady=4)
        self.button(page,'Sincronizar logs con Supabase (usa internet)',lambda:self.start('Sincronizando logs',self.actions.sync_logs)).pack(anchor='w',pady=4)

    def build_configuration(self):
        page=self.pages[1]
        actions=ttk.Frame(page);actions.pack(side='bottom',fill='x',pady=4)
        self.button(actions,'Validar cantidades',self.validate_form).pack(side='left')
        self.button(actions,'Ejecutar simulación sin internet',self.simulate).pack(side='left',padx=8)
        ttk.Label(actions,text='Desplaza el formulario para ver todos los escenarios.').pack(side='left')
        canvas=tk.Canvas(page,highlightthickness=0)
        scroll=ttk.Scrollbar(page,orient='vertical',command=canvas.yview);scroll.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
        form=ttk.Frame(canvas);canvas.create_window((0,0),window=form,anchor='nw')
        form.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        self.preset_choice=tk.StringVar();self.mode=tk.StringVar(value='GMAIL')
        self.combo(form,list(PRESETS),43,self.preset_choice).grid(row=0,column=0,columnspan=2,sticky='w',pady=5)
        self.button(form,'Aplicar preset (reemplaza cantidades)',self.apply_preset).grid(row=0,column=2,columnspan=2)
        ttk.Label(form,text='Modalidad').grid(row=1,column=0,sticky='w')
        self.combo(form,['SIMULATION','GMAIL'],15,self.mode).grid(row=1,column=1,sticky='w')
        self.count,self.normal,self.special=tk.StringVar(),tk.StringVar(),tk.StringVar()
        self.seed,self.interval,self.limit=tk.StringVar(),tk.StringVar(),tk.StringVar()
        self.spin=self.field(form,'Total',self.count,2);self.field(form,'Normales',self.normal,2,2)
        self.field(form,'Especiales',self.special,3);self.field(form,'Semilla (vacía = aleatoria)',self.seed,3,2)
        self.field(form,'Intervalo Gmail (segundos)',self.interval,4);self.field(form,'Máximo de intentos por tanda',self.limit,4,2)
        self.distribution={key:tk.StringVar(value='0') for key in [*CONTENT,*TECHNICAL]}
        ttk.Label(form,text='Contenido (local o Gmail)').grid(row=5,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Label(form,text='Fallos técnicos (solo simulación)').grid(row=5,column=2,columnspan=2,sticky='w',pady=8)
        for i,(key,data) in enumerate(CONTENT.items(),6):self.field(form,data[0],self.distribution[key],i)
        for i,(key,data) in enumerate(TECHNICAL.items(),6):self.field(form,data[0],self.distribution[key],i,2)
        self.saved_name=tk.StringVar(value='mi_prueba');self.field(form,'Nombre guardado',self.saved_name,17,width=22)
        self.button(form,'Guardar configuración',self.save_configuration).grid(row=17,column=2)
        self.saved=self.combo(form,width=25);self.saved.grid(row=18,column=0,columnspan=2,sticky='w')
        self.button(form,'Cargar configuración',self.load_configuration).grid(row=18,column=2)

    def apply_config(self,config):
        for var,value in [(self.count,config.total),(self.normal,config.normal),(self.special,config.special),(self.mode,config.mode),
                          (self.seed,'' if config.seed is None else config.seed),(self.interval,config.interval),(self.limit,config.limit)]:var.set(str(value))
        for key,var in self.distribution.items():var.set(str(config.distribution.get(key,0)))

    def apply_preset(self):
        key=PRESETS[self.preset_choice.get()]
        if key:self.apply_config(preset(key));self.status.set('Preset aplicado: cantidades reemplazadas por los valores mostrados.')

    def read_config(self):
        try:
            return ScenarioConfig(int(self.count.get()),int(self.normal.get()),int(self.special.get()),
                {key:int(var.get()) for key,var in self.distribution.items()},self.mode.get(),
                int(self.seed.get()) if self.seed.get().strip() else None,float(self.interval.get()),int(self.limit.get())).validate()
        except (ValueError,RPAError) as exc:
            messagebox.showerror('Revisa la configuración',friendly_error(exc.code if isinstance(exc,RPAError) else 'SCENARIO_QUANTITY_INVALID'));return None

    def validate_form(self):
        config=self.read_config()
        if config:self.status.set(f'Configuración válida: {config.total} = {config.normal} normales + {config.special} especiales.')

    def refresh_saved(self):self.saved['values']=sorted(p.stem for p in (self.s.runtime/'test_configs').glob('*.json'))

    def save_configuration(self):
        config=self.read_config()
        if not config:return
        name=self.saved_name.get()
        try:
            if name in self.saved['values'] and not messagebox.askyesno('Reemplazar configuración','¿Reemplazar '+name+'?'):return
            save_config(self.s,name,config);self.refresh_saved();self.status.set('Configuración guardada: '+name)
        except RPAError as exc:messagebox.showerror('Configuración',friendly_error(exc.code))

    def load_configuration(self):
        try:
            self.apply_config(load_config(self.s,self.saved.get()));self.preset_choice.set('Personalizado')
            self.status.set('Configuración cargada. Revisa cantidades antes de ejecutar.')
        except RPAError as exc:messagebox.showerror('Configuración',friendly_error(exc.code))

    def refresh_campaigns(self):
        self.campaigns=[]
        for path in sorted((self.s.runtime/'campaigns').glob('*/mensajes.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                data=load(self.s,path.parent.name);self.campaigns.append((data['id'],f"{data['count']} mensajes · {data['id']}"))
            except (OSError,ValueError,RPAError):continue
        self.selector['values']=[label for _,label in self.campaigns]
        if self.campaigns:
            i=next((i for i,(cid,_) in enumerate(self.campaigns) if cid==self.campaign_id),0)
            self.selector.current(i);self.select_campaign()

    def select_campaign(self,event=None):
        i=self.selector.current()
        if i<0:return
        self.campaign_id=self.campaigns[i][0];data=load(self.s,self.campaign_id);state=summary(self.s,self.campaign_id)
        self.selected.set(f"Campaña: {self.campaign_id} · {data['count']} mensajes")
        self.send_limit.set(str(data.get('test_config',{}).get('limit',min(24,data['count']))))
        self.send_interval.set(str(data.get('test_config',{}).get('interval',1.0)))
        self.counters.set(f"Preparados: {data['count']}   Aceptados: {state['accepted']}   Recibidos: {state['received']}")
        self.live_received=state['received']
        self.report_path=None;folder=self.s.runtime/'campaigns'/self.campaign_id
        analysis=folder/'analisis_resultado.json'
        if analysis.is_file():self.show_result({'analysis':json.loads(analysis.read_text(encoding='utf-8'))})
        else:
            self.special_counts.set(f"Especiales: {data.get('test_config',{}).get('special',0)} · comprobados: 0")
            self.show('Campaña guardada. Revisa vista previa y estado antes de enviar.\n'+json.dumps(state['states']))
        report=folder/'reporte_consolidado.json'
        if not self.report_path and report.is_file():self.set_report(json.loads(report.read_text(encoding='utf-8')).get('path'))

    def preview(self):
        if not self.campaign_id:return
        data=load(self.s,self.campaign_id);self.preview_tree.delete(*self.preview_tree.get_children())
        for item in data['messages']:
            self.preview_tree.insert('','end',values=(item['sequence'],item.get('scenario',{}).get('type','normal'),item['expected'],item['subject']))
        self.tabs.select(self.pages[2])

    def emit(self,event):self.messages.put(('progress',event))

    def start(self,title,operation,active_campaign=False):
        if self.busy:return
        self.busy=True;self.stop.clear();self.recent_events=[];self.status.set(title);self.stage.set(title)
        self.progress.configure(mode='indeterminate');self.progress.start(15)
        for control in self.controls:control.configure(state='disabled')
        for widget,_ in self.inputs:widget.configure(state='disabled')
        self.stop_button.configure(state='normal' if active_campaign else 'disabled')
        def worker():
            try:self.messages.put(('result',operation()))
            except Exception as exc:self.messages.put(('error',exc.code if isinstance(exc,RPAError) else type(exc).__name__))
        threading.Thread(target=worker,daemon=False).start()

    def simulate(self):
        config=self.read_config()
        if config:self.start('Simulación local sin envíos',lambda:self.actions.simulation(config,progress=self.emit))

    def prepare(self):
        config=self.read_config()
        if config:self.start('Preparando campaña, sin enviar',lambda:self.actions.prepare(config))

    def send(self):
        if not self.campaign_id:
            messagebox.showinfo('Selecciona una campaña','Prepara o selecciona una campaña en la sección 3.');return
        try:
            limit,interval=int(self.send_limit.get()),float(self.send_interval.get())
            info=send_preview(self.s,self.campaign_id,limit=limit,interval=interval)
        except (ValueError,RPAError) as exc:
            messagebox.showerror('Revisa el envío',friendly_error(exc.code if isinstance(exc,RPAError) else 'SCENARIO_SEND_LIMIT_INVALID'));return
        if info['review_required'] or not info['to_attempt']:
            messagebox.showinfo('Envío detenido','No hay mensajes habilitados ahora. Revisa incertidumbre, bloqueos o espera pendiente.');return
        text=(f"De: {info['sender']}\nPara: {info['recipient']}\nCampaña: {self.campaign_id}\n\n"
              f"Preparados: {info['expected']}\nYa aceptados: {info['accepted']}\nPendientes: {info['pending']}\n"
              f"A intentar ahora: {info['to_attempt']}\nIntervalo: {interval:g} segundos\n\n¿Iniciar el envío real de esta tanda?")
        if not messagebox.askyesno('Confirmar envío real',text):return
        cid=self.campaign_id
        self.start('Enviando tanda y comprobando recepción',lambda:self.actions.process(cid,execute=True,
            stop_event=self.stop,limit=limit,interval=interval,progress=self.emit),True)

    def analyze(self):
        if self.campaign_id:
            cid=self.campaign_id;self.start('Comprobando recepción y clasificación',lambda:self.actions.process(cid,progress=self.emit))

    def authorize(self,role):
        account=self.s.gmail_sender_address if role=='remitente' else self.s.gmail_receiver_address
        messagebox.showinfo('Autorizar cuenta','Selecciona '+account+' en Google.')
        def operation():
            authorize_with_audit(self.s,role,force=True);return {'authorization':'Autorización completada para '+role}
        self.start('Esperando autorización de Google',operation)

    def check_connections(self):self.start('Revisando estado local, sin red',lambda:{'connections':self.actions.connections()})

    def show(self,text):self.details.delete('1.0','end');self.details.insert('end',text)

    @staticmethod
    def describe(value):
        analysis=value.get('analysis',{});scenarios=value.get('scenario_report') or analysis.get('scenario_report');lines=[]
        if scenarios:
            m=scenarios['summary']
            lines=['SIMULACIÓN LOCAL · SIN ENVÍOS' if m['mode']=='SIMULATION' else 'PRUEBA GMAIL',
                f"{m['prepared']} preparados · {m['accepted']} aceptados por Gmail · {m['received']} recibidos · {m['classified']} clasificados",
                f"{m['passed']} pruebas correctas · {m['failed']} fallidas · {m['pending']} pendientes",
                f"{m['special']} especiales configurados · {m['special_validated']} comprobados · {m['special_pending']} pendientes",
                f"Fallos técnicos simulados: {m['simulated_technical']} · Fallos reales: {m['real_provider_failures']}",
                f"Tiempo: {m['duration_seconds']:.2f} s · Promedio: {m['average_seconds']:.4f} s"]
        elif analysis:lines=[f"Recibidos: {analysis['received_unique']} de {analysis['expected']}",f"Correctos: {analysis['correct']} · Faltantes: {analysis['missing']}"]
        elif value.get('simulation'):lines=['SIMULACIÓN LOCAL · SIN ENVÍOS',json.dumps(value.get('metrics',{}),ensure_ascii=False)]
        if value.get('send'):
            sent=value['send'];lines.append(f"Envío: {sent['accepted']} aceptados. Estado: {sent.get('error') or 'tanda terminada'}")
        return '\n'.join(lines) if lines else json.dumps(value,ensure_ascii=False,indent=2)

    def show_result(self,value):
        self.last_result=value;scenarios=value.get('scenario_report') or value.get('analysis',{}).get('scenario_report');rows=[]
        if scenarios:
            m=scenarios['summary'];self.counters.set(f"Preparados: {m['prepared']}   Aceptados: {m['accepted']}   Recibidos: {m['received']}   Clasificados: {m['classified']}")
            self.special_counts.set(f"Especiales: {m['special']}   Comprobados: {m['special_validated']}   Pendientes: {m['special_pending']}")
            self.live_received=m['received']
            self.progress.configure(mode='determinate',value=100*(m['passed']+m['failed'])/max(1,m['configured']))
            self.set_report(scenarios.get('report_path'))
            self.validation_tree.delete(*self.validation_tree.get_children())
            path=Path(scenarios.get('json_path','')).resolve()
            if path.is_file() and any(path.is_relative_to(base.resolve()) for base in (self.s.output,self.s.runtime)):
                rows=json.loads(path.read_text(encoding='utf-8')).get('scenarios',[])
                for row in rows:
                    self.validation_tree.insert('','end',values=(row['type'],row['expected_category'] or row['expected_result'],
                        row['actual_category'] or row['actual_result'] or 'Pendiente',row['validation']))
        if value.get('report_path'):self.set_report(value['report_path'])
        logs=value.get('logs') or value.get('analysis',{}).get('execution',{}).get('logs',{})
        if logs.get('file',{}).get('folder'):
            log_path=Path(logs['file']['folder']).resolve()
            if log_path.is_relative_to(self.s.runtime.resolve()):self.logs_path=log_path
        if value.get('connections'):
            data=value['connections'];labels={'LOCAL_VALID':'token vigente localmente','REFRESH_REQUIRED':'refresco necesario al usarlo','AUTH_REQUIRED':'autorización requerida'}
            text='\n'.join(f"OAuth {r['role']}: {labels[r['status']]}" for r in data['oauth'])
            sup,usage=data['supabase'],data['usage']
            text+=f"\nSupabase: {'habilitado' if sup['enabled'] else 'deshabilitado'}; cola local: {sup['queue']}"
            text+=f"\nÚltima sincronización registrada (UTC): {sup.get('last_sync') or 'ninguna'}"
            text+=f"\nCampañas locales en 24 h: {usage['attempted']} intentos y {usage['accepted']} aceptados."
            text+='\nEstimación local: no es cuota oficial ni incluye envíos externos. Conexión remota no comprobada.'
            self.connection_text.set(text);self.show(text)
        else:
            text=self.describe(value)
            if rows:
                text+='\n\nEjemplos de validación (detalle completo en Recepción):'
                for row in rows[-3:]:
                    text+=f"\n{row['type']}: esperado {row['expected_category'] or row['expected_result']} · obtenido {row['actual_category'] or row['actual_result'] or 'pendiente'} · {row['validation']}"
            self.show(text)

    def set_report(self,path):
        if path:
            candidate=Path(path).resolve()
            if candidate.suffix=='.xlsx' and candidate.is_relative_to(self.s.output.resolve()) and candidate.is_file():self.report_path=str(candidate)

    def tick(self):
        try:
            for _ in range(100):
                kind,value=self.messages.get_nowait()
                if kind=='progress':
                    self.stage.set(value['stage'])
                    line=value['stage']
                    if 'expected' in value:line+=' · esperado: '+str(value['expected'])+' · obtenido: '+str(value['actual'])
                    self.recent_events=(self.recent_events+[line])[-8:]
                    self.show('\n'.join(self.recent_events))
                    if 'accepted' in value:
                        self.counters.set(f"Preparados: {value['total']}   Aceptados: {value['accepted']}   Recibidos confirmados antes de esta lectura: {self.live_received}")
                    if value.get('total'):
                        self.progress.stop();self.progress.configure(mode='determinate',value=100*value['done']/value['total'])
                    else:self.progress.configure(mode='indeterminate');self.progress.start(15)
                    continue
                self.busy=False;self.progress.stop()
                for control in self.controls:control.configure(state='normal')
                for widget,state in self.inputs:widget.configure(state=state)
                self.stop_button.configure(state='disabled')
                if kind=='error':self.status.set(friendly_error(value));self.stage.set('Detenido');self.show(value+'\n'+friendly_error(value))
                elif value.get('id') and 'messages' in value:
                    self.campaign_id=value['id'];self.refresh_campaigns();self.preview()
                    self.status.set(f"{value['count']} preparados. Revisa la vista previa antes de enviar.");self.stage.set('Preparación terminada')
                else:
                    self.show_result(value);self.refresh_history();self.stage.set('Resultado disponible')
                    self.status.set('Revisa el resultado: aceptado no equivale a recibido. Los errores esperados se validan por separado.')
        except queue.Empty:pass
        self.after_id=self.window.after(150,self.tick)

    def refresh_history(self):
        self.history=sorted(self.s.output.glob('presentacion/*/*/resultado.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        self.history_selector['values']=[f"{p.parent.name} · {p.parent.parent.name[:8]}" for p in self.history]
        if self.history:self.history_selector.current(0)

    def load_history(self):
        i=self.history_selector.current()
        if i>=0:
            value=json.loads(self.history[i].read_text(encoding='utf-8'));self.report_path=None
            self.show_result(value);self.selected.set('Simulación anterior: '+value['execution_id'])

    def show_history(self):
        if self.presentation:self.toggle_presentation()
        self.tabs.select(self.pages[5])

    def toggle_presentation(self):
        self.presentation=not self.presentation
        if self.presentation:self.tabs.pack_forget();self.details.configure(height=16)
        else:self.tabs.pack(fill='both',expand=True,pady=6);self.details.configure(height=7)

    def open_results(self):self.open_path(Path(self.report_path).parent if self.report_path else self.s.output)

    def open_path(self,path):
        try:Path(path).mkdir(parents=True,exist_ok=True);os.startfile(str(path))
        except OSError:messagebox.showerror('No se pudo abrir','Revisa la carpeta y los permisos.')

    def open_report(self):
        if self.report_path and Path(self.report_path).is_file():
            try:os.startfile(self.report_path)
            except OSError:messagebox.showinfo('Reporte disponible',self.report_path)
        else:messagebox.showinfo('Sin reporte','Ejecuta una simulación o analiza una campaña.')

    def close(self):
        if self.busy:messagebox.showinfo('Proceso activo','Espera el resultado. Puedes detener los envíos pendientes.');return
        self.window.after_cancel(self.after_id);self.window.destroy()


if __name__=='__main__':
    window=tk.Tk()
    try:
        settings=Settings.load(ROOT)
        with profile_lock(settings.runtime/'locks/demo_gui.lock'):
            DemoWindow(window,settings);window.mainloop()
    except Exception as exc:
        messagebox.showerror('RPA EP3',friendly_error(exc.code if isinstance(exc,RPAError) else type(exc).__name__))
        window.destroy()
