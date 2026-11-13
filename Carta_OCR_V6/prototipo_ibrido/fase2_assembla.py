#!/usr/bin/env python3
"""FASE 2 dell'ibrido: trasforma l'uscita di DeepSeek in Markdown VERIFICATO contro il testo digitale del PDF.

Non usa nessun modello (solo PyMuPDF): si puo' rilanciare all'infinito sulla cache della fase 1.

Idea: nei libri con testo digitale il PDF conosce gia' le lettere, i numeri e i simboli di ogni formula. DeepSeek da' la
STRUTTURA (LaTeX, indici, frazioni, matrici) ma puo' sbagliare un simbolo. Quindi, per ogni zona:
  - EQUAZIONE: i simboli del LaTeX (lettere, cifre, greche, operatori) devono coincidere, in numero, con quelli che il PDF
    contiene in quel riquadro. Coincidono -> si tiene il LaTeX. Non coincidono (o il LaTeX e' malformato) -> si usa il
    RITAGLIO dell'originale (come fa V6) e il motivo va nel rapporto.
  - Riparazioni sicure PRIMA del confronto: parole tedesche dentro le formule ("f u r" -> "für", riprese dal PDF), comandi
    incollati (\\colonR -> \\colon R), R maiuscola -> \\mathbb{R} in contesti di insiemi.
  - TESTO: le parole sbagliate da DeepSeek ("beratendes") si correggono con le parole vere del PDF; le differenze di
    simboli nelle formule in linea sono segnalate nel rapporto.
  - FIGURE: ritaglio dell'originale.

Uso:
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  "$PY" -B fase2_assembla.py --cartella lavoro
Produce uscita/<data ora>/  <nome>_p<NNNN>.md  +  formule/ + figure/  +  RAPPORTO.txt  +  rapporto.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent

BLOCK = re.compile(r'<\|ref\|>(\w+)<\|/ref\|>\s*<\|det\|>(.*?)<\|/det\|>\n?(.*?)(?=<\|ref\|>|\Z)', re.S)
MATH_SPAN = re.compile(r'(\\\(.*?\\\)|\\\[.*?\\\])', re.S)
WORD = re.compile(r'[A-Za-zÀ-ÖØ-öø-ÿ]+')            # parole in alfabeto latino (le lettere greche incollate, es. "Ωexistiert", restano fuori)

# ----------------------------------------------------------------------------------------------- tabelle simboli
GREEK = {'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε', 'varepsilon': 'ε', 'zeta': 'ζ', 'eta': 'η',
         'theta': 'θ', 'vartheta': 'θ', 'iota': 'ι', 'kappa': 'κ', 'varkappa': 'κ', 'lambda': 'λ', 'mu': 'μ', 'nu': 'ν',
         'xi': 'ξ', 'pi': 'π', 'varpi': 'π', 'rho': 'ρ', 'varrho': 'ρ', 'sigma': 'σ', 'varsigma': 'σ', 'tau': 'τ',
         'upsilon': 'υ', 'phi': 'φ', 'varphi': 'φ', 'chi': 'χ', 'psi': 'ψ', 'omega': 'ω', 'Gamma': 'Γ', 'Delta': 'Δ',
         'Theta': 'Θ', 'Lambda': 'Λ', 'Xi': 'Ξ', 'Pi': 'Π', 'Sigma': 'Σ', 'Upsilon': 'Υ', 'Phi': 'Φ', 'Psi': 'Ψ', 'Omega': 'Ω'}
SYMBOLS = {**GREEK,
           'leq': '≤', 'le': '≤', 'leqslant': '≤', 'geq': '≥', 'ge': '≥', 'geqslant': '≥', 'neq': '=', 'ne': '=',
           'approx': '≈', 'equiv': '≡', 'sim': '∼', 'in': '∈', 'notin': '∈', 'subset': '⊂', 'subseteq': '⊆',
           'subsetneq': '⊂', 'supset': '⊃', 'supseteq': '⊇', 'cup': '∪', 'cap': '∩', 'times': '×', 'cdot': '·',
           'ast': '∗', 'to': '→', 'rightarrow': '→', 'longrightarrow': '−→', 'Rightarrow': '⇒', 'Longrightarrow': '=⇒',
           'implies': '⇒', 'Leftrightarrow': '⇔', 'Longleftrightarrow': '⇔', 'iff': '⇔', 'leftarrow': '←',
           'longleftarrow': '←', 'mapsto': '↦', 'longmapsto': '↦', 'partial': '∂', 'nabla': '∇', 'infty': '∞',
           'pm': '±', 'mp': '∓', 'wedge': '∧', 'vee': '∨', 'forall': '∀', 'exists': '∃', 'emptyset': '∅',
           'varnothing': '∅', 'prime': '′', 'perp': '⊥', 'propto': '∝', 'ell': 'ℓ', 'hbar': 'ℏ', 'setminus': '∖',
           'backslash': '∖', 'star': '∗', 'bullet': '·', 'cdotp': '·', 'coloneqq': '=', 'eqqcolon': '=',
           'Subset': '⊂⊂', 'Supset': '⊃⊃'}
KEEP_SYMS = set('+−=<>≤≥≈≡∈⊂⊆⊃⊇∪∩×·→⇒⇔←↦∂∇∞±∓∧∨∀∃∅′∗⊥∝∼ℓℏ∖')
FUNCS = {'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'sinh', 'cosh', 'tanh', 'coth', 'arcsin', 'arccos', 'arctan', 'log',
         'ln', 'lg', 'exp', 'lim', 'limsup', 'liminf', 'sup', 'inf', 'max', 'min', 'det', 'dim', 'ker', 'arg', 'deg',
         'gcd', 'hom', 'Pr', 'mod'}
IGNORE = {'left', 'right', 'big', 'Big', 'bigg', 'Bigg', 'bigl', 'bigr', 'Bigl', 'Bigr', 'biggl', 'biggr', 'Biggl', 'Biggr',
          'quad', 'qquad', 'frac', 'dfrac', 'tfrac', 'binom', 'sqrt', 'int', 'iint', 'iiint', 'oint', 'sum', 'prod',
          'coprod', 'bigcup', 'bigcap', 'bigoplus', 'bigotimes', 'mathrm', 'mathbb', 'mathcal', 'mathbf', 'mathit',
          'mathsf', 'mathtt', 'mathfrak', 'mathscr', 'text', 'textrm', 'textbf', 'textit', 'operatorname', 'boldsymbol',
          'bm', 'overline', 'underline', 'bar', 'hat', 'widehat', 'tilde', 'widetilde', 'vec', 'dot', 'ddot',
          'overrightarrow', 'overbrace', 'underbrace', 'overset', 'underset', 'stackrel', 'substack', 'limits',
          'nolimits', 'displaystyle', 'textstyle', 'scriptstyle', 'scriptscriptstyle', 'colon', 'ldots', 'cdots',
          'dots', 'vdots', 'ddots', 'not', 'neg', 'lceil', 'rceil', 'lfloor', 'rfloor', 'lVert', 'rVert', 'langle',
          'rangle', 'vert', 'Vert', 'mid', 'lbrace', 'rbrace', 'phantom', 'hphantom', 'vphantom', 'hspace', 'vspace',
          'hline', 'cline', 'label', 'nonumber', 'notag', 'tag', 'Box', 'square', 'blacksquare', 'qed', 'top',
          'bullet', 'circ', 'dagger', 'degree', 'cdotp', 'tilde', 'mathop', 'mathrel', 'mathbin', 'mathpunct',
          'begin', 'end', 'array', 'cases', 'aligned', 'align', 'pmatrix', 'bmatrix', 'vmatrix', 'matrix', 'smallmatrix',
          'eqnarray', 'gathered', 'split', 'tfrac', 'atop', 'over', 'choose', 'imath', 'jmath', 'Leftarrow',
          'leftrightarrow', 'hookrightarrow', 'rightharpoonup', 'lesssim', 'gtrsim', 'll', 'gg', 'subsetneqq',
          'nsubseteq', 'nrightarrow', 'triangle', 'angle', 'parallel', 'cong', 'simeq', 'asymp', 'aleph', 'Re', 'Im',
          'wp', 'oplus', 'otimes', 'odot', 'bigwedge', 'bigvee', 'lor', 'land', 'lnot', 'mathbbm', 'unicode', 'nu',
          'downarrow', 'uparrow', 'Downarrow', 'Uparrow', 'nearrow', 'searrow', 'swarrow', 'nwarrow', 'vdash', 'models',
          'ddagger', 'diamond', 'lbrack', 'rbrack', 'triangleq', 'rightleftharpoons', 'longleftrightarrow', 'Longleftarrow',
          'twoheadrightarrow', 'curvearrowright', 'varsubsetneq', 'subsetneq', 'supsetneq', 'nleq', 'ngeq', 'prec',
          'succ', 'preceq', 'succeq', 'between', 'ominus', 'boxtimes', 'bowtie', 'lhd', 'rhd', 'dashv', 'amalg', 'uplus',
          'sqcup', 'sqcap', 'sqsubseteq', 'sqsupseteq', 'wr', 'iota', 'partialdiff', 'strut', 'mathstrut', 'tiny',
          'small', 'large', 'Large', 'normalsize', 'rm', 'it', 'bf', 'cal', 'scriptsize', 'footnotesize', 'allowbreak',
          'nobreak', 'relax', 'protect', 'hbox', 'mbox', 'raisebox', 'rule', 'kern', 'mkern', 'mskip', 'enspace', 'thinspace',
          'medspace', 'thickspace', 'negthinspace', 'negmedspace', 'negthickspace', 'ensuremath'}
IGNORE -= set(SYMBOLS) | FUNCS
KNOWN = set(SYMBOLS) | FUNCS | IGNORE
CANON = str.maketrans({'ϵ': 'ε', 'ϕ': 'φ', 'ϑ': 'θ', 'ϖ': 'π', 'ϱ': 'ρ', 'ς': 'σ', '∆': 'Δ', 'ß': 'ss'})
MINUS_CHARS = '-–‐‑‒−'


# ----------------------------------------------------------------------------------------------- normalizzazione
def alpha_counter(s: str, case: bool = True, minus: bool = True) -> Counter:
    """Conta lettere, cifre, greche e operatori significativi; ignora parentesi, spazi, punteggiatura e pezzi di simboli grandi."""
    s = unicodedata.normalize('NFKC', s).translate(CANON).replace('\u0338', '')
    s = s.replace('↦', '7→').replace('⟹', '=⇒').replace('⟶', '−→')   # il PDF compone queste frecce con due glifi (come "\\Longrightarrow" = "=" + "⇒")
    out = []
    for c in s:
        if c == '≠':
            c = '='
        elif c == '∉':
            c = '∈'
        elif c in '*⋆':
            c = '∗'
        elif c in '•∙⋅':
            c = '·'
        elif c in MINUS_CHARS:
            if not minus:
                continue
            c = '−'
        cat = unicodedata.category(c)
        if cat in ('Lu', 'Ll', 'Lt', 'Lo') or cat == 'Nd' or c in KEEP_SYMS:
            out.append(c if case else c.lower())
    return Counter(out)


def unacc(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c)).lower()


TOKEN = re.compile(r'\\([A-Za-z]+)|\\(.)|(.)', re.S)


def latex_symbols(tex: str) -> tuple[str, list[str]]:
    """LaTeX -> stringa dei soli simboli visibili (per il confronto) + elenco dei comandi sconosciuti."""
    tex = re.sub(r'\\begin\{(?:array|tabular)\}\{[^}]*\}', '', tex)
    tex = re.sub(r'\\(?:begin|end)\{[A-Za-z*]+\}', '', tex)
    out, unknown = [], []
    for m in TOKEN.finditer(tex):
        name, esc, ch = m.groups()
        if name:
            if name in SYMBOLS:
                out.append(SYMBOLS[name])
            elif name in FUNCS:
                out.append(name)
            elif name not in IGNORE:
                unknown.append(name)
        elif ch:
            out.append('′' if ch == "'" else ch)
    return ''.join(out), unknown


def latex_problems(tex: str, unknown: list[str]) -> list[str]:
    p = []
    if unknown:
        p.append('comandi LaTeX sconosciuti: ' + ', '.join(sorted(set('\\' + u for u in unknown))))
    flat = re.sub(r'\\[{}]', '', tex.replace('\\\\', ''))          # prima gli a-capo "\\\\", poi le graffe letterali \{ \}
    if flat.count('{') != flat.count('}'):
        p.append('graffe non bilanciate')
    if len(re.findall(r'\\left\b', tex)) != len(re.findall(r'\\right\b', tex)):
        p.append('\\left/\\right non appaiati')
    if len(re.findall(r'\\begin\{', tex)) != len(re.findall(r'\\end\{', tex)):
        p.append('\\begin/\\end non appaiati')
    return p


# ----------------------------------------------------------------------------------------------- riparazioni LaTeX
CMD = re.compile(r'\\([A-Za-z]+)')


def split_glued(tex: str, repairs: list[str]) -> str:
    """\\colonR -> \\colon R: separa un comando sconosciuto in prefisso noto + resto."""
    def sub(m):
        name = m.group(1)
        if name in KNOWN:
            return m.group(0)
        for k in range(len(name) - 1, 1, -1):
            if name[:k] in KNOWN:
                repairs.append(f'comando incollato \\{name} -> \\{name[:k]} {name[k:]}')
                return '\\' + name[:k] + ' ' + name[k:]
        return m.group(0)
    return CMD.sub(sub, tex)


SPACED = re.compile(r'(?P<g>[a-zA-Z]\\mathrm\{[a-zA-Z]\}[a-zA-Z])'
                    r'|\\mathrm\{(?P<m>[A-Za-z~ ]*[ ~][A-Za-z~ ]*)\}'
                    r'|(?<![A-Za-z\\{])(?P<b>(?:[a-z] ){2,}[a-z])(?![A-Za-z])')


def restore_words(tex: str, tokens: list[str], repairs: list[str]) -> str:
    """Parole scritte lettera per lettera ("f u r", senza accenti) -> parola vera ripresa dal testo digitale del PDF."""
    pos = [0]

    def find(target: str, retry: bool = True):
        for start in range(pos[0], len(tokens)):
            acc = ''
            for end in range(start, min(start + 4, len(tokens))):
                acc += unacc(tokens[end])
                if acc == target:
                    pos[0] = end + 1
                    return ' '.join(tokens[start:end + 1])
                if len(acc) >= len(target):
                    break
        if retry and pos[0] > 0:
            pos[0] = 0
            return find(target, retry=False)
        return None

    def sub(m):
        raw = m.group(0)
        letters = re.sub(r'[^A-Za-z]', '', raw.replace('\\mathrm', ''))
        word = find(letters.lower())
        if not word:
            return raw
        repairs.append(f'parola nella formula "{raw}" -> "{word}" (dal PDF)')
        return f'\\;\\text{{{word}}}\\;'
    return SPACED.sub(sub, tex)


def fix_reals(tex: str, repairs: list[str], enabled: bool) -> str:
    """R maiuscola isolata in contesti di insiemi (R^d, \\to R, \\subseteq R) -> \\mathbb{R}, solo se la pagina usa gia' \\mathbb{R}."""
    if not enabled:
        return tex
    n = [0]

    def one(m):
        n[0] += 1
        return (m.group(1) if m.lastindex else '') + r'\mathbb{R}'
    tex = re.sub(r'(?<![A-Za-z\\{])R(?=\^)', one, tex)
    tex = re.sub(r'(\\(?:subseteq|subset|to|colon|in|times|cup|cap|mapsto)\s*)R(?![A-Za-z0-9_^({])', one, tex)
    if n[0]:
        repairs.append(f'{n[0]}x R -> \\mathbb{{R}} (la pagina usa gia\' \\mathbb{{R}})')
    return tex


def fix_latex(tex: str, tokens: list[str], has_bb: bool) -> tuple[str, list[str]]:
    repairs: list[str] = []
    tex = split_glued(tex, repairs)
    tex = restore_words(tex, tokens, repairs)
    tex = fix_reals(tex, repairs, has_bb)
    return tex, repairs


# ----------------------------------------------------------------------------------------------- PDF
def to_rect(page: pymupdf.Page, box, pad: float = 0.0) -> pymupdf.Rect:
    r = page.rect
    x0, y0, x1, y1 = box
    return pymupdf.Rect(r.x0 + x0 / 999 * r.width - pad, r.y0 + y0 / 999 * r.height - pad,
                        r.x0 + x1 / 999 * r.width + pad, r.y0 + y1 / 999 * r.height + pad)


def region_words(words, rect: pymupdf.Rect, pad: float = 2.0):
    sel = [w for w in words if rect.x0 - pad <= (w[0] + w[2]) / 2 <= rect.x1 + pad and rect.y0 - pad <= (w[1] + w[3]) / 2 <= rect.y1 + pad]
    sel.sort(key=lambda w: (round((w[1] + w[3]) / 2 / 4), w[0]))
    return sel


def tiny_images(page_imgs, rect: pymupdf.Rect) -> int:
    n = 0
    for im in page_imgs:
        b = pymupdf.Rect(im['bbox'])
        if b.width < 25 and b.height < 25 and rect.x0 - 2 <= (b.x0 + b.x1) / 2 <= rect.x1 + 2 and rect.y0 - 2 <= (b.y0 + b.y1) / 2 <= rect.y1 + 2:
            n += 1
    return n


def word_tokens(ws) -> list[str]:
    """Parole alfabetiche (>=2 lettere) del PDF in ordine di lettura, con le sillabazioni a fine riga ricomposte."""
    out = []
    for w in ws:
        out += [t for t in WORD.findall(unicodedata.normalize('NFKC', w[4])) if len(t) >= 2]
    return out


def hyphen_pairs(ws) -> list[tuple[str, str]]:
    pairs = []
    for a, b in zip(ws, ws[1:]):
        ta, tb = unicodedata.normalize('NFKC', a[4]), unicodedata.normalize('NFKC', b[4])
        if ta.endswith('-') and WORD.findall(ta) and WORD.findall(tb):
            pairs.append((WORD.findall(ta)[-1].lower(), WORD.findall(tb)[0].lower()))
    return pairs


def lev_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def apply_case(orig: str, new: str) -> str:
    if len(new) <= 3:                                     # parole brevi ("Gl."): le maiuscole sono quelle del PDF
        return new
    if len(orig) > 1 and orig.isupper():
        return new.upper()
    if orig[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def md_math(s: str) -> str:
    s = re.sub(r'\\\((.*?)\\\)', lambda m: '$' + m.group(1).strip() + '$', s, flags=re.S)
    return s


def fmt_counter(c: Counter) -> str:
    return ' '.join(f'{k}×{v}' if v > 1 else k for k, v in sorted(c.items()))


# ----------------------------------------------------------------------------------------------- una pagina
def without(c: Counter, skip) -> Counter:
    return Counter({k: v for k, v in c.items() if k not in skip}) if skip else c


def process_page(stem: str, pno: int, pdf_path: Path, raw: str, out: Path, opts, skip=frozenset(), dry: bool = False,
                 coll: dict | None = None) -> tuple[list[str], dict, list[str]]:
    """skip = simboli che questo PDF non contiene nel testo digitale (calibrazione per documento); dry = non scrive file;
    coll = raccoglie, per la calibrazione, i simboli di PDF e LaTeX di tutte le equazioni."""
    doc = pymupdf.open(pdf_path)
    page = doc[pno - 1]
    words = page.get_text('words')
    imgs = page.get_image_info()
    blocks = []
    for m in BLOCK.finditer(raw):
        nums = [int(x) for x in re.findall(r'\d+', m.group(2))]
        if len(nums) >= 4:
            bx = [nums[i:i + 4] for i in range(0, len(nums) - 3, 4)]
            blocks.append(dict(label=m.group(1), box=(min(b[0] for b in bx), min(b[1] for b in bx), max(b[2] for b in bx), max(b[3] for b in bx)),
                               body=m.group(3).strip()))
    log: list[str] = []
    st = Counter()
    md: list[str] = []
    if not blocks:
        log.append('ATTENZIONE: nessun riquadro nell\'uscita di DeepSeek (prompt senza grounding?)')
        return [raw], dict(st), log
    has_bb = '\\mathbb{R}' in raw
    tag = f'{stem}_p{pno:04d}'
    (out / 'formule').mkdir(exist_ok=True)
    (out / 'figure').mkdir(exist_ok=True)

    def crop(rect: pymupdf.Rect, sub: str, name: str, dpi: int) -> str:
        r = pymupdf.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3) & page.rect
        rel = f'{sub}/{name}.png'
        if not dry:
            page.get_pixmap(clip=r, dpi=dpi, alpha=False).save(out / rel)
        return rel

    eq_i = fig_i = 0
    for b in blocks:
        label, body = b['label'], b['body']
        rect = to_rect(page, b['box'])
        ws = region_words(words, rect)
        if label == 'equation':
            eq_i += 1
            st['eq_tot'] += 1
            tex = re.sub(r'^\s*\\\[|\\\]\s*$', '', body).strip()
            tokens = word_tokens(ws)
            pdf_text = ' '.join(w[4] for w in ws)
            wild = tiny_images(imgs, rect)
            # DeepSeek da solo
            s0, unk0 = latex_symbols(tex)
            a_full = alpha_counter(pdf_text)
            a = without(a_full, skip)
            b0 = without(alpha_counter(s0), skip)
            raw_ok = not (a - b0) and sum((b0 - a).values()) <= wild and not latex_problems(tex, unk0)
            st['eq_deepseek_da_solo_ok' if raw_ok else 'eq_deepseek_da_solo_da_scartare'] += 1
            # con le riparazioni
            fixed, reps = fix_latex(tex, tokens, has_bb)
            s1, unk1 = latex_symbols(fixed)
            b1_full = alpha_counter(s1)
            if coll is not None:
                coll['pdf'].update(a_full)
                coll['ltx'].update(b1_full)
                coll['eqs'].update(b1_full.keys())
            b1 = without(b1_full, skip)
            missing, extra = a - b1, b1 - a
            problems = latex_problems(fixed, unk1)
            ok = not missing and sum(extra.values()) <= wild and not problems
            head = f'  equazione {eq_i} [{b["box"]}]'
            if ok:
                st['eq_ok'] += 1
                if reps:
                    st['eq_ok_riparate'] += 1
                body_md = re.sub(r'\\quad\s*\(([\d.]+)\)\s*$', r'\\tag{\1}', fixed)
                md.append('$$\n' + body_md + '\n$$')
                log.append(f'{head}: ACCETTATA' + (' (dopo riparazioni)' if reps else '') + (f' [{wild} simboli-immagine tollerati]' if wild and sum(extra.values()) else ''))
                log += [f'      riparazione: {r}' for r in reps]
            else:
                st['eq_ritaglio'] += 1
                why = problems + ([f'nel PDF e non nel LaTeX: {fmt_counter(missing)}'] if missing else []) + \
                      ([f'nel LaTeX e non nel PDF: {fmt_counter(extra)}'] if sum(extra.values()) > wild else [])
                rel = crop(rect, 'formule', f'{tag}_eq{eq_i:02d}', 300)
                md.append(f'![formula originale (LaTeX non verificato)]({rel})\n\n<!-- LaTeX scartato: {fixed} -->')
                log.append(f'{head}: RITAGLIO DELL\'ORIGINALE -> {rel}')
                log += [f'      motivo: {w}' for w in why]
                log += [f'      riparazione: {r}' for r in reps]
        elif label in ('image', 'figure'):
            fig_i += 1
            st['figure'] += 1
            rel = crop(rect, 'figure', f'{tag}_fig{fig_i:02d}', 200)
            md.append(f'![figura]({rel})')
            log.append(f'  figura {fig_i}: ritaglio {rel}')
        else:
            text, tlog = process_text(body, ws, rect, imgs, has_bb, st, opts, skip)
            md.append(text)
            for t in tlog:
                log.append(f'  [{label}] {t}')
    return md, dict(st), log


def align_prose(spans: list[str], ws, key, log: list[str], st: Counter) -> list[str]:
    """Allineamento ORDINATO tra le parole di DeepSeek e quelle del PDF: dove nello stesso punto DeepSeek ha scritto parole
    diverse da quelle del PDF (es. "ist soll" invece di "stellt") si usano le parole del PDF. Solo se si somigliano abbastanza."""
    occ = []                                              # (indice span, inizio, fine, parola) delle parole di DeepSeek
    for i, seg in enumerate(spans):
        if i % 2 == 0:
            occ += [(i, m.start(), m.end(), m.group(0)) for m in WORD.finditer(seg) if len(m.group(0)) >= 2]
    if not occ:
        return spans
    D = [key(o[3]) for o in occ]
    dset = set(D)
    P: list[str] = []
    Po: list[str] = []

    def unglue(k: str) -> str:
        """"ulund" (variabile incollata a "und") -> "und" se "und" e' una parola di DeepSeek: stessa parola, non una correzione."""
        if k in dset:
            return k
        for c in (1, 2):                                  # solo DAVANTI: in coda "s", "n"... sono desinenze vere ("Funktionals")
            if len(k) - c >= 3 and k[c:] in dset:
                return k[c:]
        return k

    def add(p: str) -> None:
        if len(p) >= 2:
            P.append(unglue(key(p)))
            Po.append(p if len(p) <= 3 else p.lower())        # parole brevi: maiuscole del PDF ("Gl."); le altre le adatta apply_case

    L = list(ws)
    k = 0
    while k < len(L):
        t = unicodedata.normalize('NFKC', L[k][4])
        # frammenti brevi di una stessa parola ("A" "l" "so" = "Also"): si ricompongono se DeepSeek ha quella parola
        j = k
        while j < len(L) and WORD.fullmatch(unicodedata.normalize('NFKC', L[j][4])) and len(L[j][4]) <= 2:
            j += 1
        if j - k >= 2:
            joined = ''.join(unicodedata.normalize('NFKC', L[x][4]) for x in range(k, j))
            if key(joined) in dset:
                add(joined)
                k = j
                continue
        parts = WORD.findall(t)
        if t.endswith('-') and parts and k + 1 < len(L):
            nxt = WORD.findall(unicodedata.normalize('NFKC', L[k + 1][4]))
            if nxt and key(parts[-1] + nxt[0]) in dset:   # sillabazione a fine riga che DeepSeek ha ricomposto
                for p in parts[:-1]:
                    add(p)
                add(parts[-1] + nxt[0])
                for p in nxt[1:]:
                    add(p)
                k += 2
                continue
        for p in parts:
            add(p)
        k += 1
    # il testo digitale spezza a volte una parola a fine riga senza trattino ("Behaup" "tung"): si ricompone se DeepSeek la ha unita
    k = 0
    while k + 1 < len(P):
        if P[k] not in dset and P[k + 1] not in dset and (P[k] + P[k + 1]) in dset:
            P[k:k + 2] = [P[k] + P[k + 1]]
            Po[k:k + 2] = [Po[k] + Po[k + 1]]
        k += 1
    edits = []
    # una parola che il PDF scrive unita e DeepSeek ha scritto in due ("SPRUNG BEDINGUNG"): si riunisce
    pset = set(P)
    for k in range(len(occ) - 1):
        x, y = D[k], D[k + 1]
        if (occ[k][0] == occ[k + 1][0] and x not in pset and y not in pset and (x + y) in pset and len(x + y) >= 6
                and spans[occ[k][0]][occ[k][2]:occ[k + 1][1]].strip() == ''):
            edits.append((occ[k][0], occ[k][1], occ[k + 1][2], apply_case(occ[k][3], Po[P.index(x + y)]), occ[k][3] + ' ' + occ[k + 1][3]))
    sm = difflib.SequenceMatcher(None, D, P, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != 'replace' or (i2 - i1) > 6 or (j2 - j1) > 6:
            continue
        a_s, b_s = ''.join(D[i1:i2]), ''.join(P[j1:j2])
        # confusione classica di lettura (l / i / 1, o / 0) in una parola breve: "GI." invece di "Gl."
        diff = [(x, y) for x, y in zip(a_s, b_s) if x != y]
        confusable = ((i2 - i1) == (j2 - j1) == 1 and len(a_s) == len(b_s) <= 4 and len(diff) == 1
                      and frozenset(diff[0]) in (frozenset('il'), frozenset('l1'), frozenset('i1'), frozenset('o0')))
        if not confusable and (lev_ratio(a_s, b_s) < 0.6 or (len(a_s) != len(b_s) and (i2 - i1) != (j2 - j1) and abs(len(a_s) - len(b_s)) > 3)):
            continue                                       # troppo diverse, o parole intere di DeepSeek che il PDF non ha: non si tocca
        if (i2 - i1) == (j2 - j1):
            for d, p in zip(range(i1, i2), range(j1, j2)):
                if D[d] != P[p] and (lev_ratio(D[d], P[p]) >= 0.5 or confusable):
                    i, s0, e0, w = occ[d]
                    edits.append((i, s0, e0, apply_case(w, Po[p]), w))
        elif len({occ[d][0] for d in range(i1, i2)}) == 1:   # numero di parole diverso ("ist soll" -> "stellt"), nello stesso testo
            i, s0, _, w0 = occ[i1]
            edits.append((i, s0, occ[i2 - 1][2], apply_case(w0, ' '.join(Po[j1:j2])), ' '.join(occ[d][3] for d in range(i1, i2))))
    out = list(spans)
    for i, s0, e0, new, old in sorted(edits, key=lambda e: (e[0], -e[1])):
        out[i] = out[i][:s0] + new + out[i][e0:]
        log.append(f'parole corrette con il PDF (allineamento): "{old}" -> "{new}"')
        st['parole_corrette_allineamento'] += 1
    return out


def process_text(body: str, ws, rect, imgs, has_bb: bool, st: Counter, opts, skip=frozenset()) -> tuple[str, list[str]]:
    log: list[str] = []
    tokens = word_tokens(ws)

    def key(w: str) -> str:
        return w.lower().replace('ß', 'ss')

    orig_of = {key(t): t.lower() for t in tokens if len(t) >= 4}          # forma originale (con ß) di ogni parola del PDF
    pdf_tok = [key(t) for t in tokens if len(t) >= 4]
    pairs = [(key(a), key(b)) for a, b in hyphen_pairs(ws)]
    for a, b in pairs:
        orig_of.setdefault(a + b, a + b)
    S = set(pdf_tok) | {(a + b) for a, b in pairs}
    # parole del PDF con una lettera di matematica incollata davanti/dietro ("xexistiert"): accettate come varianti
    S_loose = set(S)
    for t in list(S):
        if len(t) >= 5:
            S_loose |= {v for v in (t[1:], t[2:]) if len(v) >= 4}
    # il testo digitale a volte spezza le parole ("A l so"): si ricompongono le serie di frammenti brevi (solo per ACCETTARE)
    run: list[str] = []
    for w in list(ws) + [None]:
        t = unicodedata.normalize('NFKC', w[4]) if w else ''
        if w and WORD.fullmatch(t) and len(t) <= 2:
            run.append(t)
            continue
        if len(run) >= 2:
            S_loose.add(key(''.join(run)))
        run = []
    # flusso continuo di lettere come ultima risorsa (solo parole di almeno 5 lettere)
    stream = key(''.join(WORD.findall(' '.join(unicodedata.normalize('NFKC', w[4]) for w in ws))))

    def accepted(w: str) -> bool:
        k = key(w)
        return k in S_loose or (len(k) >= 5 and k in stream)

    spans = MATH_SPAN.split(body)
    if opts.correggi_parole:
        spans = align_prose(spans, ws, key, log, st)
    ds_tok = []
    for i, seg in enumerate(spans):
        if i % 2 == 0:
            ds_tok += [key(t) for t in WORD.findall(seg) if len(t) >= 4]
    ds_set = set(ds_tok)
    ds_short = ds_set | {key(t) for i, seg in enumerate(spans) if i % 2 == 0 for t in WORD.findall(seg) if len(t) == 3}
    # parole di DeepSeek assenti dal PDF -> abbinate alle parole del PDF che DeepSeek non ha usato
    leftover = Counter(pdf_tok) - Counter(ds_tok)
    for t in list(leftover):                              # parola del PDF coperta da una di DeepSeek (con lettera incollata)
        if len(t) >= 5 and {v for v in (t[1:], t[2:]) if len(v) >= 3} & ds_short:
            leftover[t] = 0
        elif len(t) >= 4 and any(d != t and (d.startswith(t) or d.endswith(t)) for d in ds_set):
            leftover[t] = 0                               # frammento di una parola che DeepSeek ha scritto intera ("Behaup" + "tung")
    for x, y in zip(ds_tok, ds_tok[1:]):                  # parola del PDF che DeepSeek ha scritto in due ("SPRUNG BEDINGUNG")
        if leftover.get(x + y):
            leftover[x + y] = 0
    for a, b in pairs:                                    # sillabazione a fine riga: i due pezzi non sono "mancanti"
        if (a + b) in ds_set or (a in ds_set and b in ds_set):
            for piece in (a, b):
                if leftover.get(piece):
                    leftover[piece] -= 1
    st['parole_ds_non_nel_pdf'] += sum(1 for t in ds_tok if not accepted(t))
    corrections = []

    def fix_word(m):
        w = m.group(0)
        if len(w) < 4 or accepted(w):
            return w
        k = key(w)
        cands = [c for c, n in leftover.items() if n > 0 and abs(len(c) - len(k)) <= 3]
        best = max(cands, key=lambda c: lev_ratio(k, c), default=None)
        if best and lev_ratio(k, best) >= 0.72 and opts.correggi_parole:
            leftover[best] -= 1
            new = apply_case(w, orig_of.get(best, best))
            corrections.append((w, new))
            return new
        log.append(f'parola non trovata nel PDF: "{w}"')
        st['parole_non_risolte'] += 1
        return w

    out_parts = []
    flat_syms = []
    inline_info = []
    for i, seg in enumerate(spans):
        if i % 2 == 0:
            new = WORD.sub(fix_word, seg)
            out_parts.append(new)
            flat_syms.append(re.sub(r'\*\*', '', re.sub(r'(?m)^\s*[*•]\s', '', new)))   # niente simboli dell'elenco/grassetto Markdown
        else:
            inner = re.sub(r'^\\\(|\\\)$|^\\\[|\\\]$', '', seg).strip()
            fixed, reps = fix_latex(inner, tokens, has_bb)
            for r in reps:
                log.append(f'formula in linea riparata: {r}')
            st['formule_inline'] += 1
            syms, unk = latex_symbols(fixed)
            probs = latex_problems(fixed, unk)
            if probs:
                log.append(f'formula in linea con LaTeX sospetto ({"; ".join(probs)}): {fixed[:80]}')
                st['inline_latex_sospetto'] += 1
            flat_syms.append(syms)
            inline_info.append((fixed, alpha_counter(syms, case=False, minus=False)))
            out_parts.append('\\(' + fixed + '\\)')
    for w, n in corrections:
        log.append(f'parola corretta con il PDF: "{w}" -> "{n}"')
        st['parole_corrette'] += 1
    # parole del PDF che DeepSeek non ha scritto (omissioni)
    miss = [c for c, n in leftover.items() if n > 0 and len(c) >= 5 and c not in {key(x) for _, x in corrections}]
    if miss:
        st['parole_pdf_mancanti'] += len(miss)
        log.append('parole del PDF assenti nella trascrizione: ' + ', '.join(sorted(miss)))
    # confronto complessivo dei simboli (maiuscole/minuscole e segni meno ignorati: nel testo c'e' il maiuscoletto e la sillabazione)
    pdf_text = ' '.join(w[4] for w in ws).replace('•', '')              # i punti elenco del PDF non sono matematica
    a = without(alpha_counter(pdf_text, case=False, minus=False), {c.lower() for c in skip})
    b = without(alpha_counter(''.join(flat_syms), case=False, minus=False), {c.lower() for c in skip})
    wild = tiny_images(imgs, rect)
    missing, extra = a - b, b - a
    if missing or sum(extra.values()) > wild:
        st['blocchi_con_differenze'] += 1
        msg = []
        if missing:
            msg.append(f'nel PDF e non nella trascrizione: {fmt_counter(missing)}')
        if sum(extra.values()) > wild:
            msg.append(f'nella trascrizione e non nel PDF: {fmt_counter(extra)}')
            for fx, c in inline_info:
                if any(extra.get(k) for k in c):
                    st['formule_inline_sospette'] += 1
                    msg.append(f'formula sospetta: ${fx[:70]}$')
        log.append('DIFFERENZE rispetto al testo digitale -> ' + ' | '.join(msg))
        text = md_math(''.join(out_parts))
        # avviso leggibile dai programmi successivi (invisibile nel Markdown reso)
        return text + '\n<!-- DA VERIFICARE CON L\'ORIGINALE: ' + ' | '.join(msg).replace('-->', '') + ' -->', log
    return md_math(''.join(out_parts)), log


# ----------------------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description='Ibrido, fase 2: Markdown verificato contro il PDF')
    ap.add_argument('pagine', nargs='*', metavar='FILE.pdf:PAGINE', help='solo queste pagine (come nella fase 1); se omesso: tutta la cartella di lavoro')
    ap.add_argument('--cartella', type=Path, default=HERE / 'lavoro')
    ap.add_argument('--uscita', type=Path)
    ap.add_argument('--senza-correzione-parole', dest='correggi_parole', action='store_false')
    args = ap.parse_args()

    metas = sorted(args.cartella.glob('*_p[0-9][0-9][0-9][0-9].json'))          # solo i file di pagina (c'e' anche cache_qwen.json)
    if not metas:
        print(f'Nessuna pagina in {args.cartella}: lancia prima la fase 1.', file=sys.stderr)
        return 2
    out = args.uscita or HERE / 'uscita' / datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    report, summary = [], {}
    total = Counter()
    # 1) calibrazione per documento: simboli che il LaTeX usa piu' volte ma che il testo digitale di QUEL PDF non contiene mai
    #    (es. una Δ senza codifica). Non sono verificabili in quel libro: si escludono dal confronto, tutto il resto resta rigoroso.
    wanted = None
    if args.pagine:
        wanted = set()
        for spec in args.pagine:
            name, _, pages = spec.rpartition(':')
            for part in pages.split(','):
                a, _, b = part.partition('-')
                wanted |= {(Path(name).stem, n) for n in range(int(a), int(b or a) + 1)}
    loaded = []
    for mf in metas:
        meta = json.loads(mf.read_text(encoding='utf-8'))
        if wanted is not None and (Path(meta['pdf']).stem, int(meta['pagina'])) not in wanted:
            continue
        if mf.with_suffix('.raw.txt').is_file():
            loaded.append((mf, meta))
    if not loaded:
        print('Nessuna delle pagine richieste e\' nella cartella di lavoro: lancia prima la fase 1.', file=sys.stderr)
        return 2
    skip_of: dict[str, set] = {}
    for pdf_s in sorted({m['pdf'] for _, m in loaded}):
        coll = dict(pdf=Counter(), ltx=Counter(), eqs=Counter())
        for mf, meta in loaded:
            if meta['pdf'] == pdf_s:
                process_page(Path(pdf_s).stem, int(meta['pagina']), Path(pdf_s), mf.with_suffix('.raw.txt').read_text(encoding='utf-8'),
                             out, args, dry=True, coll=coll)
        skip_of[pdf_s] = {c for c in coll['ltx'] if coll['pdf'][c] == 0 and coll['ltx'][c] >= 3 and coll['eqs'][c] >= 2}
        if skip_of[pdf_s]:
            report.append(f'### {Path(pdf_s).name}: simboli NON verificabili in questo PDF (assenti dal suo testo digitale): '
                          + ' '.join(sorted(skip_of[pdf_s])) + '\n')
    for mf, meta in loaded:
        raw_f = mf.with_suffix('.raw.txt')
        pdf = Path(meta['pdf'])
        stem = pdf.stem
        raw = raw_f.read_text(encoding='utf-8')
        md, st, log = process_page(stem, int(meta['pagina']), pdf, raw, out, args, skip=frozenset(skip_of[meta['pdf']]))
        (out / f'{stem}_p{int(meta["pagina"]):04d}.md').write_text('\n\n'.join(md) + '\n', encoding='utf-8')
        head = f'=== {pdf.name} pagina {meta["pagina"]}' + ('  [USCITA TRONCATA: pagina incompleta]' if meta.get('troncato') else '')
        report += [head] + log + ['']
        summary[f'{stem}_p{meta["pagina"]}'] = st
        total.update(st)
    summary['TOTALE'] = dict(total)
    (out / 'RAPPORTO.txt').write_text('\n'.join(report), encoding='utf-8')
    (out / 'rapporto.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')
    print('\n'.join(report))
    print('--- TOTALE ---')
    for k, v in sorted(total.items()):
        print(f'  {k}: {v}')
    print(f'\nUscita in: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
