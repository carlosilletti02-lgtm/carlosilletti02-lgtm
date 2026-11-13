#!/usr/bin/env python3
"""Scarica DeepSeek-OCR 2 (versione MLX bf16) in una cartella locale. E' l'UNICO passaggio che usa Internet.

Cosa fa:
  1. controlla lo spazio libero (servono circa 7 GB);
  2. scarica da Hugging Face il repository 'mlx-community/DeepSeek-OCR-2-bf16' in
     ~/Library/Application Support/CartaOCR/models/deepseek-ocr-2   (non tocca Qwen ne' altro);
  3. NON scarica i file *.py del repository (codice dell'autore del modello): mlx_vlm ha gia' la propria
     implementazione e noi non eseguiamo codice scaricato. Con --anche-py li scarica comunque;
  4. verifica ogni file pesante confrontando dimensione e impronta SHA-256 con quelle pubblicate da Hugging Face;
  5. scrive LEGGIMI_VERSIONE.txt con repository, versione (commit) e data, per ritrovare esattamente cosa hai usato.

Se si interrompe, rilancia lo stesso comando: riprende da dove era (non cancella e non riscarica i file gia' completi).

Uso:
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  cd "$HOME/Desktop/CartaOCR_Progetto/05_V6_in_sviluppo"
  "$PY" -B strumenti_test/scarica_deepseek_ocr2.py
"""
import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = 'mlx-community/DeepSeek-OCR-2-bf16'
DEST = Path.home() / 'Library/Application Support/CartaOCR/models/deepseek-ocr-2'
NEED_GB = 10.0                          # 6,8 GB di pesi + margine


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description='Scarica DeepSeek-OCR 2 (MLX bf16) in locale')
    ap.add_argument('--repo', default=REPO)
    ap.add_argument('--cartella', type=Path, default=DEST)
    ap.add_argument('--anche-py', action='store_true', help='scarica anche i file .py del repository (non necessari)')
    args = ap.parse_args()

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print('ERRORE: huggingface_hub non e\' installato in questo Python.', file=sys.stderr)
        return 2

    dest = args.cartella.expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(dest.parent).free / 1e9
    print(f'Repository : {args.repo}\nDestinazione: {dest}\nSpazio libero: {free_gb:.0f} GB (ne servono ~{NEED_GB:.0f})')
    if free_gb < NEED_GB:
        print('ERRORE: spazio insufficiente.', file=sys.stderr)
        return 2
    print('\nATTENZIONE: questo e\' l\'unico passaggio che usa Internet. Dopo, tutto il lavoro e\' offline.\n')

    api = HfApi()
    try:
        info = api.model_info(args.repo, files_metadata=True)
    except Exception as exc:                                            # noqa: BLE001
        print(f'ERRORE: impossibile leggere il repository ({exc}). Sei connesso a Internet?', file=sys.stderr)
        return 2
    heavy = [s for s in info.siblings if getattr(s, 'lfs', None)]
    total = sum((s.size or 0) for s in info.siblings if args.anche_py or not s.rfilename.endswith('.py'))
    print(f'Versione (commit): {info.sha}\nFile da scaricare: circa {total / 1e9:.2f} GB\n')

    ignore = ['.gitattributes'] + ([] if args.anche_py else ['*.py'])
    path = Path(snapshot_download(repo_id=args.repo, revision=info.sha, local_dir=str(dest), ignore_patterns=ignore))

    print('\nVerifica dei file pesanti (dimensione + SHA-256)...')
    bad = 0
    for s in heavy:
        f = path / s.rfilename
        if not f.is_file():
            print(f'  MANCA   {s.rfilename}'); bad += 1; continue
        ok_size = f.stat().st_size == s.size
        ok_hash = ok_size and sha256(f) == s.lfs.sha256
        print(f'  {"OK     " if ok_hash else "ERRORE "} {s.rfilename}  ({f.stat().st_size / 1e9:.2f} GB)')
        bad += 0 if ok_hash else 1
    if bad:
        print(f'\nATTENZIONE: {bad} file non corrispondono. Rilancia il comando; se persiste, cancella la cartella {dest} e riprova.')
        return 1

    (path / 'LEGGIMI_VERSIONE.txt').write_text(
        f'Repository: {args.repo}\nCommit: {info.sha}\nScaricato: {datetime.now():%Y-%m-%d %H:%M}\n'
        f'File .py dell\'autore scaricati: {"si" if args.anche_py else "no (non servono a mlx_vlm)"}\n'
        'Licenza dichiarata dal repository: verificare la scheda del modello prima di pubblicare qualcosa.\n', encoding='utf-8')
    print(f'\nFATTO. Modello pronto in: {path}\nOra puoi lanciare strumenti_test/prova_deepseek_ocr2.py (offline).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
