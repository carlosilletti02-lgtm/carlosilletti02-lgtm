#!/usr/bin/env python3
"""Prova di DeepSeek-OCR 2 su poche pagine: trascrive ogni pagina in Markdown (formule in LaTeX) e MISURA tempo e RAM.

Solo FASE 1 (lettura): non traduce e non usa Qwen. Tutto offline: il modello deve essere gia' nella cartella locale
(vedi scarica_deepseek_ocr2.py). Va lanciato con la rete bloccata (comando nel fondo di questo testo).

Per ogni pagina salva, in strumenti_test/prove_deepseek/<data ora>/:
  <nome>_p<N>_originale.png        la pagina come l'ha vista il modello
  <nome>_p<N>_deepseek.md          trascrizione pulita (senza i tag di posizione)
  <nome>_p<N>_deepseek_grezzo.txt  uscita grezza del modello (per capire gli errori)
  <nome>_p<N>_pymupdf4llm.md       lo stesso con pymupdf4llm (testo esatto, formule appiattite) per confronto
  RISULTATO.txt                    tempi, token e picco di RAM di ogni pagina

Uso (dalla cartella 05_V6_in_sviluppo), 3 pagine predefinite (PDE p.25, economia p.34, matematica p.208):
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  sandbox-exec -p '(version 1)(allow default)(deny network*)' "$PY" -B strumenti_test/prova_deepseek_ocr2.py
Altre pagine:  --prova NOMEFILE.pdf:PAGINA  (ripetibile; i PDF si cercano in ~/Desktop/manuali in tedesco/)
Numeri di pagina = quelli del lettore PDF (la prima pagina del file e' la 1).
"""
import os
for _k, _v in (('HF_HUB_OFFLINE', '1'), ('TRANSFORMERS_OFFLINE', '1'), ('HF_DATASETS_OFFLINE', '1'), ('HF_HUB_DISABLE_TELEMETRY', '1')):
    os.environ[_k] = _v                                  # prima di importare mlx_vlm: niente rete, in nessun caso

import argparse
import re
import resource
import sys
import time
from datetime import datetime
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
PDFS = Path.home() / 'Desktop/manuali in tedesco'
MODEL = Path.home() / 'Library/Application Support/CartaOCR/models/deepseek-ocr-2'
DEFAULT_TESTS = ['1783639.pdf:25', '978-3-658-50521-9.pdf:34', '978-3-658-41641-6.pdf:208']
PROMPT = '<|grounding|>Convert the document to markdown.'
GROUNDING = re.compile(r'<\|ref\|>.*?<\|/ref\|>\s*<\|det\|>.*?<\|/det\|>\s*', re.S)
TAGS = re.compile(r'<\|/?(?:ref|det|grounding)\|>')


def clean(raw: str) -> str:
    """Toglie i tag di posizione (<|ref|>..<|det|>[[x,y,x,y]]<|/det|>) lasciando il Markdown."""
    return TAGS.sub('', GROUNDING.sub('', raw)).strip() + '\n'


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9        # macOS: byte


def parse_test(spec: str) -> tuple[Path, int]:
    name, _, page = spec.rpartition(':')
    p = Path(name).expanduser()
    return (p if p.is_absolute() else PDFS / name), int(page)


def main() -> int:
    ap = argparse.ArgumentParser(description='Prova DeepSeek-OCR 2 (fase 1) con misura della RAM')
    ap.add_argument('--prova', action='append', metavar='FILE.pdf:PAGINA', help='pagina da trascrivere (ripetibile)')
    ap.add_argument('--modello', type=Path, default=MODEL)
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--max-token', type=int, default=4096)
    ap.add_argument('--prompt', default=PROMPT)
    ap.add_argument('--uscita', type=Path)
    args = ap.parse_args()

    model_dir = args.modello.expanduser()
    if not (model_dir / 'config.json').is_file() or not list(model_dir.glob('*.safetensors')):
        print(f'ERRORE: modello non trovato in {model_dir}\nScaricalo prima con strumenti_test/scarica_deepseek_ocr2.py', file=sys.stderr)
        return 2
    tests = [parse_test(s) for s in (args.prova or DEFAULT_TESTS)]
    for pdf, page in tests:
        if not pdf.is_file():
            print(f'ERRORE: PDF non trovato: {pdf}', file=sys.stderr)
            return 2
    out_dir = args.uscita or HERE / 'prove_deepseek' / datetime.now().strftime('%Y%m%d_%H%M%S')
    out_dir.mkdir(parents=True, exist_ok=False)
    print(f'Risultati in: {out_dir}')

    # 1) pagine come immagini + confronto pymupdf4llm (prima del modello: cosi' la RAM misurata e' solo del modello)
    jobs = []
    try:
        import pymupdf4llm
    except ImportError:
        pymupdf4llm = None
    for pdf, page in tests:
        stem = f'{pdf.stem[:30]}_p{page}'
        with pymupdf.open(pdf) as doc:
            if not 1 <= page <= len(doc):
                print(f'ERRORE: {pdf.name} ha {len(doc)} pagine, non esiste la {page}', file=sys.stderr)
                return 2
            png = out_dir / f'{stem}_originale.png'
            doc[page - 1].get_pixmap(dpi=args.dpi, alpha=False).save(png)
        if pymupdf4llm:
            try:
                md = pymupdf4llm.to_markdown(str(pdf), pages=[page - 1], write_images=False, show_progress=False, use_ocr=False)
            except Exception as exc:                                      # noqa: BLE001
                md = f'(pymupdf4llm non riuscito: {exc})'
            (out_dir / f'{stem}_pymupdf4llm.md').write_text(md, encoding='utf-8')
        jobs.append((stem, png))

    # 2) modello
    import mlx.core as mx
    from mlx_vlm import apply_chat_template, generate, load
    from mlx_vlm.utils import load_config

    rss0 = rss_gb()
    t0 = time.time()
    model, processor = load(str(model_dir))
    config = load_config(str(model_dir))
    mx.eval(model.parameters())
    t_load = time.time() - t0
    peak_load = mx.get_peak_memory() / 1e9
    print(f'Modello caricato in {t_load:.1f} s | RAM MLX dopo il caricamento: {mx.get_active_memory() / 1e9:.2f} GB '
          f'(picco {peak_load:.2f} GB) | RAM processo: {rss_gb():.2f} GB (prima {rss0:.2f})\n', flush=True)

    # 3) pagine
    prompt = apply_chat_template(processor, config, args.prompt, num_images=1)
    print('Prompt inviato al modello:', repr(prompt), '\n', flush=True)
    lines = [f'Modello: {model_dir}', f'Caricamento: {t_load:.1f} s | RAM MLX attiva {mx.get_active_memory() / 1e9:.2f} GB | picco {peak_load:.2f} GB',
             f'Prompt: {args.prompt!r} | dpi {args.dpi} | max token {args.max_token}', '']
    peak_all = peak_load
    for stem, png in jobs:
        mx.reset_peak_memory()
        t1 = time.time()
        res = generate(model, processor, prompt, image=[str(png)], max_tokens=args.max_token, temperature=0.0, verbose=False)
        dt = time.time() - t1
        peak = max(mx.get_peak_memory() / 1e9, float(res.peak_memory or 0))
        peak_all = max(peak_all, peak)
        raw = res.text
        (out_dir / f'{stem}_deepseek_grezzo.txt').write_text(raw, encoding='utf-8')
        (out_dir / f'{stem}_deepseek.md').write_text(clean(raw), encoding='utf-8')
        warn = '  <-- ARRIVATO AL LIMITE DI TOKEN: possibile ripetizione/ciclo' if res.generation_tokens >= args.max_token else ''
        row = (f'{stem}: {dt:.1f} s | token generati {res.generation_tokens} ({res.generation_tps:.1f} tok/s) | '
               f'token di ingresso {res.prompt_tokens} | picco RAM MLX {peak:.2f} GB | uscita {len(raw)} caratteri{warn}')
        print(row, flush=True)
        lines.append(row)
        mx.clear_cache()
    summary = f'\nPICCO MASSIMO RAM MLX: {peak_all:.2f} GB | RAM massima del processo: {rss_gb():.2f} GB'
    print(summary)
    (out_dir / 'RISULTATO.txt').write_text('\n'.join(lines) + summary + '\n', encoding='utf-8')
    print(f'\nFATTO. Apri la cartella: {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
