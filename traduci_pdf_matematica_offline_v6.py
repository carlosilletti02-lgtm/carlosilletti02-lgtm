#!/usr/bin/env python3
"""Carta OCR / Matematica V6: PDF digitale -> PDF italiano, 100% offline (Qwen MLX gia' installato).

File NUOVO: non modifica V5, translator.py, worker.py o il libro. Autonomo: non importa nulla da
~/Documents/Codex. Nessuna rete (variabili HF_HUB_OFFLINE ecc.), nessuna dipendenza nuova.

Correzioni GENERALI rispetto alla V5 (nessuna regola legata a un libro o a un font):
  1. Raggruppamento corretto delle parole in righe (V5 raggruppava per (riga, parola): ogni parola era
     una "riga" a se' e ogni simbolo un segnaposto/ritaglio separato).
  2. Parole della lingua scambiate per matematica (Wir, Satz, Sei...) escluse da una lista in file di
     configurazione (lingua_deu.json), non dal codice. Caratteri non rappresentabili -> ritaglio, mai quadratini.
  3. Frammenti di parentesi attaccati alla matematica (es. "(u,", "R)") inclusi nella formula.
  4. Riferimenti ((6.3), 6.1) e citazioni ([60, Kap. IX]) restano TESTO tradotto, non immagini.
  5. Frammenti senza parole naturali adiacenti a un'equazione vengono assorbiti nel suo ritaglio.
  6. Paragrafi interrotti da equazioni display sono tradotti come UNA frase (tag <E1>).
  7. Tag ASCII <F1>/<E1>; stacco dei tag/numeri iniziali e finali; frasi come unita'; validazione
     (tag, ordine delle equazioni, numeri, residuo della lingua); scala di recupero a 5 livelli;
     cache che registra anche i fallimenti e dipende da modello+prompt+glossario.
  8. Impaginazione a righe con baseline reale: nessuna rottura dentro una formula, nessun
     punto/virgola staccato, righe alte spingono quelle successive, scala dal corpo reale del libro.
  9. Rapporto con controlli automatici ("avvisi"), compatibile con lo schema di V5 (da_rivedere).

Esempio:
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  "$PY" traduci_pdf_matematica_offline_v6.py --original "$HOME/Desktop/978-3-658-41641-6.pdf" \\
      --output /percorso/nuovo.pdf --start-page 194 --end-page 220
Prova di sola impaginazione, senza Qwen: --fake
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

for _k, _v in {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "NO_PROXY": "*", "no_proxy": "*"}.items():
    os.environ[_k] = _v

import pymupdf as fitz

HERE = Path(__file__).resolve().parent
SUPPORT = Path.home() / 'Library/Application Support/CartaOCR'
DEFAULT_MODEL = SUPPORT / 'models/qwen3.5-9b'
USER_GLOSSARY = SUPPORT / 'glossario.json'
PROMPT_VERSION = 'v6.0'
PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 51
BODY_SIZE = 10.9
LINE_HEIGHT = 16.2
BOTTOM = PAGE_H - 55
MAX_CHARS, MAX_TAGS = 1100, 16

TAG_RE = re.compile(r'<([FE])(\d+)>')
MATH_CHARS = set('∑∏∫∮√∞≤≥≈≠≡∂∇∈∉⊂⊆⊃⊇∪∩∀∃→←↔⇒⇔⊗⊕⊥∥⟂⋅·≃≅⟨⟩∧∨ℝℂℕℤℚαβγδεζηθικλμνξοπρστυφχψω∆Δ⇀↦±∓=<>^_×÷')
MATH_NAMES = {'lim', 'inf', 'sup', 'sin', 'cos', 'tan', 'div', 'grad', 'det', 'ker', 'max', 'min', 'argmax', 'argmin'}
ROMAN_BULLET = re.compile(r'^\(?[ivxlcdm]{1,5}\)[,.]?$', re.I)
REF_PAREN = re.compile(r'^\(\d+(?:\.\d+)+\)[.,;:]?$')
REF_DOTTED = re.compile(r'^\d+(?:\.\d+)+[.,;:]?$')
BAD_TRANSLATION = re.compile(r'[�]|(?:\*\*\?)|[\x00-\x08\x0b-\x1f]')
LIGATURES = str.maketrans({'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
                           'ﬅ': 'st', 'ﬆ': 'st'})
NATURAL = re.compile(r'[^\W\d_]{3,}')
NATURAL_LONG = re.compile(r'[^\W\d_]{7,}')

CFG: dict = {}
VETO: set = set()
RESIDUO: set = set()
TITOLI: tuple = ()
ABBREV: set = set()
FONT_OBJ = None
WORDLETTERS: set = set()
LEXICON: set = set()
FIGURES_ON = True
CAPTIONS: tuple = ()


def configure(path):
    """Carica le liste della lingua (tutto cio' che e' specifico del tedesco sta nel JSON, non nel codice)."""
    global CFG, VETO, RESIDUO, TITOLI, ABBREV, WORDLETTERS, CAPTIONS
    CFG = json.loads(Path(path).read_text(encoding='utf-8'))
    VETO = {w.lower() for w in CFG.get('veto_matematica', [])}
    RESIDUO = {w.lower() for w in CFG.get('residuo', [])}
    TITOLI = tuple(CFG.get('titoli', []))
    ABBREV = set(CFG.get('abbreviazioni', []))
    CAPTIONS = tuple(k.replace(' ', '') for k in CFG.get('didascalie', []))
    WORDLETTERS = set(CFG.get('lettere_parola', []))   # lettere singole che in questa lingua sono parole (en: a, I)


def choose_font(requested=None):
    paths = ([Path(requested).expanduser()] if requested else []) + [
        Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
        Path('/Library/Fonts/Arial Unicode.ttf'),
        Path('/System/Library/Fonts/Supplemental/Helvetica.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    ]
    for path in paths:
        if path.is_file():
            return path
    raise RuntimeError('Nessun font Unicode locale disponibile: usa --font /percorso/font.ttf')


def norm_lig(s):
    return str(s).translate(LIGATURES)


# ----------------------------------------------------------------------------------------------
# Classificazione
# ----------------------------------------------------------------------------------------------

def is_math_char(c):
    o = ord(c)
    return (c in MATH_CHARS or 0x2190 <= o <= 0x22FF or 0x2100 <= o <= 0x214F or 0x27C0 <= o <= 0x27EF
            or 0x2980 <= o <= 0x2AFF or 0x0391 <= o <= 0x03A9 or 0x03B1 <= o <= 0x03C9 or 0x03D0 <= o <= 0x03F5
            or 0x1D400 <= o <= 0x1D7FF or o in (0x00B1, 0x00D7, 0x00F7, 0x2032, 0x2033, 0x2034, 0x00B7, 0x2212, 0x2206))


def build_lexicon(doc, first, last, max_pages=60):
    """Parole che nel documento compaiono anche in minuscolo (campione di pagine): lessico della lingua, ricavato dal libro."""
    pages = list(range(first, last + 1))
    if len(pages) > max_pages:
        step = len(pages) / max_pages
        pages = [pages[int(i * step)] for i in range(max_pages)]
    lex = set()
    for n in pages:
        for w in doc[n - 1].get_text('words'):
            t = norm_lig(w[4]).strip('.,;:!?()[]{}"\'')
            if len(t) >= 3 and t.isalpha() and t.islower():
                lex.add(t)
    return lex


def unrenderable(s):
    """True se la parola contiene caratteri che il font italiano non sa disegnare (-> ritaglio, mai quadratini)."""
    if FONT_OBJ is None:
        return False
    for c in s:
        if c.isspace():
            continue
        if ord(c) < 32 or not FONT_OBJ.has_glyph(ord(c)):
            return True
    return False


def word_is_math(text):
    s = text.strip().strip('.,;:!?')
    if not s:
        return False
    if s.lower() in VETO:                      # parola della lingua, non una variabile
        return False
    if s in WORDLETTERS:
        return False
    if ROMAN_BULLET.fullmatch(s):
        return True
    if any(is_math_char(c) for c in s):
        return True
    if s in ('R', 'N', 'Z', 'C', 'Q', 'I', 'X', 'Y', 'G', 'F', 'J', 'W', 'L', 'S', 'A', 'B'):
        return True
    if (len(s) >= 3 and s[0].isupper() and s.isalpha() and s.lower() in LEXICON
            and s.lower() not in MATH_NAMES):          # "Beam" se nel documento esiste "beam": e' una parola
        return False
    if re.fullmatch(r'[XYZFGWSAB][a-z]{1,3}', s) or re.fullmatch(r'[fgwxy][a-z]?(?:nk|n|k|i|j|pi|ij)', s):
        return True
    if len(s) == 1 and s.isalpha():
        return True
    if s.lower() in MATH_NAMES:
        return True
    if re.search(r'[A-Za-z]\(|\)[A-Za-z0-9]|\d[A-Za-z]|[A-Za-z]\d|[A-Za-z]_[A-Za-z0-9]', s):
        return True
    if any(c.isdigit() for c in s):
        return True
    return False


def is_bracket_fragment(t):
    """'(u,' 'R)' '(X*' '[(x': pezzi di parentesi attaccati a una formula."""
    s = t.strip()
    if not s or not any(c in '()[]{}|' for c in s) or len(s) > 6:
        return False
    return not NATURAL.search(s)


SPLIT_TAIL = re.compile(r'^(?P<head>.+?)(?P<tail>[-–][^\W\d_]{4,}[^\w]*)$')


def split_embedded(words, ctx):
    """'C2,σ-Regularität' -> formula 'C2,σ' + testo '-Regularität' (stesso confine tipografico del PDF)."""
    out = []
    for w in words:
        t = norm_lig(w[4])
        m = SPLIT_TAIL.match(t)
        if (m and m.group('tail').lstrip('-–').rstrip('.,;:)').lower() not in MATH_NAMES
                and word_is_math(t) and word_is_math(m.group('head'))):
            x0, x1 = w[0], w[2]
            bx = None
            letters = m.group('tail').lstrip('-–')[:4]
            for sx0, sx1, st in ctx.spans.get((int(w[5]), int(w[6])), []):
                if sx0 > x0 + 1 and sx1 <= x1 + 1.5 and letters in st:
                    bx = sx0
                    break
            if bx is None:
                bx = x0 + (x1 - x0) * len(m.group('head')) / len(t)
            out.append((x0, w[1], bx, w[3], m.group('head'), w[5], w[6], w[7]))
            out.append((bx, w[1], x1, w[3], m.group('tail'), w[5], w[6], w[7]))
        else:
            out.append(w)
    return out


def lines_of(words, ctx):
    """Righe VISIVE: le righe di PyMuPDF con apici/pedici impilati (baseline entro mezzo corpo) si fondono."""
    groups = defaultdict(list)
    for w in words:
        groups[(int(w[5]), int(w[6]))].append(w)
    keys = sorted(groups)
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    xr = {k: (min(w[0] for w in groups[k]), max(w[2] for w in groups[k])) for k in keys}
    for i, a in enumerate(keys):
        ba = ctx.baselines.get(a)
        for b in keys[i + 1:]:
            bb = ctx.baselines.get(b)
            if ba is None or bb is None:
                continue
            if abs(ba - bb) < 0.5 * ctx.body and not (xr[a][1] + 8 < xr[b][0] or xr[b][1] + 8 < xr[a][0]):
                parent[find(b)] = find(a)
    merged = defaultdict(list)
    for k in keys:
        merged[find(k)].append(k)
    result = []
    for ks in merged.values():
        ws = sorted([w for k in ks for w in groups[k]], key=lambda t: t[0])
        result.append((max(ks, key=lambda k: len(groups[k])), ws))
    result.sort(key=lambda r: r[0])
    return result


def classify_words(lines, ctx):
    """(parole piatte, testi, flag matematica, id riga, baseline). Citazioni, riferimenti e numeri isolati = testo."""
    flat, line_id, base_of = [], [], []
    for li, (main, ws) in enumerate(lines):
        for w in ws:
            flat.append(w)
            line_id.append(li)
            base_of.append(ctx.baselines.get(main))
    texts = [norm_lig(w[4]) for w in flat]
    n = len(flat)
    forced = [False] * n
    i = 0
    while i < n:                                            # citazioni [60, Kap. IX] e [12]
        t = texts[i]
        if t.startswith('[') and not t.startswith('[['):
            j = None
            for k in range(i, min(n, i + 14)):
                if int(flat[k][5]) != int(flat[i][5]):
                    break
                if texts[k].rstrip('.,;:').endswith(']'):
                    j = k
                    break
            if j is not None:
                span = ' '.join(texts[i:j + 1])
                inner = span.replace('[', '').replace(']', '')
                natural = bool(re.search(r'[A-Za-zÄÖÜäöüß]{3,}', inner))
                single = bool(re.fullmatch(r'\[\d+\][.,;:]?', span))
                if (natural or single) and not any(is_math_char(c) for c in inner):
                    for k in range(i, j + 1):
                        forced[k] = True
                    i = j + 1
                    continue
        i += 1
    flags = [(not forced[k]) and (word_is_math(texts[k]) or unrenderable(texts[k])) for k in range(n)]

    def near(a, b, limit):
        return line_id[a] == line_id[b] and -1.5 <= flat[b][0] - flat[a][2] <= limit

    for k in range(n):                                     # (6.3), 6.1: testo se non incollati a una formula
        if flags[k] and not forced[k] and (REF_PAREN.match(texts[k]) or REF_DOTTED.match(texts[k])):
            math_prev = k > 0 and flags[k - 1] and near(k - 1, k, 1.2)
            math_next = k + 1 < n and flags[k + 1] and near(k, k + 1, 1.2)
            if not math_prev and not math_next:
                flags[k] = False
    for _ in range(3):                                      # frammenti di parentesi vicini a formule
        changed = False
        for k in range(n):
            if flags[k] or forced[k] or not is_bracket_fragment(texts[k]):
                continue
            if (k > 0 and flags[k - 1] and near(k - 1, k, 5)) or (k + 1 < n and flags[k + 1] and near(k, k + 1, 5)):
                flags[k] = True
                changed = True
        if not changed:
            break
    for k in range(n):                                      # "loc", "max" in corpo ridotto accanto a una formula
        h = flat[k][3] - flat[k][1]
        if (not flags[k] and not forced[k] and h < 0.82 * ctx.med_h and re.search(r'[^\W_]', texts[k])
                and ((k > 0 and flags[k - 1] and near(k - 1, k, 2.5)) or (k + 1 < n and flags[k + 1] and near(k, k + 1, 2.5)))):
            flags[k] = True
    cand = set()                                            # numeri interi isolati (186, 6, "Satz 2"), non apici/pedici
    for k in range(n):
        if flags[k] and not forced[k] and re.fullmatch(r'\d{1,4}[.,;:]?', texts[k]):
            h, base = flat[k][3] - flat[k][1], base_of[k]
            if base is not None and h >= 0.88 * ctx.med_h and -0.8 <= flat[k][3] - base <= 4.2:
                cand.add(k)
    for k in sorted(cand):
        pv = k > 0 and line_id[k - 1] == line_id[k] and flags[k - 1] and (k - 1) not in cand
        nx = k + 1 < n and line_id[k + 1] == line_id[k] and flags[k + 1] and (k + 1) not in cand
        if not pv and not nx:
            flags[k] = False
    return flat, texts, flags, line_id, base_of


def image_crop(page, rect, ctx=None, baseline=None, scale=3.0, pad_x=2.0, pad_r=None):
    r = fitz.Rect(rect)
    r.x0 -= pad_x; r.x1 += (pad_x if pad_r is None else pad_r)
    r.y0 -= 2.0; r.y1 += 2.0
    r &= page.rect
    if ctx is not None:                                     # controllo: righe vicine catturate in parte
        for ln in ctx.page_lines:
            inter = ln & r
            if ln.get_area() > 0 and not inter.is_empty and inter.get_area() / ln.get_area() < 0.6 and inter.height > 1.0 \
                    and not fitz.Rect(rect).intersects(ln):
                ctx.contaminati += 1
                break
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=r, alpha=False, colorspace=fitz.csRGB)
    asc = (baseline - r.y0) if baseline is not None else r.height * 0.77
    asc = min(max(asc, 0.0), r.height)
    return {'image': pix.tobytes('png'), 'width': r.width, 'height': r.height, 'ascent': asc, 'rect': tuple(r)}


def make_prose(page, words, ctx):
    """Testo con tag <F1>... e ritagli per le formule in linea (una formula = una sequenza contigua)."""
    lines = lines_of(words, ctx)
    flat, texts, flags, line_id, base_of = classify_words(lines, ctx)
    formulas, line_tokens = [], []
    pos = 0
    for main, line in lines:
        out, run = [], []
        base = ctx.baselines.get(main)

        def flush(tight=False):
            if not run:
                return
            rect = fitz.Rect(run[0][:4])
            for tk in run[1:]:
                rect |= fitz.Rect(tk[:4])
            lt, punct, pad_r = norm_lig(run[-1][4]), '', None
            if len(lt) > 1 and lt[-1] in '.,;:' and word_is_math(lt[:-1]):
                cut = max(rect.x0 + 1.0, run[-1][2] - 0.28 * ctx.body)   # punto/virgola finale: testo, non immagine
                if cut < rect.x1:
                    rect.x1, punct, pad_r = cut, lt[-1], 0.0
            if tight and pad_r is None:
                pad_r = 0.0
            formulas.append(image_crop(page, rect, ctx, baseline=base, pad_r=pad_r))
            out.append('<F%d>' % len(formulas) + punct)
            run.clear()

        for w in line:
            k = pos
            pos += 1
            if flags[k]:
                if run and (w[0] - run[-1][2] > 9):
                    flush()
                run.append(w)
            else:
                glue = bool(run) and texts[k][:1] in '-–.,;:' and (w[0] - run[-1][2]) <= 1.5
                flush(tight=glue)
                if (glue or texts[k] in ('.', ',', ';', ':')) and out:
                    out[-1] += texts[k]                     # "<F1>-Regularität", "<F2>," senza spazio
                else:
                    out.append(texts[k])
        flush()
        line_tokens.append(out)
    parts = []
    for toks in line_tokens:                                # a capo: "Funktio- nen" e "Poisson- Gleichung"
        if not toks:
            continue
        if parts:
            prev, first = parts[-1], toks[0]
            if (not TAG_RE.fullmatch(prev) and prev.endswith('-') and len(prev) > 2
                    and not TAG_RE.fullmatch(first) and first[:1].isalpha()):
                parts[-1] = (prev[:-1] if first[:1].islower() else prev) + first
                parts.extend(toks[1:])
                continue
        parts.extend(toks)
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip(), formulas


def long_natural(tokens):
    """Una parola della lingua di 7+ lettere non compare dentro una formula (es. '-Regularität')."""
    return any(NATURAL_LONG.search(t) and t.lower().strip('.,;:') not in MATH_NAMES for t in tokens)


def looks_like_equation(words, rect, page):
    if not words:
        return False
    texts = [norm_lig(w[4]) for w in words]
    if long_natural(texts):
        return False
    alpha = [t for t in texts if re.search(r'[A-Za-zÀ-ÿ]{3,}', t)]
    if rect.y0 < 0.13 * page.rect.height and len([t for t in alpha if len(t) >= 4]) >= 2:
        return False
    if ROMAN_BULLET.match(texts[0]):
        return False
    german = sum(1 for t in texts if t.lower().strip('.,;:') in RESIDUO)
    symbol_count = sum(word_is_math(t) for t in texts)
    if german >= 1 and len(alpha) >= 2:
        return False
    if len(alpha) >= 5:
        return False
    if symbol_count >= 1 and symbol_count / len(texts) >= .47:
        return True
    if rect.x0 >= page.rect.width * .27 and symbol_count >= 1 and len(alpha) <= 2:
        return True
    if not alpha and symbol_count:
        return True
    return False


def is_pure_math_block(words, raw_text):
    normalized = raw_text.strip()
    if not words:
        return bool(normalized) and (bool(re.search(r'[⎛⎝⎞⎠⎡⎣⎤⎦⎧⎨⎩⎫⎬⎭∫∑∏]', normalized))
                                     or all(ord(c) < 32 or c.isspace() for c in normalized))
    tokens = [norm_lig(w[4]) for w in words]
    if long_natural(tokens) or any(t.lower().strip('.,;:') in RESIDUO for t in tokens):
        return False
    normal_prose = [t for t in tokens if re.fullmatch(r'[A-Za-zÄÖÜäöüß]{3,}', t) and t.lower() not in MATH_NAMES]
    math_n = sum(word_is_math(t) for t in tokens)
    operators = sum(1 for t in tokens if any(ch in t for ch in '=≤≥∇∑∫±∓≠≡'))
    return len(normal_prose) <= 1 and len(tokens) >= 3 and (operators >= 2 or math_n / len(tokens) >= .60)


def is_heading(text):
    t = text.lstrip()
    if len(t) > 140:
        return False
    return t.startswith(TITOLI) or bool(re.match(r'^<F\d+>\s+[A-ZÄÖÜ]', t) and len(t) < 90) or bool(re.match(r'^\d+(\.\d+)+\s', t))


def merge_split_lines(entries, ctx):
    """PyMuPDF a volte spezza una riga in due blocchi (apici/pedici): stessa baseline e parole adiacenti -> un blocco."""
    out = []
    for e in entries:
        prev = out[-1] if out else None
        if prev and 'words' in prev and 'words' in e and prev['words'] and e['words']:
            la = max(prev['words'], key=lambda w: (int(w[5]), int(w[6]), w[0]))
            la_key = (int(la[5]), int(la[6]))
            last_line = [w for w in prev['words'] if (int(w[5]), int(w[6])) == la_key]
            fb = min(e['words'], key=lambda w: (int(w[5]), int(w[6]), w[0]))
            fk = (int(fb[5]), int(fb[6]))
            first_line = [w for w in e['words'] if (int(w[5]), int(w[6])) == fk]
            ba, bb = ctx.baselines.get(la_key), ctx.baselines.get(fk)
            if ba is not None and bb is not None and abs(ba - bb) < 0.5 * ctx.body:
                gap = min(w[0] for w in first_line) - max(w[2] for w in last_line)
                if -20 <= gap <= 8:
                    prev['words'] = prev['words'] + e['words']
                    prev['rect'] = prev['rect'] | e['rect']
                    prev['raw'] += ' ' + e['raw']
                    continue
        out.append(e)
    return out


def realign_words(words, raw):
    """In alcuni PDF i numeri dei blocchi delle parole non coincidono con quelli del dizionario (i blocchi fatti solo di
    simboli spostano la numerazione): le parole finirebbero nel blocco sbagliato e le righe si fonderebbero a caso.
    Si riassegnano per POSIZIONE solo le parole il cui (blocco, riga) non contiene il loro centro; con numerazione
    coerente non cambia nulla. Restituisce (parole, quante spostate)."""
    lines, cand = {}, []
    for bid, block in enumerate(raw):
        if block.get('type') != 0:
            continue
        bno = block.get('number', bid)
        for lno, ln in enumerate(block.get('lines', [])):
            text = norm_lig(''.join(str(sp.get('text', '')) for sp in ln.get('spans', []))).replace(' ', '')
            lines[(bno, lno)] = (fitz.Rect(ln['bbox']), text)
            cand.append((bno, lno))

    def inside(rect, cx, cy):
        return rect.x0 - 1 <= cx <= rect.x1 + 1 and rect.y0 - 1 <= cy <= rect.y1 + 1
    out, moved = [], 0
    for w in words:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        cur = lines.get((int(w[5]), int(w[6])))
        if cur and inside(cur[0], cx, cy):
            out.append(w)
            continue
        wt = norm_lig(w[4]).replace(' ', '')
        hits = [k for k in cand if inside(lines[k][0], cx, cy)]
        pool = [k for k in hits if wt and wt in lines[k][1]] or hits
        if not pool:
            out.append(w)
            continue
        k = min(pool, key=lambda kk: lines[kk][0].get_area())
        out.append((w[0], w[1], w[2], w[3], w[4], k[0], k[1], w[7]))
        moved += 1
    return out, moved


def find_figures(page, entries, body=10.0):
    """Figure (vettoriali o miste): cluster di tratti grandi (>= 8 tratti, >= 100x50 pt) uniti alle immagini che
    li toccano. I blocchi di testo/immagine che stanno DENTRO la regione (le etichette del disegno) escono dal
    flusso del testo: la figura resta un'immagine unica. Passo ADDITIVO: senza figure non cambia nulla.
    Restituisce [(regione, indici assorbiti, indice di ancoraggio)]."""
    try:
        clusters = [fitz.Rect(r) for r in page.cluster_drawings()]
        drawings = page.get_drawings()
    except Exception:                                       # noqa: BLE001
        return []
    pw, ph = page.rect.width, page.rect.height
    regions = []
    for r in clusters:
        if r.width < 100 or r.height < 50 or r.get_area() > 0.8 * pw * ph:
            continue
        if sum(1 for d in drawings if d['rect'].intersects(r)) < 8:
            continue
        regions.append(fitz.Rect(r))
    if not regions:
        return []
    merged = True
    while merged:                                           # regioni che si toccano = una figura
        merged = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                if regions[i].intersects(regions[j]):
                    regions[i] |= regions[j]
                    del regions[j]
                    merged = True
                    break
            if merged:
                break
    for r in regions:                                       # immagini incorporate che toccano la figura
        for e in entries:
            if 'visual' in e and r.intersects(e['visual']) and (r & e['visual']).get_area() > 0.3 * e['visual'].get_area():
                r |= e['visual']
    def is_caption(e):
        return 'raw' in e and bool(CAPTIONS) and e['raw'].replace(' ', '').startswith(CAPTIONS)

    def is_label(e):                                        # legenda/etichetta: breve, corpo piu' piccolo, non didascalia
        return ('raw' in e and e.get('words') and 0 < len(e['raw'].strip()) <= 120
                and 0 < e.get('size', 0) <= 0.92 * body and not is_caption(e))

    def box_of(e):
        return e['visual'] if 'visual' in e else e['rect']
    found = []
    for r in regions:
        idxs = set()
        for _ in range(3):
            grew = False
            for i, e in enumerate(entries):
                if i in idxs or is_caption(e):
                    continue
                box = box_of(e)
                if box.get_area() > 0 and (box & r).get_area() >= 0.5 * box.get_area():
                    idxs.add(i)
                    continue
                if is_label(e):
                    gap = max(box.y0 - r.y1, r.y0 - box.y1, 0)
                    if gap <= 14 and min(box.x1, r.x1) - max(box.x0, r.x0) > 0:
                        idxs.add(i)
                        r |= box
                        grew = True
            if not grew:
                break
        running = sum(len(e['raw']) for i, e in enumerate(entries) if i in idxs and 'raw' in e)
        if running > 700 and r.get_area() > 0.45 * pw * ph:   # una cornice attorno al testo corrente non e' una figura
            continue
        later = [i for i, e in enumerate(entries) if i not in idxs and box_of(e).y0 >= r.y0]
        anchor = min(idxs) if idxs else (later[0] if later else len(entries))
        found.append((r, idxs, anchor))
    return found


def collect_page(page):
    """Blocchi della pagina, con la stessa textpage per parole e blocchi (numerazione coerente)."""
    tp = page.get_textpage(flags=fitz.TEXTFLAGS_DICT)
    raw = tp.extractDICT().get('blocks', [])
    words_raw, realigned = realign_words(tp.extractWORDS(), raw)
    all_words = defaultdict(list)
    for w in words_raw:
        all_words[int(w[5])].append(w)
    baselines, sizes, page_lines, spans = {}, Counter(), [], {}
    for bid, block in enumerate(raw):
        if block.get('type') != 0:
            continue
        bno = block.get('number', bid)
        for lno, line in enumerate(block.get('lines', [])):
            c = Counter()
            for sp in line.get('spans', []):
                n = len(str(sp.get('text', '')).strip())
                if n:
                    c[round(sp['origin'][1], 2)] += n
                    sizes[round(sp.get('size', 0), 1)] += n
            if c:
                baselines[(bno, lno)] = c.most_common(1)[0][0]
            spans[(bno, lno)] = [(sp['bbox'][0], sp['bbox'][2], str(sp.get('text', ''))) for sp in line.get('spans', [])]
            page_lines.append(fitz.Rect(line['bbox']))
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    heights = sorted(w[3] - w[1] for ws in all_words.values() for w in ws) or [10.0]
    ctx = SimpleNamespace(baselines=baselines, page_lines=page_lines, contaminati=0, spans=spans,
                          body=body, med_h=heights[len(heights) // 2])
    entries = []
    for bid, block in enumerate(raw):
        bno = block.get('number', bid)
        if block.get('type') == 1:
            entries.append({'visual': fitz.Rect(block['bbox'])})
            continue
        if block.get('type') != 0:
            continue
        raw_text = ' '.join(' '.join(str(sp.get('text', '')) for sp in ln.get('spans', [])) for ln in block.get('lines', []))
        bsz = Counter()
        for ln in block.get('lines', []):
            for sp in ln.get('spans', []):
                bsz[round(sp.get('size', 0), 1)] += len(str(sp.get('text', '')).strip())
        entries.append({'words': split_embedded(all_words.get(bno, []), ctx), 'rect': fitz.Rect(block['bbox']),
                        'raw': raw_text, 'size': bsz.most_common(1)[0][0] if bsz else 0})
    entries = merge_split_lines(entries, ctx)
    absorbed, anchors = set(), defaultdict(list)
    for region, idxs, anchor in (find_figures(page, entries, body) if FIGURES_ON else []):
        absorbed |= idxs
        anchors[anchor].append(region)
    result = []
    for ei, e in enumerate(entries):
        for region in anchors.get(ei, []):
            result.append({'kind': 'figure', 'rect': region})
        if ei in absorbed:
            continue
        if 'visual' in e:
            result.append({'kind': 'visual', 'rect': e['visual']})
            continue
        words, rect, raw_text = e['words'], e['rect'], e['raw']
        if not words:
            if is_pure_math_block([], raw_text):
                result.append({'kind': 'equation', 'rect': rect})
            continue
        text = ' '.join(norm_lig(w[4]) for w in words)
        if is_pure_math_block(words, raw_text):
            result.append({'kind': 'equation', 'rect': rect})
            continue
        has_lang = any(t.lower().strip('.,;:') in RESIDUO for t in text.split())
        is_eq = False if (has_lang and re.search(r'[a-zäöüß]{3}', text)) else looks_like_equation(words, rect, page)
        if len(words) <= 2 and re.fullmatch(r'\(\d+(?:\.\d+)*\)', text.strip()):
            result.append({'kind': 'equation', 'rect': rect})   # numero d'equazione: resta con la sua equazione
            continue
        if len(words) <= 2 and re.fullmatch(r'[0-9.\s\-()]+', text):
            continue                                        # numero di pagina
        if len(words) <= 2 and not any(c.isalpha() for c in text):
            if is_eq:
                result.append({'kind': 'equation', 'rect': rect})
            continue
        if is_eq:
            result.append({'kind': 'equation', 'rect': rect})
            continue
        ptext, formulas = make_prose(page, words, ctx)
        if ptext:
            result.append({'kind': 'prose', 'text': ptext, 'formulas': formulas, 'rect': rect,
                           'heading': is_heading(ptext)})
    for region in anchors.get(len(entries), []):
        result.append({'kind': 'figure', 'rect': region})
    left = min([e['rect'].x0 for e in entries if 'words' in e and e['words']] or [0.0])
    result = absorb_fragments(result, left, page.rect.width)
    result = group_equation_blocks(page, result, ctx)
    result = merge_across_equations(result)
    return result, {'body': body, 'contaminati': ctx.contaminati, 'riallineate': realigned}


def absorb_fragments(items, left, width, gap_limit=19.0):
    """Frammenti senza parole naturali accanto a un'equazione ne fanno parte ('(X*', 'du dv'). Idem righe BREVI e
    RIENTRATE con sole parole funzionali ('0 für w ∈ B', 'falls'): voci di una definizione a tratti."""
    def is_frag(it):
        if it['kind'] != 'prose':
            return False
        nw = [w for w in NATURAL.findall(TAG_RE.sub(' ', it['text'])) if w.lower() not in MATH_NAMES]
        if not nw:
            return True
        return (len(nw) <= 2 and all(w.lower() in RESIDUO for w in nw) and it['rect'].x0 > left + 0.18 * width
                and len(it['text'].split()) <= 14)
    for _ in range(4):
        changed = False
        for i, it in enumerate(items):
            if not is_frag(it):
                continue
            for j in (i - 1, i + 1):
                if 0 <= j < len(items) and items[j]['kind'] == 'equation':
                    a, b = fitz.Rect(items[j]['rect']), fitz.Rect(it['rect'])
                    if max(b.y0 - a.y1, a.y0 - b.y1, 0) <= gap_limit:
                        items[i] = {'kind': 'equation', 'rect': b}
                        changed = True
                        break
        if not changed:
            break
    return items


def group_equation_blocks(page, items, ctx, gap_limit=19.0):
    grouped, pending = [], []

    def flush():
        if not pending:
            return
        area = fitz.Rect(pending[0])
        for r in pending[1:]:
            area |= fitz.Rect(r)
        grouped.append({'kind': 'equation', 'visual': image_crop(page, area, ctx, pad_x=3.5), 'parts': len(pending), 'rect': area})
        pending.clear()

    for item in items:
        if item['kind'] == 'equation':
            r = fitz.Rect(item['rect'])
            if pending:
                area = fitz.Rect(pending[0])
                for old in pending[1:]:
                    area |= fitz.Rect(old)
                if max(r.y0 - area.y1, area.y0 - r.y1, 0) > gap_limit or (area | r).height > page.rect.height * .48:
                    flush()
            pending.append(r)
        else:
            flush()
            grouped.append(item)
    flush()
    return grouped


def first_natural_word(text):
    m = re.search(r'[^\W\d_]{2,}', TAG_RE.sub(' ', text))
    return m.group(0) if m else ''


def mergeable(a, b):
    ta = TAG_RE.sub(' ', a['text']).strip()
    if re.search(r'[.!?]\s*$', ta):
        return False
    w = first_natural_word(b['text'])
    return bool(w) and w[0].islower()


def merge_across_equations(items):
    """prosa + equazione display + prosa che continua la frase = UNA unita' di traduzione (tag <E1>)."""
    out, i = [], 0
    while i < len(items):
        it = items[i]
        if it['kind'] == 'prose':
            cur = dict(it)
            cur['equations'] = []
            cur['merged'] = 0
            while (i + 2 < len(items) and items[i + 1]['kind'] == 'equation' and 'visual' in items[i + 1]
                   and items[i + 2]['kind'] == 'prose' and mergeable(cur, items[i + 2])):
                cur['equations'].append(items[i + 1]['visual'])
                nxt, off = items[i + 2], len(cur['formulas'])
                shifted = TAG_RE.sub(lambda m: f'<F{int(m.group(2)) + off}>', nxt['text'])
                cur['text'] = f"{cur['text']} <E{len(cur['equations'])}> {shifted}"
                cur['formulas'] = cur['formulas'] + nxt['formulas']
                cur['merged'] += 1
                i += 2
            out.append(cur)
        else:
            out.append(it)
        i += 1
    return out


# ----------------------------------------------------------------------------------------------
# Traduzione
# ----------------------------------------------------------------------------------------------

class Failure(Exception):
    pass


def has_natural(s):
    return bool([w for w in NATURAL.findall(TAG_RE.sub(' ', s)) if w.lower() not in MATH_NAMES])


def count_tags(s):
    return len(TAG_RE.findall(s))


def split_sentences(text):
    out, start = [], 0
    for m in re.finditer(r'([.!?])\s+(?=[A-ZÄÖÜ<])', text):
        end = m.end(1)
        prev = text[start:end]
        last = prev.split()[-1] if prev.split() else ''
        base = last.rstrip('.!?')
        if m.group(1) == '.' and (base in ABBREV or len(base) <= 1 or re.fullmatch(r'\d+', base)
                                  or re.fullmatch(r'[A-Za-z]\.[A-Za-z]', base)):
            continue
        out.append(prev.strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


def split_long(s):
    if len(s) <= MAX_CHARS and count_tags(s) <= MAX_TAGS:
        return [s]
    cuts = [m.end() for m in re.finditer(r'[,;:]\s+', s)] + [m.start() for m in re.finditer(r'<E\d+>', s)]
    cuts = [c for c in cuts if 20 < c < len(s) - 20]
    if not cuts:
        cuts = [m.end() for m in re.finditer(r'\s+', s) if 20 < m.end() < len(s) - 20]
    if not cuts:
        return [s]
    c = min(cuts, key=lambda x: abs(x - len(s) / 2))
    a, b = s[:c].strip(), s[c:].strip()
    if not a or not b:
        return [s]
    return split_long(a) + split_long(b)


def split_chunks(text):
    chunks, cur = [], ''
    for sent in split_sentences(text):
        for piece in split_long(sent):
            cand = (cur + ' ' + piece).strip()
            if cur and (len(cand) > MAX_CHARS or count_tags(cand) > MAX_TAGS):
                chunks.append(cur)
                cur = piece
            else:
                cur = cand
    if cur:
        chunks.append(cur)
    return chunks


TAG_ONLY = re.compile(r'^<[FE]\d+>[.,;:]?$')
NUM_TOKEN = re.compile(r'^[\d.,§()\[\]-]+$')


def peel(chunk):
    """Stacca tag e numeri iniziali, tag finali: non passano dal modello e tornano al loro posto."""
    toks = chunk.split()
    i = 0
    while i < len(toks) and (TAG_ONLY.match(toks[i]) or NUM_TOKEN.match(toks[i])):
        i += 1
    j = len(toks)
    while j > i and TAG_ONLY.match(toks[j - 1]):
        j -= 1
    return toks[:i], toks[i:j], toks[j:]


def renumber(text):
    maps = {'F': {}, 'E': {}}

    def sub(m):
        k, n = m.group(1), int(m.group(2))
        if n not in maps[k]:
            maps[k][n] = len(maps[k]) + 1
        return f'<{k}{maps[k][n]}>'
    out = TAG_RE.sub(sub, text)
    inv = {k: {v: g for g, v in mp.items()} for k, mp in maps.items()}
    return out, inv


def restore(text, inv):
    return TAG_RE.sub(lambda m: f"<{m.group(1)}{inv[m.group(1)].get(int(m.group(2)), int(m.group(2)))}>", text)


def clean(out):
    out = re.sub(r'<think>.*?</think>', '', str(out), flags=re.S)
    out = re.sub(r'\(Riporta[^)]*\)', '', out)
    out = re.sub(r'<(?![FE]\d+>)([^<>\n]{1,40})>', r'\1', out)       # il modello a volte avvolge parole in <...>
    return re.sub(r'\s+', ' ', out).strip()


def validate(src, out):
    """(problema grave | None, avvisi). Mai accettare tag persi, equazioni riordinate, numeri cambiati, residuo."""
    if not out.strip():
        return 'traduzione vuota', []
    if BAD_TRANSLATION.search(out):
        return 'caratteri corrotti', []
    s_tags, o_tags = TAG_RE.findall(src), TAG_RE.findall(out)
    if sorted(s_tags) != sorted(o_tags):
        return 'tag modificati o mancanti', []
    if [t for t in s_tags if t[0] == 'E'] != [t for t in o_tags if t[0] == 'E']:
        return 'ordine delle equazioni modificato', []
    if sorted(re.findall(r'\d+', TAG_RE.sub(' ', src))) != sorted(re.findall(r'\d+', TAG_RE.sub(' ', out))):
        return 'numeri modificati', []
    words = re.findall(r'[^\W\d_]+', TAG_RE.sub(' ', out).lower())
    left = [w for w in words if w in RESIDUO]
    if len(left) >= 2 or (len(left) == 1 and len(words) <= 6):
        return 'parole non tradotte: ' + ', '.join(sorted(set(left))[:5]), []
    if len(src) >= 40 and out.strip() == src.strip():
        return 'nessuna traduzione', []
    soft = []
    if [t for t in s_tags if t[0] == 'F'] != [t for t in o_tags if t[0] == 'F']:
        soft.append('ordine delle formule cambiato (ammesso)')
    ratio = len(TAG_RE.sub('', out)) / max(1, len(TAG_RE.sub('', src)))
    if len(src) >= 60 and not (0.45 <= ratio <= 2.2):
        soft.append(f'lunghezza anomala (rapporto {ratio:.2f})')
    return None, soft


def load_glossary():
    gl = dict(CFG.get('glossario', {}))
    try:
        data = json.loads(USER_GLOSSARY.read_text(encoding='utf-8'))
        gl.update({k: v for k, v in data.get(CFG.get('lingua', 'deu'), {}).items() if isinstance(v, str)})
    except (OSError, ValueError, AttributeError):
        pass
    return gl


def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


def fix_references(text):
    """Dentro le citazioni [60, Kap. IX, Satz 1] applica la tabella 'riferimenti' della lingua (non il modello)."""
    refs = CFG.get('riferimenti', {})
    if not refs:
        return text

    def sub(m):
        inner = m.group(0)
        for k, v in refs.items():
            inner = re.sub(r'(?<![^\W_])' + re.escape(k) + r'(?![^\W_])', v, inner)
        return inner
    return re.sub(r'\[[^\[\]]{1,70}\]', sub, text)


class Translator:
    def __init__(self, model_path, glossary, cache_path, fake=False, retry_failed=False):
        self.fake, self.glossary, self.cache_path, self.retry_failed = fake, glossary, cache_path, retry_failed
        self.stats = Counter()
        self.model_name = Path(model_path).name
        self.gl_hash = hashlib.sha256(json.dumps(glossary, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
        try:
            data = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        self.cache = {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
        if not fake:
            from mlx_vlm import load
            self.model, self.processor = load(str(model_path))
            self.tok = getattr(self.processor, 'tokenizer', self.processor)

    # -- modello
    def _llm(self, messages, length):
        from mlx_vlm import generate
        try:
            prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                  enable_thinking=False)
        except TypeError:
            prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        self.stats['chiamate_qwen'] += 1
        try:
            r = generate(self.model, self.processor, prompt, temperature=0.0, max_tokens=max(256, length * 3), verbose=False)
        except TypeError:
            r = generate(self.model, self.processor, prompt, max_tokens=max(256, length * 3), verbose=False)
        return str(getattr(r, 'text', r))

    def _system(self, core):
        nome = CFG.get('nome_lingua', 'tedesco')
        rules = (f'Sei un traduttore tecnico di testi matematici e ingegneristici. Traduci dal {nome} all’italiano il testo '
                 'dell’utente, fedelmente e per intero: non riassumere, non spiegare, non completare frasi interrotte. '
                 'I tag <F1>, <F2>, … sono formule nel testo; i tag <E1>, <E2>, … sono equazioni su riga separata. '
                 'Copia ogni tag IDENTICO, una sola volta, nello stesso ordine in cui compaiono; non tradurli, non aggiungerne, '
                 'non toglierne, anche all’inizio o alla fine. Traduci tutte le parole, anche brevi. '
                 'Mantieni invariati numeri, riferimenti e sigle. Rispondi solo con la traduzione.')
        terms = {k: v for k, v in self.glossary.items() if k.lower() in core.lower()}
        if terms:
            rules += ' Terminologia da usare: ' + '; '.join(f'{k} = {v}' for k, v in terms.items()) + '.'
        return rules

    def _msgs(self, core, reminder=False):
        m = [{'role': 'system', 'content': self._system(core)}]
        for a, b in CFG.get('esempi', []):
            m += [{'role': 'user', 'content': a}, {'role': 'assistant', 'content': b}]
        content = core
        if reminder:
            tags = ' '.join(f'<{k}{n}>' for k, n in TAG_RE.findall(core))
            content += f"\n\n(Riporta in questo ordine tutti i tag: {tags}. Traduci ogni parola {CFG.get('nome_lingua', 'tedesca')}.)" \
                if tags else f"\n\n(Traduci ogni parola {CFG.get('nome_lingua', 'tedesca')}.)"
        m.append({'role': 'user', 'content': content})
        return m

    # -- scala di recupero
    def _key(self, core):
        return hashlib.sha256(f'{PROMPT_VERSION}|{self.model_name}|{self.gl_hash}|{core}'.encode('utf-8')).hexdigest()

    def _store(self, key, out, level, soft):
        self.cache[key] = {'it': out, 'livello': level, 'avvisi': soft}
        write_json(self.cache_path, self.cache)
        self.stats[f'livello_{level}'] += 1
        return out, level, soft

    def translate_core(self, core, allow_split=True):
        key = self._key(core)
        hit = self.cache.get(key)
        if hit and not (hit.get('errore') and self.retry_failed):
            if hit.get('errore'):
                self.stats['cache_fallimenti'] += 1
                raise Failure(hit['errore'])
            self.stats['cache'] += 1
            return hit['it'], hit.get('livello', 1), hit.get('avvisi', [])
        if self.fake:
            return core, 1, []
        last = 'nessun tentativo'
        for level, reminder in ((1, False), (2, True)):
            cand = clean(self._llm(self._msgs(core, reminder), len(core)))
            hard, soft = validate(core, cand)
            if not hard:
                return self._store(key, cand, level, soft)
            last = hard
        if allow_split:
            sents = split_sentences(core)
            if len(sents) > 1:
                try:
                    pieces = []
                    for s in sents:
                        s_l, inv = renumber(s)
                        if not has_natural(s_l):
                            pieces.append(s)
                            continue
                        o, _, _ = self.translate_core(s_l, allow_split=False)
                        pieces.append(restore(o, inv))
                    cand = ' '.join(pieces)
                    hard, soft = validate(core, cand)
                    if not hard:
                        return self._store(key, cand, 3, soft + ['tradotto per frasi'])
                    last = hard
                except Failure as exc:
                    last = str(exc)
        cand = self._segmentwise(core)
        if cand is not None:
            hard, soft = validate(core, cand)
            if not hard:
                return self._store(key, cand, 4, soft + ['tradotto a segmenti: ordine locale da controllare'])
            last = hard
        self.cache[key] = {'errore': last}
        write_json(self.cache_path, self.cache)
        self.stats['livello_5_fallito'] += 1
        raise Failure(last)

    def _segmentwise(self, core):
        out = []
        for p in re.split(r'(<[FE]\d+>)', core):
            if not p or TAG_RE.fullmatch(p) or not has_natural(p):
                out.append(p)
                continue
            body = p.strip()
            lead, trail = p[:len(p) - len(p.lstrip())], p[len(p.rstrip()):]
            cand = clean(self._llm(self._msgs_fragment(body), len(body)))
            if not cand:
                return None
            out.append(lead + cand + trail)
        return ''.join(out)

    def _msgs_fragment(self, body):
        nome = CFG.get('nome_lingua', 'tedesco')
        rules = (f'Traduci dal {nome} all’italiano questo frammento di frase (può essere incompleto): non completarlo e non '
                 'aggiungere nulla. Mantieni invariati numeri e sigle. Rispondi solo con la traduzione.')
        terms = {k: v for k, v in self.glossary.items() if k.lower() in body.lower()}
        if terms:
            rules += ' Terminologia da usare: ' + '; '.join(f'{k} = {v}' for k, v in terms.items()) + '.'
        return [{'role': 'system', 'content': rules}, {'role': 'user', 'content': body}]

    def translate_unit(self, text):
        outs, level, problems, warns = [], 0, [], []
        for ch in split_chunks(text):
            lead, core_toks, trail = peel(ch)
            core = ' '.join(core_toks)
            if not core or not has_natural(core):
                outs.append(ch)
                continue
            core_l, inv = renumber(core)
            try:
                o, lv, soft = self.translate_core(core_l)
                o = restore(o, inv)
                level, warns = max(level, lv), warns + soft
            except Failure as exc:
                problems.append({'testo': ch[:180], 'motivo': str(exc)[:200]})
                o = '[DA RIVEDERE: testo non tradotto] ' + core
                level = 5
            outs.append(' '.join(x for x in (' '.join(lead), o, ' '.join(trail)) if x))
        return fix_references(' '.join(outs)), level, problems, warns


# ----------------------------------------------------------------------------------------------
# Impaginazione a righe con baseline reale
# ----------------------------------------------------------------------------------------------

def clusters(text):
    """Cluster non spezzabili: parola+tag+punteggiatura attaccati, e formule separate solo da spazi."""
    cur = None
    for raw in text.split():
        for piece in [p for p in re.split(r'(<E\d+>)', raw) if p]:
            m = re.fullmatch(r'<E(\d+)>', piece)
            if m:
                if cur:
                    yield ('c', cur)
                    cur = None
                yield ('d', int(m.group(1)))
                continue
            parts = []
            for s in re.split(r'(<F\d+>)', piece):
                if not s:
                    continue
                t = TAG_RE.fullmatch(s)
                parts.append(('a', int(t.group(2))) if t else ('w', s))
            if cur and cur[-1][0] == 'a' and parts[0][0] == 'a':
                cur = cur + [('g', None)] + parts
            else:
                if cur:
                    yield ('c', cur)
                cur = parts
    if cur:
        yield ('c', cur)


class Writer:
    def __init__(self, fontfile, fake=False):
        self.doc = fitz.open()
        self.fontpath = fontfile
        self.font = fitz.Font(fontfile=str(fontfile))
        self.fake = fake
        self.page = None
        self.y = 82.0
        self.factor = 1.1
        self.source = 1
        self.page_count = 0
        self.avvisi = []
        self.text_asc, self.text_desc = 0.80 * BODY_SIZE, 0.26 * BODY_SIZE
        self.space = self.font.text_length(' ', fontsize=BODY_SIZE)
        self._glyph_ok = {}

    def new_page(self, source, continued=False):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page.insert_font(fontname='CartaIT', fontfile=str(self.fontpath))
        self.y = 82.0
        self.page_count += 1
        self.source = source
        header = f'TRADUZIONE ITALIANA  |  pagina PDF originale {source}' + ('  (continua)' if continued else '')
        if self.fake:
            header = '[TEST SENZA QWEN]  ' + header
        self.page.insert_text((MARGIN, 38), header, fontname='CartaIT', fontsize=9, color=(.37, .37, .37))
        self.page.draw_line(fitz.Point(MARGIN, 47), fitz.Point(PAGE_W - MARGIN, 47), color=(.7, .7, .7), width=.5)

    def need(self, height):
        if self.page is None:
            self.new_page(self.source)
        if self.y + height > BOTTOM:
            self.new_page(self.source, continued=True)

    def glyph_ok(self, token):
        bad = []
        for c in token:
            if c not in self._glyph_ok:
                self._glyph_ok[c] = ord(c) >= 32 and bool(self.font.has_glyph(ord(c)))
            if not self._glyph_ok[c]:
                bad.append(c)
        return bad

    def measure(self, parts, formulas):
        out = []
        for kind, val in parts:
            if kind == 'w':
                bad = self.glyph_ok(val)
                if bad:
                    self.avvisi.append(f'glifo mancante nel testo: {val[:30]!r}')
                out.append({'k': 'w', 'text': val, 'w': self.font.text_length(val, fontsize=BODY_SIZE),
                            'asc': self.text_asc, 'desc': self.text_desc})
            elif kind == 'a':
                if not 1 <= val <= len(formulas):
                    continue
                c = formulas[val - 1]
                f = self.factor
                out.append({'k': 'a', 'img': c['image'], 'w': c['width'] * f, 'asc': c['ascent'] * f,
                            'desc': (c['height'] - c['ascent']) * f})
            else:
                out.append({'k': 'g', 'w': 2.2 * self.factor, 'asc': 0, 'desc': 0})
        return out

    def emit_line(self, line, avail):
        x, asc, desc, items = MARGIN, self.text_asc, self.text_desc, []
        for ci, parts in enumerate(line):
            if ci:
                x += self.space
            for p in parts:
                p['x'] = x
                x += p['w']
                asc, desc = max(asc, p['asc']), max(desc, p['desc'])
                items.append(p)
        height = max(LINE_HEIGHT, asc + desc + 3.5)
        self.need(height)
        base = self.y + (height - asc - desc) / 2 + asc
        for p in items:
            if p['k'] == 'w':
                self.page.insert_text((p['x'], base), p['text'], fontname='CartaIT', fontsize=BODY_SIZE, color=(.09, .09, .09))
            elif p['k'] == 'a':
                self.page.insert_image(fitz.Rect(p['x'], base - p['asc'], p['x'] + p['w'], base + p['desc']),
                                       stream=p['img'], keep_proportion=False)
        self.y += height

    def write_paragraph(self, text, formulas, equations, heading=False):
        avail = PAGE_W - 2 * MARGIN
        line, width = [], 0.0
        for kind, payload in clusters(text):
            if kind == 'd':
                if line:
                    self.emit_line(line, avail)
                    line, width = [], 0.0
                if 1 <= payload <= len(equations):
                    self.write_display(equations[payload - 1])
                continue
            parts = self.measure(payload, formulas)
            if not parts:
                continue
            w = sum(p['w'] for p in parts)
            if w > avail:                                   # formula piu' larga della riga: scala le sole immagini
                atoms = sum(p['w'] for p in parts if p['k'] == 'a')
                rest = w - atoms
                k = max(0.5, (avail - rest) / atoms) if atoms else 1.0
                for p in parts:
                    if p['k'] == 'a':
                        p['w'] *= k; p['asc'] *= k; p['desc'] *= k
                w = sum(p['w'] for p in parts)
                if k < 0.75 or w > avail:
                    self.avvisi.append(f'formula in linea ridotta a {k:.2f}')
            add = w + (self.space if line else 0)
            if line and width + add > avail:
                self.emit_line(line, avail)
                line, width, add = [], 0.0, w
            line.append(parts)
            width += add
        if line:
            self.emit_line(line, avail)
        self.y += 7.8 if heading else 5.3

    def write_display(self, crop):
        avail = PAGE_W - 2 * MARGIN
        scale = min(self.factor, avail / max(1, crop['width']), (PAGE_H - 175) / max(1, crop['height']))
        if scale < 0.75 * self.factor:
            self.avvisi.append(f'equazione ridotta a {scale / self.factor:.2f} del formato originale')
        w, h = crop['width'] * scale, crop['height'] * scale
        self.need(h + 16)
        left = MARGIN + (avail - w) / 2
        self.page.insert_image(fitz.Rect(left, self.y + 8, left + w, self.y + 8 + h), stream=crop['image'], keep_proportion=False)
        self.y += h + 16

    def save(self, target):
        self.doc.save(str(target), garbage=3, deflate=True)
        self.doc.close()


# ----------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='PDF matematico -> italiano offline, V6')
    ap.add_argument('--original', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--start-page', type=int, default=1)
    ap.add_argument('--end-page', type=int)
    ap.add_argument('--model', help='cartella del modello Qwen MLX locale (opzionale)')
    ap.add_argument('--font', help='font Unicode locale, opzionale')
    ap.add_argument('--config', default=str(HERE / 'lingua_deu.json'), help='liste della lingua (JSON)')
    ap.add_argument('--fake', action='store_true', help='solo impaginazione, NON traduce')
    ap.add_argument('--riprova-falliti', action='store_true', help='ritenta anche i passaggi falliti in cache')
    ap.add_argument('--senza-figure', action='store_true', help='disattiva la conservazione delle figure (comportamento precedente)')
    args = ap.parse_args()
    global FIGURES_ON
    FIGURES_ON = not args.senza_figure
    source, output = Path(args.original).expanduser().resolve(), Path(args.output).expanduser().resolve()
    if not source.is_file():
        ap.error(f'Libro non trovato: {source}')
    if source == output or output.exists():
        ap.error('Scegli un nome nuovo: il PDF originale e gli output esistenti non vengono sovrascritti')
    if not output.parent.is_dir():
        ap.error('Cartella di output non trovata')
    configure(args.config)
    font = choose_font(args.font)
    global FONT_OBJ
    FONT_OBJ = fitz.Font(fontfile=str(font))
    cache_path, report_path = output.with_suffix('.cache.json'), output.with_suffix('.rapporto.json')
    model = Path(args.model).expanduser() if args.model else DEFAULT_MODEL
    if not args.fake and not (model / 'config.json').is_file():
        ap.error(f'Modello non trovato: {model}')
    translator = Translator(model, load_glossary(), cache_path, fake=args.fake, retry_failed=args.riprova_falliti)
    writer = Writer(font, args.fake)
    report = {'versione': 'v6-generale', 'originale': str(source), 'output': str(output), 'offline': True,
              'test_senza_qwen': args.fake, 'prompt': PROMPT_VERSION, 'modello': translator.model_name,
              'nota': 'Controlli automatici in "avvisi". Resta necessaria una revisione matematica manuale.',
              'pagine': [], 'unita_tradotte': 0, 'equazioni_display': 0, 'formule_inline': 0,
              'unita_fuse_attraverso_equazioni': 0, 'figure_conservate': 0, 'parole_riallineate': 0, 'ritagli_con_testo_vicino': 0, 'da_rivedere': 0, 'pagine_italiane': 0}
    try:
        with fitz.open(source) as original:
            last = args.end_page or len(original)
            if args.start_page < 1 or last < args.start_page or last > len(original):
                ap.error(f'Pagine non valide; il documento contiene {len(original)} pagine')
            global LEXICON
            LEXICON = build_lexicon(original, args.start_page, last)
            for physical in range(args.start_page, last + 1):
                page = original[physical - 1]
                writer.source = physical
                writer.new_page(physical)
                writer.avvisi = []
                items, info = collect_page(page)
                writer.factor = min(1.5, max(0.8, BODY_SIZE / info['body']))
                rec = {'pagina_pdf_originale': physical, 'testi_tradotti': 0, 'formule_preservate': 0,
                       'da_rivedere': [], 'avvisi': []}
                report['ritagli_con_testo_vicino'] += info['contaminati']
                report['parole_riallineate'] += info['riallineate']
                for it in items:
                    if it['kind'] == 'figure':
                        writer.write_display(image_crop(page, it['rect'], scale=4.0, pad_x=3.0))
                        rec['figure_conservate'] = rec.get('figure_conservate', 0) + 1
                        report['figure_conservate'] += 1
                        continue
                    if it['kind'] in ('equation', 'visual'):
                        crop = it.get('visual') or image_crop(page, it['rect'])
                        writer.write_display(crop)
                        rec['formule_preservate'] += 1
                        report['equazioni_display'] += 1
                        continue
                    report['formule_inline'] += len(it['formulas'])
                    report['unita_fuse_attraverso_equazioni'] += it.get('merged', 0)
                    out, level, problems, warns = translator.translate_unit(it['text'])
                    writer.write_paragraph(out, it['formulas'], it.get('equations', []), it['heading'])
                    rec['testi_tradotti'] += 1
                    report['unita_tradotte'] += 1
                    if problems:
                        rec['da_rivedere'].extend(problems)
                        report['da_rivedere'] += len(problems)
                    rec['avvisi'].extend(w for w in warns if 'ammesso' not in w)
                rec['avvisi'].extend(writer.avvisi)
                if rec.get('figure_conservate'):
                    rec['avvisi'].append(f"{rec['figure_conservate']} figura/e conservata/e come immagine: le scritte nel disegno restano nella lingua originale")
                if info['riallineate']:
                    rec['avvisi'].append(f"numerazione dei blocchi del PDF incoerente: {info['riallineate']} parole riassegnate per posizione")
                if info['contaminati']:
                    rec['avvisi'].append(f"{info['contaminati']} ritagli catturano in parte righe di testo vicine")
                report['pagine'].append(rec)
                print(f'Pagina PDF {physical}/{last} · unita {rec["testi_tradotti"]} · equazioni {rec["formule_preservate"]}'
                      f' · da rivedere {len(rec["da_rivedere"])} · avvisi {len(rec["avvisi"])}', flush=True)
        writer.save(output)
        report['pagine_italiane'] = writer.page_count
        report['statistiche_traduzione'] = dict(translator.stats)
        write_json(report_path, report)
        print('\nPDF italiano creato:', output)
        print('Rapporto:', report_path)
        print('Passaggi da rivedere:', report['da_rivedere'], '| statistiche:', dict(translator.stats))
    except Exception:
        writer.doc.close()
        raise


if __name__ == '__main__':
    main()
