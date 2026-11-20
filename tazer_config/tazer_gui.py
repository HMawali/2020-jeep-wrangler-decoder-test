#!/usr/bin/env python3
"""
tazer_gui.py - native desktop GUI (Tkinter, bundled with Python on Windows).

Read-only Jeep JL body-config reader over the USB2CANFD. All CAN work runs on a
background thread; the UI only reads. Writes are intentionally absent (see HANDOFF.md).

Run:  python -I tazer_gui.py
"""
import threading, queue, time, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # work under `python -I`
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from canlink import SlcanLink, CanFrame, S_125K, S_500K, BUS_LABEL, list_ports
from uds import UdsClient, nrc_name
import did_catalog

class App:
    def __init__(self, root):
        self.root = root
        root.title('Tazer JL Config (read-only)')
        root.geometry('900x620')
        self.cat = did_catalog.load()
        self.q = queue.Queue()
        self.worker = None
        self.last_results = None
        self._build()
        self.refresh_ports()
        self.root.after(80, self._pump)

    def _build(self):
        top = ttk.Frame(self.root, padding=8); top.pack(fill='x')
        ttk.Label(top, text='Port').pack(side='left')
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(top, textvariable=self.port_var, width=22, state='readonly')
        self.port_cb.pack(side='left', padx=(4, 6))
        ttk.Button(top, text='↻', width=3, command=self.refresh_ports).pack(side='left')
        self.bus_var = tk.StringVar(value='s4')
        ttk.Label(top, text='  Bus').pack(side='left')
        ttk.Combobox(top, textvariable=self.bus_var, width=24, state='readonly',
                     values=[f's4 — {BUS_LABEL[S_125K]}', f's6 — {BUS_LABEL[S_500K]}']
                     ).pack(side='left', padx=4)
        ttk.Label(top, text='  Module 0x').pack(side='left')
        self.mod_var = tk.StringVar(value='620')
        ttk.Entry(top, textvariable=self.mod_var, width=6).pack(side='left')
        self.read_btn = ttk.Button(top, text='Connect & Read', command=self.on_read)
        self.read_btn.pack(side='right')
        self.save_btn = ttk.Button(top, text='Save…', command=self.on_save, state='disabled')
        self.save_btn.pack(side='right', padx=6)
        self.status = ttk.Label(self.root, text='session: —', foreground='#666')
        self.status.pack(fill='x', padx=10)

        mid = ttk.Panedwindow(self.root, orient='horizontal'); mid.pack(fill='both', expand=True, padx=8, pady=6)
        left = ttk.Frame(mid); mid.add(left, weight=3)
        self.tree = ttk.Treeview(left, columns=('data',), show='tree headings', height=18)
        self.tree.heading('#0', text='DID'); self.tree.heading('data', text='data / field')
        self.tree.column('#0', width=120); self.tree.column('data', width=420)
        self.tree.pack(fill='both', expand=True, side='left')
        sb = ttk.Scrollbar(left, command=self.tree.yview); sb.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=sb.set)

        right = ttk.Frame(mid, width=260); mid.add(right, weight=1)
        msg = ("Writes are LOCKED.\n\n"
               "This reads config only. Writing a block (UDS 2E) is disabled: we have the "
               "bit-field map but not verified setting names/values, and a wrong write can "
               "brick a body module.\n\n"
               "To label a setting safely:\n"
               "1. Read, Save a baseline.\n"
               "2. Change that one setting in the truck, Read again, Save.\n"
               "3. Diff the two files — the bit that moved is that setting.\n\n"
               "No SecurityAccess (0x27): the Tazer has no seed→key. Access = SGW bypass "
               "+ extended session. Read 22 01 XX / Write 2E 01 XX <data>.")
        t = tk.Text(right, wrap='word', height=20, width=34, relief='flat', bg='#f6f6f4')
        t.insert('1.0', msg); t.config(state='disabled'); t.pack(fill='both', expand=True, padx=4, pady=4)

        self.logbox = tk.Text(self.root, height=7, bg='#111', fg='#9f9', font=('Menlo', 10))
        self.logbox.pack(fill='x', padx=8, pady=(0, 8))

    def log(self, s):
        self.logbox.insert('end', s + '\n'); self.logbox.see('end')

    def refresh_ports(self):
        ports = list_ports()
        self.port_cb['values'] = ports
        if ports and not self.port_var.get(): self.port_var.set(ports[0])
        self.log('# ports: ' + (', '.join(ports) if ports else 'none found'))

    def on_read(self):
        if self.worker and self.worker.is_alive(): return
        port = self.port_var.get()
        if not port: messagebox.showwarning('No port', 'Pick a serial port.'); return
        try:
            tx = int(self.mod_var.get().replace('0x', ''), 16)
        except ValueError:
            messagebox.showwarning('Bad module', 'Module ID must be hex, e.g. 620'); return
        bus = S_500K if self.bus_var.get().startswith('s6') else S_125K
        self.read_btn.config(state='disabled')
        self.tree.delete(*self.tree.get_children())
        self.worker = threading.Thread(target=self._do_read, args=(port, bus, tx), daemon=True)
        self.worker.start()

    def _do_read(self, port, bus, tx):
        try:
            link = SlcanLink(port); link.open(bus, listen_only=False)
        except Exception as e:
            self.q.put(('log', f'✗ open failed: {e}')); self.q.put(('done', None)); return
        self.q.put(('log', f'→ {port} on {BUS_LABEL[bus]}, module 0x{tx:03X}'))
        uds = UdsClient(link)
        ignore = {f.id for f in link.collect(2.0)}; link.drain()
        try:
            s = uds.diagnostic_session(0x03, tx)
            status = ('DENIED (%s)' % nrc_name(s.nrc)) if (s and s.is_negative) else (('OK ' + s.hex) if s else 'no response')
        except Exception as e:
            status = f'error: {e}'
        self.q.put(('status', 'session 0x10 03 -> ' + status))
        uds.tester_present(tx)
        results = {}; ok = 0
        for did in self.cat.all_dids:
            try: r = uds.read_did(did, tx, None, ignore=ignore)
            except Exception: r = None
            if r is None:
                self.q.put(('row', (did, '— no response', False))); results['0x%04X' % did] = None
            elif r.is_negative:
                self.q.put(('row', (did, 'NRC 0x%02X (%s)' % (r.nrc, nrc_name(r.nrc)), False)))
                results['0x%04X' % did] = {'nrc': r.nrc}
            elif len(r.data) >= 3 and r.data[0] == 0x62:
                payload = r.data[3:]; ok += 1
                self.q.put(('row', (did, payload.hex(' ').upper() or '(empty)', True)))
                results['0x%04X' % did] = payload.hex().upper()
            else:
                self.q.put(('row', (did, '? ' + r.hex, False))); results['0x%04X' % did] = {'raw': r.hex}
        link.close()
        self.q.put(('log', f'✓ {ok}/{len(self.cat.all_dids)} DIDs read'))
        self.q.put(('results', {'module': '0x%03X' % tx, 'bus': bus,
                                'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'dids': results}))
        self.q.put(('done', None))

    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'log': self.log(payload)
                elif kind == 'status': self.status.config(text=payload)
                elif kind == 'row':
                    did, data, ok = payload
                    node = self.tree.insert('', 'end', text='0x%04X' % did, values=(data,),
                                            tags=('ok' if ok else 'bad',))
                    for f in self.cat.fields(did):
                        name = f.label or 'unlabelled'
                        self.tree.insert(node, 'end', text='', values=(f'{name} · {f.desc()}',))
                elif kind == 'results':
                    self.last_results = payload; self.save_btn.config(state='normal')
                elif kind == 'done':
                    self.read_btn.config(state='normal')
        except queue.Empty:
            pass
        self.tree.tag_configure('bad', foreground='#b00')
        self.root.after(80, self._pump)

    def on_save(self):
        if not self.last_results: return
        path = filedialog.asksaveasfilename(defaultextension='.json',
                                            initialfile='read_%s.json' % time.strftime('%H%M%S'))
        if path:
            json.dump(self.last_results, open(path, 'w'), indent=2)
            self.log(f'# saved -> {path}')

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == '__main__':
    main()
