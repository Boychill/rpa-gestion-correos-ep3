"""Interfaz de escritorio para presentar el robot sin escribir comandos."""
from pathlib import Path
import json
import os
import queue
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import tkinter as tk
from tkinter import ttk, messagebox

from rpa.config import Settings
from rpa.demo_actions import DemoActions
from rpa.gmail_campaign import summary, load
from rpa.gmail_auth import authorize_with_audit
from rpa.runtime import RPAError, profile_lock

ROOT = Path(__file__).resolve().parent


class DemoWindow:
    def __init__(self, window, settings):
        self.window, self.s = window, settings
        self.actions = DemoActions(settings)
        self.messages = queue.Queue()
        self.stop = threading.Event()
        self.busy, self.report_path, self.active_campaign = False, None, False
        self.logs_path = settings.runtime/'logs'
        self.campaign_id = None
        self.controls = []
        window.title('RPA EP3 · Demostración de correos')
        window.geometry('1000x760')
        window.minsize(900,650)
        style=ttk.Style(window)
        style.theme_use('clam')
        style.configure('TFrame',background='#f0f4f8')
        style.configure('TLabel',background='#f0f4f8',foreground='#16324f',font=('Segoe UI',10))
        style.configure('Title.TLabel',font=('Segoe UI',22,'bold'))
        style.configure('TButton',font=('Segoe UI',10),padding=8)
        root=ttk.Frame(window,padding=24);root.pack(fill='both',expand=True)
        ttk.Label(root,text='Gestión automática de correos',style='Title.TLabel').pack(anchor='w')
        ttk.Label(root,text='Prepara → envía → clasifica → genera Excel → guarda logs').pack(anchor='w',pady=(4,16))
        local=ttk.LabelFrame(root,text='1. Demostración sin envíos',padding=12);local.pack(fill='x')
        self.count=tk.StringVar(value='6')
        ttk.Label(local,text='Cantidad:').pack(side='left')
        self.spin=ttk.Spinbox(local,from_=1,to=1000,textvariable=self.count,width=7);self.spin.pack(side='left',padx=8)
        self.button(local,'Ejecutar simulación',self.simulate).pack(side='left',padx=8)
        ttk.Label(local,text='Funciona sin Gmail ni internet.').pack(side='left',padx=8)
        live=ttk.LabelFrame(root,text='2. Prueba real con Gmail',padding=12);live.pack(fill='x',pady=12)
        ttk.Label(live,text='De: '+settings.gmail_sender_address+'    →    Para: '+settings.gmail_receiver_address).pack(anchor='w')
        row=ttk.Frame(live);row.pack(fill='x',pady=8)
        self.button(row,'Preparar lote',self.prepare).pack(side='left',padx=(0,8))
        self.selector=ttk.Combobox(row,state='readonly',width=58);self.selector.pack(side='left',fill='x',expand=True)
        self.selector.bind('<<ComboboxSelected>>',self.select_campaign)
        actions=ttk.Frame(live);actions.pack(fill='x')
        self.button(actions,'Enviar y analizar',self.send).pack(side='left',padx=(0,8))
        self.button(actions,'Solo analizar / reanudar lectura',self.analyze).pack(side='left',padx=8)
        self.stop_button=ttk.Button(actions,text='Detener nuevos envíos',command=self.stop.set,state='disabled')
        self.stop_button.pack(side='left',padx=8)
        ttk.Label(root,text='Progreso Gmail del lote seleccionado').pack(anchor='w')
        self.progress=ttk.Progressbar(root,maximum=100);self.progress.pack(fill='x',pady=(0,6))
        self.status=tk.StringVar(value='Lista. La simulación y la preparación no envían correos.')
        ttk.Label(root,textvariable=self.status,wraplength=920).pack(anchor='w')
        self.details=tk.Text(root,height=15,wrap='word',font=('Consolas',10),background='white',foreground='#16324f')
        footer=ttk.Frame(root);footer.pack(side='bottom',fill='x')
        self.button(footer,'Autorizar remitente',lambda:self.authorize('remitente')).pack(side='left',padx=(0,6))
        self.button(footer,'Autorizar receptor',lambda:self.authorize('receptor')).pack(side='left',padx=6)
        ttk.Button(footer,text='Abrir Excel',command=self.open_report).pack(side='left',padx=6)
        ttk.Button(footer,text='Ver logs',command=lambda:self.open_path(self.logs_path)).pack(side='left',padx=6)
        ttk.Button(footer,text='Ver resultados',command=lambda:self.open_path(settings.output)).pack(side='left',padx=6)
        self.details.pack(fill='both',expand=True,pady=12)
        self.refresh_campaigns()
        window.protocol('WM_DELETE_WINDOW',self.close)
        window.after(500,self.tick)

    def button(self,parent,text,command):
        button=ttk.Button(parent,text=text,command=command)
        self.controls.append(button)
        return button

    def count_value(self,maximum=1000):
        try:
            count=int(self.count.get())
            if not 1<=count<=maximum: raise ValueError()
            return count
        except ValueError:
            messagebox.showerror('Cantidad inválida',f'Usa un número entre 1 y {maximum}.')
            return None

    def show(self,text):
        self.details.delete('1.0','end');self.details.insert('end',text)

    def refresh_campaigns(self):
        self.campaigns=[]
        base=self.s.runtime/'campaigns'
        for path in sorted(base.glob('*/mensajes.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                data=load(self.s,path.parent.name)
                created=datetime.fromisoformat(data['created']).astimezone(ZoneInfo(self.s.display_timezone))
                self.campaigns.append((data['id'],f"{data['count']} mensajes · {created:%d/%m %H:%M} Santiago · {data['id'][:8]}"))
            except (OSError,ValueError,RPAError):
                continue
        self.selector['values']=[label for _,label in self.campaigns]
        if self.campaigns:
            index=next((i for i,(cid,_) in enumerate(self.campaigns) if cid==self.campaign_id),0)
            self.selector.current(index);self.select_campaign()

    def select_campaign(self,event=None):
        index=self.selector.current()
        if index>=0:
            self.campaign_id=self.campaigns[index][0]
            data=load(self.s,self.campaign_id)
            current=summary(self.s,self.campaign_id)
            self.progress['value']=100*current['accepted']/current['expected']
            self.report_path=None
            folder=self.s.runtime/'campaigns'/self.campaign_id
            report_file=folder/'reporte_consolidado.json'
            if report_file.exists():
                saved=json.loads(report_file.read_text(encoding='utf-8'))
                target=Path(saved.get('path','')).resolve()
                if target.is_file() and target.is_relative_to(self.s.output.resolve()):
                    self.report_path=str(target)
            analysis_file=folder/'analisis_resultado.json'
            if analysis_file.exists():
                self.show(self.describe({'analysis':json.loads(analysis_file.read_text(encoding='utf-8')),
                                         'report_path':self.report_path}))
                return
            self.show('LOTE PREPARADO · AÚN NO ENVIADO\n'+self.campaign_id+'\n\n'+
                '\n'.join(item['subject'] for item in data['messages'][:6])+
                '\n\nCategorías esperadas: '+json.dumps(data['expected'],ensure_ascii=False))

    @staticmethod
    def describe(value):
        lines=[]
        if value.get('simulation'):
            m=value.get('metrics',{})
            lines=['SIMULACIÓN LOCAL · SIN ENVÍOS',f"Procesados: {m.get('processed',0)}",
                   f"Clasificados: {m.get('classified',0)}",f"Fallidos: {m.get('failed',0)}",
                   f"Tiempo: {m.get('duration_seconds',0):.2f} segundos"]
        sent=value.get('send')
        if sent:
            lines += ['ENVÍO GMAIL',f"Aceptados: {sent.get('accepted',0)} de {sent.get('expected',0)}",
                      'Estado: '+str(sent.get('error') or 'Sin errores de envío')]
        analyzed=value.get('analysis')
        if analyzed:
            lines += ['ANÁLISIS DEL LOTE',f"Recibidos únicos: {analyzed['received_unique']} de {analyzed['expected']}",
                      f"Clasificación correcta: {analyzed['correct']}",f"Faltantes: {analyzed['missing']}",
                      f"Duplicados: {analyzed['duplicates']}",'', 'CATEGORÍAS']
            lines += [f'  {name}: {count}' for name,count in analyzed.get('categories',{}).items()]
        if value.get('report_path'):lines += ['', 'EXCEL CONSOLIDADO',value['report_path']]
        if not lines:lines=[json.dumps(value,ensure_ascii=False,indent=2)]
        return '\n'.join(lines)

    def start(self,title,operation,active_campaign=False):
        if self.busy:return
        self.busy=True;self.active_campaign=active_campaign;self.stop.clear();self.status.set(title)
        for button in self.controls:button.configure(state='disabled')
        self.selector.configure(state='disabled');self.spin.configure(state='disabled')
        self.stop_button.configure(state='normal' if active_campaign else 'disabled')
        def worker():
            try:self.messages.put(('result',operation()))
            except Exception as exc:self.messages.put(('error',exc.code if isinstance(exc,RPAError) else type(exc).__name__))
        threading.Thread(target=worker,daemon=False).start()

    def simulate(self):
        count=self.count_value()
        if count:self.start('Procesando simulación local…',lambda:self.actions.simulation(count))

    def prepare(self):
        count=self.count_value(500)
        if count:self.start('Preparando mensajes, sin enviar…',lambda:self.actions.prepare(count))

    def send(self):
        if not self.campaign_id:
            messagebox.showinfo('Prepara un lote','Primero pulsa Preparar lote.');return
        data=load(self.s,self.campaign_id);state=summary(self.s,self.campaign_id)
        pending=data['count']-state['accepted']
        if not messagebox.askyesno('Enviar correos reales',f"Se enviarán hasta {pending} mensajes pendientes.\n\nDe: {data['sender']}\nPara: {data['recipient']}\n\nDespués se analizará el lote y se generará el Excel.\n¿Iniciar?"):return
        campaign_id=self.campaign_id
        self.start('Enviando y analizando el lote…',lambda:self.actions.process(campaign_id,execute=True,stop_event=self.stop),True)

    def analyze(self):
        if self.campaign_id:
            campaign_id=self.campaign_id
            self.start('Leyendo el lote y generando resultados…',lambda:self.actions.process(campaign_id),True)

    def authorize(self,role):
        account=self.s.gmail_sender_address if role=='remitente' else self.s.gmail_receiver_address
        messagebox.showinfo('Autorizar cuenta','Selecciona '+account+' en la ventana de Google.')
        def operation():
            authorize_with_audit(self.s,role,force=True)
            return {'status':'AUTHORIZED','role':role}
        self.start('Esperando autorización de '+role+'…',operation)

    def tick(self):
        try:
            kind,value=self.messages.get_nowait()
            self.busy=False
            for button in self.controls:button.configure(state='normal')
            self.selector.configure(state='readonly');self.spin.configure(state='normal');self.stop_button.configure(state='disabled')
            if kind=='error':
                self.status.set('Se detuvo: '+value)
                self.show(value+'\n\nSi indica AUTH_REQUIRED, usa el botón Autorizar del rol correspondiente.\nLos envíos inciertos requieren revisión; no prepares otro lote para reintentarlos.')
            else:
                if value.get('id') and 'messages' in value:
                    self.campaign_id=value['id'];self.refresh_campaigns()
                    self.status.set('Lote preparado. Revisa la vista previa antes de enviar.')
                else:
                    self.report_path=value.get('report_path',self.report_path)
                    self.logs_path=value.get('logs',{}).get('file',{}).get('folder',self.logs_path)
                    self.show(self.describe(value))
                    self.status.set('Resultado disponible. Revisa recibidos, faltantes y estado; aceptado no equivale a recibido.')
        except queue.Empty:pass
        if self.campaign_id:
            try:
                state=summary(self.s,self.campaign_id)
                self.progress['value']=100*state['accepted']/state['expected']
                if self.busy and self.active_campaign:self.status.set(f"Lote: {state['accepted']}/{state['expected']} aceptados · {state['received']} recibidos confirmados. La tarea sigue en ejecución.")
            except (OSError,RPAError,ValueError):pass
        self.window.after(1000,self.tick)

    def open_path(self,path):
        try:
            Path(path).mkdir(parents=True,exist_ok=True)
            os.startfile(str(path))
        except OSError:messagebox.showerror('No se pudo abrir',str(path))

    def open_report(self):
        if self.report_path and Path(self.report_path).is_file():
            try:os.startfile(self.report_path)
            except OSError:messagebox.showinfo('Reporte generado','Archivo disponible en:\n'+self.report_path)
        else:messagebox.showinfo('Sin reporte','Ejecuta una simulación o completa el análisis del lote.')

    def close(self):
        if self.busy:
            messagebox.showinfo('Proceso activo','Espera el resultado de la tarea actual. Durante un envío puedes detener los mensajes pendientes con el botón Detener nuevos envíos.');return
        self.window.destroy()


if __name__=='__main__':
    window=tk.Tk()
    try:
        settings=Settings.load(ROOT)
        with profile_lock(settings.runtime/'locks/demo_gui.lock'):
            DemoWindow(window,settings)
            window.mainloop()
    except Exception as exc:
        messagebox.showerror('RPA EP3',exc.code if isinstance(exc,RPAError) else type(exc).__name__)
        window.destroy()
