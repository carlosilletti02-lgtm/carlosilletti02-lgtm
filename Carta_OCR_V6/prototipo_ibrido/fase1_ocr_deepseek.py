#!/usr/bin/env python3
"""FASE 1 dell'ibrido: DeepSeek-OCR 2 legge le pagine e restituisce blocchi con riquadro + testo/LaTeX.

Gira in un processo SEPARATO dalla traduzione: a fine lavoro il processo termina e il modello esce dalla memoria.
Tutto offline (variabili d'ambiente + va lanciato con la rete bloccata). Non traduce, non usa Qwen.

Per ogni pagina salva nella cartella di lavoro:
  <nome>_p<NNNN>.raw.txt   uscita grezza di DeepSeek (con i tag dei riquadri)
  <nome>_p<NNNN>.json      parametri usati, tempi, picco RAM, percorso del PDF
Se i due file esistono gia' con gli stessi parametri la pagina e' saltata (cache); --rifai la rilegge.

Uso (dalla cartella 05_V6_in_sviluppo/prototipo_ibrido):
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  sandbox-exec -p '(version 1)(allow default)(deny network*)' "$PY" -B fase1_ocr_deepseek.py --cartella lavoro \
      1783639.pdf:25 978-3-658-50521-9.pdf:34 libro.pdf:30-35
Pagine = numeri del lettore PDF (la prima e' la 1). I PDF si cercano in ~/Desktop/manuali in tedesco/ se il percorso non e' assoluto.
"""
import os
for _k, _v in (('HF_HUB_OFFLINE', '1'), ('TRANSFORMERS_OFFLINE', '1'), ('HF_DATASETS_OFFLINE', '1'), ('HF_HUB_DISABLE_TELEMETRY', '1')):
    os.environ[_k] = _v                                   # prima di importare mlx_vlm: niente rete, in nessun caso

import argparse
import json
import re
import resource
import sys
import time
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
PDFS = Path.home() / 'Desktop/manuali in tedesco'
MODEL = Path.home() / 'Library/Application Support/CartaOCR/models/deepseek-ocr-2'
PROMPT = '<|grounding|>Convert the document to markdown.'


def parse_specs(specs: list[str]) -> list[tuple[Path, int]]:
    out = []
    for spec in specs:
        name, _, pages = spec.rpartition(':')
        if not name:
            raise SystemExit(f'Formato non valido: {spec!r} (usa NOMEFILE.pdf:25 oppure NOMEFILE.pdf:30-35 oppure NOMEFILE.pdf:25,34)')
        p = Path(name).expanduser()
        pdf = p if p.is_absolute() else PDFS / name
        for part in pages.split(','):
            a, _, b = part.partition('-')
            for n in range(int(a), int(b or a) + 1):
                out.append((pdf, n))
    return out


def model_commit(model_dir: Path) -> str:
    f = model_dir / 'LEGGIMI_VERSIONE.txt'
    if f.is_file():
        m = re.search(r'Commit:\s*(\w+)', f.read_text(encoding='utf-8'))
        if m:
            return m.group(1)
    return 'sconosciuto'


def main() -> int:
    ap = argparse.ArgumentParser(description='Ibrido, fase 1: DeepSeek-OCR 2 (offline)')
    ap.add_argument('pagine', nargs='+', metavar='FILE.pdf:PAGINE')
    ap.add_argument('--cartella', type=Path, default=HERE / 'lavoro')
    ap.add_argument('--modello', type=Path, default=MODEL)
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--max-token', type=int, default=4096)
    ap.add_argument('--rifai', action='store_true', help='rilegge anche le pagine gia\' in cache')
    args = ap.parse_args()

    model_dir = args.modello.expanduser()
    if not (model_dir / 'config.json').is_file() or not list(model_dir.glob('*.safetensors')):
        print(f'ERRORE: modello non trovato in {model_dir}', file=sys.stderr)
        return 2
    jobs = parse_specs(args.pagine)
    for pdf, n in jobs:
        if not pdf.is_file():
            print(f'ERRORE: PDF non trovato: {pdf}', file=sys.stderr)
            return 2
    work = args.cartella
    work.mkdir(parents=True, exist_ok=True)
    commit = model_commit(model_dir)
    params = dict(dpi=args.dpi, prompt=PROMPT, max_token=args.max_token, modello_commit=commit)

    todo = []
    for pdf, n in jobs:
        base = work / f'{pdf.stem}_p{n:04d}'
        meta_f, raw_f = base.with_suffix('.json'), base.with_suffix('.raw.txt')
        if not args.rifai and meta_f.is_file() and raw_f.is_file():
            old = json.loads(meta_f.read_text(encoding='utf-8'))
            if all(old.get(k) == v for k, v in params.items()):
                print(f'{pdf.stem} p.{n}: in cache, salto')
                continue
        todo.append((pdf, n, base))
    if not todo:
        print('Niente da fare: tutte le pagine sono gia\' in cache.')
        return 0

    import mlx.core as mx
    from mlx_vlm import apply_chat_template, generate, load
    from mlx_vlm.utils import load_config

    t0 = time.time()
    model, processor = load(str(model_dir))
    config = load_config(str(model_dir))
    mx.eval(model.parameters())
    print(f'Modello caricato in {time.time() - t0:.1f} s | RAM MLX {mx.get_active_memory() / 1e9:.2f} GB', flush=True)
    prompt = apply_chat_template(processor, config, PROMPT, num_images=1)

    tmp_png = work / '_pagina_corrente.png'
    peak_all = 0.0
    for pdf, n, base in todo:
        with pymupdf.open(pdf) as doc:
            if not 1 <= n <= len(doc):
                print(f'{pdf.name}: la pagina {n} non esiste (il PDF ha {len(doc)} pagine)', file=sys.stderr)
                continue
            doc[n - 1].get_pixmap(dpi=args.dpi, alpha=False).save(tmp_png)
        mx.reset_peak_memory()
        t1 = time.time()
        res = generate(model, processor, prompt, image=[str(tmp_png)], max_tokens=args.max_token, temperature=0.0, verbose=False)
        dt = time.time() - t1
        peak = max(mx.get_peak_memory() / 1e9, float(res.peak_memory or 0))
        peak_all = max(peak_all, peak)
        truncated = res.generation_tokens >= args.max_token
        base.with_suffix('.raw.txt').write_text(res.text, encoding='utf-8')
        base.with_suffix('.json').write_text(json.dumps(dict(
            params, pdf=str(pdf.resolve()), pagina=n, secondi=round(dt, 1), token=res.generation_tokens,
            picco_ram_gb=round(peak, 2), troncato=truncated), indent=1), encoding='utf-8')
        print(f'{pdf.stem} p.{n}: {dt:.1f} s | {res.generation_tokens} token | picco RAM {peak:.2f} GB'
              + ('  <-- TRONCATO al limite di token' if truncated else ''), flush=True)
        mx.clear_cache()
    tmp_png.unlink(missing_ok=True)
    print(f'\nFASE 1 FINITA. Picco RAM MLX: {peak_all:.2f} GB. Il modello esce dalla memoria con la fine del processo.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
