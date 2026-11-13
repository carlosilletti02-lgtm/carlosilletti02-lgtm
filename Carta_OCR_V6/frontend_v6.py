#!/usr/bin/env python3
"""Piccola finestra per la Carta OCR V6: scegli il libro, scegli prima e ultima pagina, premi Traduci.

Tutto in locale: usa solo Tkinter (gia' nel Python di Carta OCR) e pymupdf (gia' installato). Non apre porte di rete,
non carica il libro da nessuna parte: legge il PDF dal suo posto e lancia 'avvia_v6.py', che blocca la rete a livello
di sistema (sandbox-exec) per tutta la traduzione. Il PDF originale non viene mai modificato.

Avvio (dal Terminale):
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  "$PY" "$HOME/Desktop/CartaOCR_Progetto/05_V6_in_sviluppo/frontend_v6.py"
oppure doppio clic su Avvia_Frontend.command (stessa cartella).

I numeri di pagina sono quelli del lettore PDF (la prima pagina del file e' la 1), NON quelli stampati sul libro:
le due anteprime servono proprio a controllare di aver scelto le pagine giuste.
"""
from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pymupdf

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / 'avvia_v6.py'
PREVIEW_W = 200                       # larghezza delle anteprime in pixel
RE_PAGE = re.compile(r'Pagina PDF (\d+)/(\d+)')
RE_DIR = re.compile(r'^Risultati in:\s*(.+?)\s*$')


def available_languages() -> list[tuple[str, str]]:
    """(codice, etichetta) per ogni lingua_<codice>.json accanto al programma."""
    out = []
    for f in sorted(HERE.glob('lingua_*.json')):
        code = f.stem.removeprefix('lingua_')
        try:
            name = json.loads(f.read_text(encoding='utf-8')).get('nome_lingua', code)
        except (OSError, ValueError):
            name = code
        out.append((code, f'{name} ({code})' + (' - sperimentale' if code != 'deu' else '')))
    return out or [('deu', 'tedesco (deu)')]


def fmt_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Carta OCR V6 - traduzione locale')
        self.minsize(820, 640)
        self.doc: pymupdf.Document | None = None
        self.pdf_path: Path | None = None
        self.total = 0
        self.toc: list[tuple[int, str, int, int]] = []        # (livello, titolo, pagina inizio, pagina fine)
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.out_dir: Path | None = None
        self.t0 = 0.0
        self.run_first = self.run_last = 0
        self.stopped = False
        self._preview_job: str | None = None
        self._photos: dict[str, tk.PhotoImage | None] = {'da': None, 'a': None}
        self.langs = available_languages()

        self.var_from = tk.StringVar(value='1')
        self.var_to = tk.StringVar(value='10')
        self.var_fake = tk.BooleanVar(value=False)
        self.var_lang = tk.StringVar(value=self.langs[0][1])
        self.var_file = tk.StringVar(value='Nessun libro scelto')
        self.var_status = tk.StringVar(value='Scegli un PDF per cominciare.')
        self.var_time = tk.StringVar(value='')
        self._build()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.after(150, self._poll)
        self.after(250, self._tick)
        self.after(300, lambda: (self.lift(), self.attributes('-topmost', True), self.after(400, lambda: self.attributes('-topmost', False))))

    # ------------------------------------------------------------------ interfaccia
    def _build(self) -> None:
        pad = {'padx': 10, 'pady': 6}
        top = ttk.Frame(self); top.pack(fill='x', **pad)
        ttk.Button(top, text='1. Scegli il libro (PDF)…', command=self.choose_pdf).pack(side='left')
        ttk.Label(top, textvariable=self.var_file).pack(side='left', padx=12)

        mid = ttk.Frame(self); mid.pack(fill='both', expand=True, **pad)
        left = ttk.LabelFrame(mid, text='2. Pagine da tradurre'); left.pack(side='left', fill='both', expand=True)
        right = ttk.LabelFrame(mid, text='Controllo: le pagine scelte'); right.pack(side='left', fill='y', padx=(10, 0))

        row = ttk.Frame(left); row.pack(fill='x', padx=8, pady=8)
        ttk.Label(row, text='Pagina iniziale').grid(row=0, column=0, sticky='w')
        ttk.Label(row, text='Pagina finale').grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.sp_from = ttk.Spinbox(row, from_=1, to=9999, width=8, textvariable=self.var_from, command=self.schedule_preview)
        self.sp_to = ttk.Spinbox(row, from_=1, to=9999, width=8, textvariable=self.var_to, command=self.schedule_preview)
        self.sp_from.grid(row=1, column=0, sticky='w'); self.sp_to.grid(row=1, column=1, sticky='w', padx=(16, 0))
        self.lbl_total = ttk.Label(row, text=''); self.lbl_total.grid(row=1, column=2, sticky='w', padx=12)
        for sp in (self.sp_from, self.sp_to):
            sp.bind('<KeyRelease>', lambda _e: self.schedule_preview())
        ttk.Button(row, text='Prime 10', command=lambda: self.set_range(1, 10)).grid(row=1, column=3, padx=(8, 0))

        ttk.Label(left, text='Capitoli del libro (se il PDF ha l\'indice): clicca per riempire le pagine').pack(anchor='w', padx=8)
        box = ttk.Frame(left); box.pack(fill='both', expand=True, padx=8, pady=(2, 8))
        self.lb = tk.Listbox(box, height=8, width=36, activestyle='none', exportselection=False)
        sb = ttk.Scrollbar(box, orient='vertical', command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side='left', fill='both', expand=True); sb.pack(side='left', fill='y')
        self.lb.bind('<<ListboxSelect>>', self.on_toc)

        opt = ttk.Frame(left); opt.pack(fill='x', padx=8, pady=(0, 8))
        ttk.Label(opt, text='Lingua del libro:').grid(row=0, column=0, sticky='w')
        self.cb_lang = ttk.Combobox(opt, state='readonly', width=26, values=[l[1] for l in self.langs], textvariable=self.var_lang)
        self.cb_lang.grid(row=0, column=1, sticky='w', padx=8)
        ttk.Checkbutton(opt, text='Prova veloce: solo impaginazione, senza tradurre', variable=self.var_fake
                        ).grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 0))

        self.lbl_prev = {}
        for key, title in (('da', 'Prima pagina'), ('a', 'Ultima pagina')):
            f = ttk.Frame(right); f.pack(side='left', padx=8, pady=8, anchor='n')
            cap = ttk.Label(f, text=title); cap.pack()
            img = ttk.Label(f, relief='sunken', width=24, anchor='center'); img.pack(pady=4)
            self.lbl_prev[key] = (cap, img)

        run = ttk.Frame(self); run.pack(fill='x', **pad)
        self.btn_go = ttk.Button(run, text='3. TRADUCI', command=self.start); self.btn_go.pack(side='left')
        self.btn_stop = ttk.Button(run, text='Ferma', command=self.stop, state='disabled'); self.btn_stop.pack(side='left', padx=8)
        self.btn_dir = ttk.Button(run, text='Apri cartella risultati', command=lambda: self.open_path(self.out_dir), state='disabled')
        self.btn_pdf = ttk.Button(run, text='Apri PDF tradotto', command=lambda: self.open_path(self.result_pdf()), state='disabled')
        self.btn_warn = ttk.Button(run, text='Apri AVVISI', command=lambda: self.open_path(self.out_dir / 'AVVISI.txt' if self.out_dir else None), state='disabled')
        for b in (self.btn_dir, self.btn_pdf, self.btn_warn):
            b.pack(side='left', padx=4)

        st = ttk.Frame(self); st.pack(fill='x', padx=10)
        ttk.Label(st, textvariable=self.var_status).pack(side='left')
        ttk.Label(st, textvariable=self.var_time).pack(side='right')
        self.bar = ttk.Progressbar(self, maximum=100, mode='determinate'); self.bar.pack(fill='x', padx=10, pady=4)

        lf = ttk.Frame(self); lf.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(lf, height=9, wrap='word', state='disabled', font=('Menlo', 10))
        lsb = ttk.Scrollbar(lf, orient='vertical', command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side='left', fill='both', expand=True); lsb.pack(side='left', fill='y')

    # ------------------------------------------------------------------ scelta del libro
    def choose_pdf(self) -> None:
        if self.proc:
            messagebox.showinfo('Traduzione in corso', 'Aspetta la fine (o premi Ferma) prima di cambiare libro.')
            return
        path = filedialog.askopenfilename(title='Scegli il libro', filetypes=[('PDF', '*.pdf')],
                                          initialdir=str(Path.home() / 'Desktop'))
        if path:
            self.load_pdf(Path(path))

    def load_pdf(self, path: Path) -> bool:
        try:
            doc = pymupdf.open(path)
            if doc.needs_pass:
                raise ValueError('il PDF e\' protetto da password')
            if len(doc) < 1:
                raise ValueError('il PDF non ha pagine')
        except Exception as exc:                                       # noqa: BLE001
            messagebox.showerror('PDF non leggibile', f'{path.name}\n\n{exc}')
            return False
        if self.doc:
            self.doc.close()
        self.doc, self.pdf_path, self.total = doc, path, len(doc)
        self.var_file.set(f'{path.name}  -  {self.total} pagine')
        self.lbl_total.configure(text=f'(il PDF ha {self.total} pagine)')
        self.sp_from.configure(to=self.total); self.sp_to.configure(to=self.total)
        self.set_range(1, min(10, self.total))
        self._load_toc()
        has_text = any(doc[i].get_text('text').strip() for i in range(min(self.total, 5)))
        self.var_status.set('Pronto. Controlla le anteprime e premi TRADUCI.' if has_text else
                            'Attenzione: le prime pagine non hanno testo digitale (scansione?). Serve prima l\'OCR di Carta OCR.')
        return True

    def _load_toc(self) -> None:
        self.toc, self.lb_items = [], []
        self.lb.delete(0, 'end')
        try:
            raw = [t for t in self.doc.get_toc() if 1 <= t[2] <= self.total]
        except Exception:                                               # noqa: BLE001
            raw = []
        for i, (lvl, title, page) in enumerate(raw):
            end = self.total
            for lvl2, _t2, page2 in raw[i + 1:]:
                if lvl2 <= lvl:
                    end = max(page, page2 - 1) if page2 > page else page
                    break
            self.toc.append((lvl, title.strip(), page, end))
            self.lb.insert('end', f'{"    " * (lvl - 1)}{title.strip()[:70]}   (pp. {page}-{end})')
        if not self.toc:
            self.lb.insert('end', '(questo PDF non ha un indice: scrivi le pagine a mano)')

    def on_toc(self, _e=None) -> None:
        sel = self.lb.curselection()
        if sel and self.toc:
            _lvl, _t, a, b = self.toc[sel[0]]
            self.set_range(a, b)

    # ------------------------------------------------------------------ pagine e anteprime
    def set_range(self, a: int, b: int) -> None:
        if self.total:
            a, b = max(1, min(a, self.total)), max(1, min(b, self.total))
        self.var_from.set(str(a)); self.var_to.set(str(b))
        self.schedule_preview()

    def read_range(self) -> tuple[int, int] | None:
        try:
            a, b = int(self.var_from.get()), int(self.var_to.get())
        except ValueError:
            return None
        if not self.total or a < 1 or b > self.total or a > b:
            return None
        return a, b

    def schedule_preview(self) -> None:
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self.update_preview)

    def update_preview(self) -> None:
        self._preview_job = None
        rng = self.read_range()
        for key in ('da', 'a'):
            cap, img = self.lbl_prev[key]
            if not self.doc or not rng:
                img.configure(image='', text='(pagine non valide)' if self.doc else '')
                self._photos[key] = None
                continue
            n = rng[0] if key == 'da' else rng[1]
            try:
                page = self.doc[n - 1]
                zoom = PREVIEW_W / page.rect.width
                png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes('png')
                photo = tk.PhotoImage(data=png)
            except Exception as exc:                                    # noqa: BLE001
                img.configure(image='', text=f'anteprima non disponibile ({exc})')
                continue
            self._photos[key] = photo                                   # il riferimento evita che Tk la scarti
            img.configure(image=photo, text='')
            cap.configure(text=f'{"Prima" if key == "da" else "Ultima"} pagina: {n}')
        if self.doc and rng:
            n = rng[1] - rng[0] + 1
            self.lbl_total.configure(text=f'= {n} pagin{"a" if n == 1 else "e"} (il PDF ne ha {self.total})')

    # ------------------------------------------------------------------ esecuzione
    def result_pdf(self) -> Path | None:
        if not self.out_dir:
            return None
        found = sorted(self.out_dir.glob('*_italiano.pdf'))
        return found[0] if found else None

    def start(self) -> None:
        if self.proc:
            return
        if not self.pdf_path:
            messagebox.showinfo('Manca il libro', 'Prima scegli il PDF (pulsante 1).')
            return
        rng = self.read_range()
        if not rng:
            messagebox.showerror('Pagine non valide',
                                 f'Scrivi due numeri tra 1 e {self.total}, con la pagina iniziale non maggiore della finale.')
            return
        a, b = rng
        lang = next(c for c, label in self.langs if label == self.var_lang.get())
        if not self.var_fake.get() and (b - a + 1) > 40:
            if not messagebox.askyesno('Molte pagine', f'Stai per tradurre {b - a + 1} pagine: ci vorra\' parecchio tempo. Continuare?'):
                return
        cmd = [sys.executable, '-B', str(LAUNCHER), '--pdf', str(self.pdf_path), '--lingua', lang, '--da', str(a), '--a', str(b)]
        if self.var_fake.get():
            cmd.append('--fake')
        env = dict(os.environ, PYTHONUNBUFFERED='1')
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                         errors='replace', bufsize=1, env=env, cwd=str(HERE), start_new_session=True)
        except OSError as exc:
            messagebox.showerror('Impossibile avviare', str(exc))
            return
        self.out_dir, self.stopped = None, False
        self.run_first, self.run_last = a, b
        self.t0 = time.time()
        self.bar.configure(value=0)
        self.var_status.set(f'Avvio… pagine {a}-{b} ({"solo impaginazione" if self.var_fake.get() else "traduzione"})')
        self.clear_log()
        for btn in (self.btn_dir, self.btn_pdf, self.btn_warn):
            btn.configure(state='disabled')
        self.btn_go.configure(state='disabled'); self.btn_stop.configure(state='normal')
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self.q.put(('line', line))
        self.q.put(('end', proc.wait()))

    def _poll(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == 'line':
                    self.on_line(val)
                else:
                    self.on_end(val)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def on_line(self, line: str) -> None:
        self.append_log(line)
        m = RE_DIR.match(line)
        if m:
            self.out_dir = Path(m.group(1))
        m = RE_PAGE.search(line)
        if m:
            done = int(m.group(1)) - self.run_first + 1
            total = self.run_last - self.run_first + 1
            self.bar.configure(value=100.0 * done / total)
            self.var_status.set(f'Pagina del PDF {m.group(1)} (fatte {done} di {total})')

    def on_end(self, code: int) -> None:
        self.proc = None
        self.btn_go.configure(state='normal'); self.btn_stop.configure(state='disabled')
        elapsed = fmt_time(time.time() - self.t0)
        if self.out_dir and self.out_dir.is_dir():
            self.btn_dir.configure(state='normal')
        if self.stopped:
            self.var_status.set('Fermata: i risultati parziali, se ci sono, restano nella cartella.')
        elif code == 0:
            self.bar.configure(value=100)
            self.var_status.set('FINITO. Guarda AVVISI.txt e confronta le pagine con l\'originale.')
            if self.result_pdf():
                self.btn_pdf.configure(state='normal')
            if self.out_dir and (self.out_dir / 'AVVISI.txt').is_file():
                self.btn_warn.configure(state='normal')
        else:
            self.var_status.set(f'ERRORE (codice {code}): leggi il registro qui sotto.')
        self.var_time.set(f'durata {elapsed}')

    def _tick(self) -> None:
        if self.proc:
            el = time.time() - self.t0
            val = float(self.bar['value'])
            eta = f'  |  mancano circa {fmt_time(el * (100 - val) / val)}' if val >= 8 else ''
            self.var_time.set(f'trascorso {fmt_time(el)}{eta}')
        self.after(1000, self._tick)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.stopped = True
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.proc.terminate()
            self.var_status.set('Interruzione in corso…')

    def on_close(self) -> None:
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno('Traduzione in corso', 'Chiudendo la finestra la traduzione si ferma. Chiudere?'):
                return
            self.stop()
        if self.doc:
            self.doc.close()
        self.destroy()

    # ------------------------------------------------------------------ varie
    def append_log(self, text: str) -> None:
        self.log.configure(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def clear_log(self) -> None:
        self.log.configure(state='normal'); self.log.delete('1.0', 'end'); self.log.configure(state='disabled')

    @staticmethod
    def open_path(path: Path | None) -> None:
        if path and Path(path).exists():
            subprocess.run(['open', str(path)], check=False)


def main() -> int:
    if not LAUNCHER.is_file():
        print(f'Manca {LAUNCHER.name} nella cartella {HERE}', file=sys.stderr)
        return 2
    app = App()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():            # facoltativo: PDF gia' scelto da riga di comando
        app.load_pdf(Path(sys.argv[1]).expanduser().resolve())
    app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
