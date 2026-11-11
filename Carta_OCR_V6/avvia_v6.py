#!/usr/bin/env python3
"""Lanciatore semplice della V6: una cartella di risultati per ogni prova, rete bloccata, avvisi leggibili.

Uso (dal Terminale, con il Python di Carta OCR):
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  "$PY" avvia_v6.py --pdf "/percorso/nuovo.pdf" --lingua deu --da 1 --a 10

  --lingua  deu (tedesco, validata su un libro) | eng (inglese, SPERIMENTALE). Un'altra lingua: copia
            lingua_deu.json in lingua_xxx.json, cambia le liste e usa --lingua xxx.
  --da/--a  pagine del PDF (se omesse: le prime 10, per una prova veloce).
  --con-rete  NON blocca la rete (predefinito: rete bloccata con sandbox-exec; se non disponibile avvisa e prosegue
              comunque senza usare Internet, perche' il motore non ne ha bisogno).

Non sovrascrive nulla: ogni prova crea Risultati_V6/<nome>_p<da>-<a>_<data ora>/ con
  <nome>_italiano.pdf, rapporto.json, cache.json, esecuzione.log, AVVISI.txt
Il PDF originale non viene mai modificato.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ENGINE = HERE / 'traduci_pdf_matematica_offline_v6.py'


def main() -> int:
    ap = argparse.ArgumentParser(description='Carta OCR V6 - lanciatore')
    ap.add_argument('--pdf', required=True, type=Path)
    ap.add_argument('--lingua', default='deu')
    ap.add_argument('--da', type=int, default=1)
    ap.add_argument('--a', type=int)
    ap.add_argument('--fake', action='store_true', help='solo impaginazione, senza tradurre (prova rapida)')
    ap.add_argument('--con-rete', action='store_true')
    args = ap.parse_args()

    pdf = args.pdf.expanduser().resolve()
    if not pdf.is_file():
        print(f'ERRORE: PDF non trovato: {pdf}', file=sys.stderr)
        return 2
    config = HERE / f'lingua_{args.lingua}.json'
    if not config.is_file():
        print(f'ERRORE: manca {config.name}. Copia lingua_deu.json in {config.name} e adatta le liste.', file=sys.stderr)
        return 2
    try:
        import pymupdf
        with pymupdf.open(pdf) as doc:
            total = len(doc)
    except Exception as exc:                                # noqa: BLE001
        print(f'ERRORE: PDF non leggibile ({exc}). Se e\' una scansione serve prima l\'OCR di Carta OCR.', file=sys.stderr)
        return 2
    end = args.a or min(total, args.da + 9)
    if args.da < 1 or end < args.da or end > total:
        print(f'ERRORE: pagine non valide; il PDF ha {total} pagine.', file=sys.stderr)
        return 2

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_dir = HERE / 'Risultati_V6' / f'{pdf.stem[:40]}_p{args.da}-{end}_{stamp}'
    out_dir.mkdir(parents=True, exist_ok=False)
    out_pdf = out_dir / f'{pdf.stem[:40]}_italiano.pdf'
    command = [sys.executable, '-B', str(ENGINE), '--original', str(pdf), '--output', str(out_pdf),
               '--start-page', str(args.da), '--end-page', str(end), '--config', str(config)]
    if args.fake:
        command.append('--fake')
    sandbox = shutil.which('sandbox-exec')
    if sandbox and not args.con_rete:
        command = [sandbox, '-p', '(version 1)(allow default)(deny network*)'] + command
        print('Rete bloccata a livello di sistema per tutta l\'esecuzione.')
    elif not args.con_rete:
        print('Attenzione: sandbox-exec non disponibile; il motore comunque non usa Internet.')
    print(f'V6 | {pdf.name} | pagine {args.da}-{end} di {total} | lingua {args.lingua}')
    print(f'Risultati in: {out_dir}\n', flush=True)

    log = out_dir / 'esecuzione.log'
    with log.open('w', encoding='utf-8') as lf:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end='', flush=True)
            lf.write(line)
        code = proc.wait()

    report_src, cache_src = out_pdf.with_suffix('.rapporto.json'), out_pdf.with_suffix('.cache.json')
    if report_src.is_file():
        report_src.replace(out_dir / 'rapporto.json')
    if cache_src.is_file():
        cache_src.replace(out_dir / 'cache.json')
    write_avvisi(out_dir)
    print(f'\n{"FINITO" if code == 0 else "ERRORE (codice " + str(code) + ")"} | cartella: {out_dir}')
    print(f'Avvisi da guardare: {out_dir / "AVVISI.txt"}')
    return code


def write_avvisi(out_dir: Path) -> None:
    rp = out_dir / 'rapporto.json'
    lines = ['AVVISI V6 - cio\' che il programma ha riconosciuto come dubbio.',
             'Non elenca gli errori che il programma non puo\' vedere: la revisione sulle formule resta necessaria.', '']
    if not rp.is_file():
        (out_dir / 'AVVISI.txt').write_text('\n'.join(lines + ['Nessun rapporto: esecuzione interrotta, vedi esecuzione.log.']), encoding='utf-8')
        return
    data = json.loads(rp.read_text(encoding='utf-8'))
    st = data.get('statistiche_traduzione', {})
    lines += [f"Pagine italiane: {data.get('pagine_italiane')} | unita' tradotte: {data.get('unita_tradotte')} | "
              f"equazioni display: {data.get('equazioni_display')} | formule in linea: {data.get('formule_inline')}",
              f"Frasi unite attraverso equazioni: {data.get('unita_fuse_attraverso_equazioni')} | passaggi da rivedere: {data.get('da_rivedere')}",
              f"Chiamate al modello: {st.get('chiamate_qwen', 0)} | dalla cache: {st.get('cache', 0)} | "
              f"recuperati a livello 2/3/4: {st.get('livello_2', 0)}/{st.get('livello_3', 0)}/{st.get('livello_4', 0)} | "
              f"falliti: {st.get('livello_5_fallito', 0)}", '']
    for page in data.get('pagine', []):
        items = [f"  [DA RIVEDERE] {x.get('motivo')} :: {x.get('testo')}" for x in page.get('da_rivedere', [])]
        items += [f'  [avviso] {a}' for a in page.get('avvisi', [])]
        if items:
            lines += [f"Pagina PDF originale {page.get('pagina_pdf_originale')}:"] + items + ['']
    (out_dir / 'AVVISI.txt').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
