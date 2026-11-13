#!/usr/bin/env python3
"""FASE 3 dell'ibrido: Qwen traduce in italiano il Markdown VERIFICATO prodotto dalla fase 2.

Gira in un processo SEPARATO (DeepSeek non e' in memoria: la fase 1 e' gia' finita). Offline.
Riusa dal motore V6, SENZA modificarlo: Translator (segnaposto <F1>/<E1>, scala di recupero, cache, glossario) e validate()
(tag, numeri, parole non tradotte). Il motore V6 e' importato come modulo e non viene mai eseguito.

Cosa traduce
  - paragrafi, titoli ("## ..."), elementi di elenco: Qwen, con le formule in linea ($...$) sostituite da segnaposto.
  - una frase interrotta da un'equazione ("... lässt als $$..$$ für jedes ...") e' tradotta come UNA unita' (come V6).
  - le PAROLE dentro le formule (\\text{für alle}, \\mathrm{bzw.}): tradotte una per una; il resto della formula non si tocca.
Cosa NON tocca
  - formule (LaTeX), ritagli di formule e figure, commenti "DA VERIFICARE". Dopo la traduzione un controllo automatico verifica che
    tutte le formule siano identiche a quelle in ingresso (ignorando solo le parole dentro \\text{}/\\mathrm{}).

Uso:
  PY="$HOME/Library/Application Support/CartaOCR/runtime/bin/python3"
  sandbox-exec -p '(version 1)(allow default)(deny network*)' "$PY" -B fase3_traduci.py uscita/<cartella> [--lingua deu]
Scrive nella stessa cartella: <nome>_p<NNNN>_it.md (una pagina), <nome>_italiano.md (tutte le pagine), RAPPORTO_TRADUZIONE.txt
"""
import os
for _k, _v in (('HF_HUB_OFFLINE', '1'), ('TRANSFORMERS_OFFLINE', '1'), ('HF_DATASETS_OFFLINE', '1'), ('HF_HUB_DISABLE_TELEMETRY', '1')):
    os.environ[_k] = _v

import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / 'traduci_pdf_matematica_offline_v6.py'

EQ = r'\$\$\n.*?\n\$\$'
IMG = r'!\[[^\]]*\]\([^)]*\)(?:\n\n<!-- LaTeX scartato:.*?-->)?'
BLOCKS = re.compile(f'({EQ})|({IMG})', re.S)
WARN = re.compile(r'\n?(<!-- DA VERIFICARE.*?-->)\s*$', re.S)
INLINE = re.compile(r'\$([^$\n]+?)\$')
WORDY = re.compile(r'\\(text|mathrm)\{([^{}]*)\}')
LIST_ITEM = re.compile(r'^(\s*(?:[*•\-]|\d+[.)])\s+)(.*)$')
HEADING = re.compile(r'^(#+\s+)(.*)$')


def load_engine():
    spec = importlib.util.spec_from_file_location('v6engine', ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    patch_validate(mod)
    return mod


def patch_validate(v6) -> None:
    """Correzione IN MEMORIA (il file di V6 non cambia) di un falso allarme del controllo dei numeri di V6.

    V6 ignora i numeri ordinali ("1. Ordnung" -> "primo ordine") togliendo "\\d{1,2}\\.\\s". Ma cosi' toglie anche la coda di un
    numero a punti a fine frase ("... teorema 4.24. Per questo ...": "24." sembra un ordinale) e boccia una traduzione corretta
    con "numeri modificati". Qui l'esclusione non tocca i numeri preceduti da un punto o da una cifra."""
    def validate(src, out):
        if not out.strip():
            return 'traduzione vuota', []
        if v6.BAD_TRANSLATION.search(out):
            return 'caratteri corrotti', []
        s_tags, o_tags = v6.TAG_RE.findall(src), v6.TAG_RE.findall(out)
        if sorted(s_tags) != sorted(o_tags):
            return 'tag modificati o mancanti', []
        if [t for t in s_tags if t[0] == 'E'] != [t for t in o_tags if t[0] == 'E']:
            return 'ordine delle equazioni modificato', []

        def digits(t):
            return sorted(re.findall(r'\d+', re.sub(r'(?<![\d.])\b\d{1,2}\.(?=\s)', ' ', v6.TAG_RE.sub(' ', t))))
        if digits(src) != digits(out):
            return 'numeri modificati', []
        words = re.findall(r'[^\W\d_]+', v6.TAG_RE.sub(' ', out).lower())
        left = [w for w in words if w in v6.RESIDUO]
        if len(left) >= 2 or (len(left) == 1 and len(words) <= 6):
            return 'parole non tradotte: ' + ', '.join(sorted(set(left))[:5]), []
        if len(src) >= 40 and out.strip() == src.strip():
            return 'nessuna traduzione', []
        soft = []
        if [t for t in s_tags if t[0] == 'F'] != [t for t in o_tags if t[0] == 'F']:
            soft.append('ordine delle formule cambiato (ammesso)')
        ratio = len(v6.TAG_RE.sub('', out)) / max(1, len(v6.TAG_RE.sub('', src)))
        if len(src) >= 60 and not (0.45 <= ratio <= 2.2):
            soft.append(f'lunghezza anomala (rapporto {ratio:.2f})')
        return None, soft
    v6.validate = validate


def parse_page(md: str) -> list[tuple[str, str]]:
    """Pagina Markdown -> blocchi (tipo, testo): 'eq' ($$..$$), 'img' (figura/ritaglio), 'text' (tutto il resto)."""
    blocks, pos = [], 0

    def add_text(s: str) -> None:
        for chunk in re.split(r'\n\s*\n', s):
            if chunk.strip():
                blocks.append(('text', chunk.strip('\n')))

    for m in BLOCKS.finditer(md):
        add_text(md[pos:m.start()])
        blocks.append(('eq' if m.group(1) else 'img', m.group(0)))
        pos = m.end()
    add_text(md[pos:])
    return blocks


def fingerprint(md: str) -> list[str]:
    """Le formule di una pagina, con il contenuto di \\text{}/\\mathrm{} annullato: in ingresso e in uscita devono coincidere."""
    forms = [m.group(1) for m in re.finditer(r'\$\$\n(.*?)\n\$\$', md, re.S)]
    rest = re.sub(r'\$\$\n.*?\n\$\$', ' ', md, flags=re.S)
    rest = re.sub(r'<!--.*?-->', ' ', rest, flags=re.S)
    forms += [m.group(1) for m in INLINE.finditer(rest)]
    out = []
    for f in forms:
        f = WORDY.sub('\\\\W{}', f)                       # \text{..} e \mathrm{..}: si confronta solo che ci sia una parola
        out.append(re.sub(r'\\;|\s+', '', f))
    return sorted(out)


class Pipeline:
    def __init__(self, v6, translator, lexicon: set[str], formula_dict: dict[str, str] | None = None):
        self.v6, self.tr, self.lex = v6, translator, lexicon
        self.fdict = {k.lower(): v for k, v in (formula_dict or {}).items()}
        self.stats = Counter()
        self.problems: list[str] = []

    # -- titoli all'inizio di un blocco ("Definition 2.18" resta spesso com'e': Qwen la scambia per una parola gia' italiana)
    def fix_title(self, line: str) -> str:
        refs = self.v6.CFG.get('riferimenti', {})
        titles = set(self.v6.CFG.get('titoli', []))
        gl = self.v6.CFG.get('glossario', {})
        m = re.match(r'^((?:#+\s+)?(?:[*•\-]\s+)?(?:■\s*)?)([^\W\d_][\w.ﬁ]*)(\b.*)$', line, re.S)
        if not m:
            return line
        word = m.group(2)
        new = refs.get(word) if word in titles or word in refs else None
        if not new and word in titles and word in gl:
            new = gl[word][:1].upper() + gl[word][1:]
        if new and new != word:
            self.stats['titoli_corretti'] += 1
            return m.group(1) + new + m.group(3)
        return line

    # -- parole dentro le formule
    def phrase(self, text: str) -> str | None:
        norm = re.sub(r'\s+', ' ', text.strip()).lower()
        if norm in self.fdict:
            self.stats['frasi_formula_dizionario'] += 1
            return self.fdict[norm]
        key = self.tr._key('FRASE|' + text)
        hit = self.tr.cache.get(key)
        if hit and 'it' in hit:
            self.stats['frasi_formula_cache'] += 1
            return hit['it']
        if self.tr.fake:
            return text
        out = self.v6.clean(self.tr._llm(self.tr._msgs_fragment(text), len(text))).strip().strip('«»"')
        if not text.endswith('.'):
            out = out.rstrip('.')
        ok = bool(out) and '\n' not in out and len(out) <= max(14, 3 * len(text)) and not re.search(r'[$\\{}<>]', out)
        if not ok:
            return None
        self.tr.cache[key] = {'it': out, 'livello': 0, 'avvisi': []}
        self.v6.write_json(self.tr.cache_path, self.tr.cache)
        self.stats['frasi_formula_qwen'] += 1
        return out

    def formula_words(self, tex: str) -> str:
        def sub(m):
            cmd, inner = m.group(1), m.group(2)
            words = re.findall(r'[^\W\d_]+', inner)
            if not words or not any(w.lower() in self.lex for w in words):
                return m.group(0)
            new = self.phrase(inner.strip())
            if new is None:
                self.stats['frasi_formula_non_tradotte'] += 1
                self.problems.append(f'parola in formula non tradotta: "{inner.strip()}"')
                return m.group(0)
            if cmd == 'mathrm' and len(re.findall(r'[^\W\d_]', new)) >= 3:
                return f'\\;\\text{{{new}}}\\;'            # parola in tondo senza spazi attorno ("\\mathrm{bzw.}"): la si stacca
            lead = ' ' if inner.startswith(' ') else ''
            trail = ' ' if inner.endswith(' ') else ''
            return f'\\{cmd}{{{lead}{new}{trail}}}'
        return WORDY.sub(sub, tex)

    # -- testo
    def tag(self, s: str, forms: list[str]) -> str:
        def sub(m):
            forms.append(m.group(1).strip())
            return f'<F{len(forms)}>'
        return INLINE.sub(sub, s)

    def untag(self, s: str, forms: list[str]) -> str:
        s = re.sub(r'(<F\d+>)\s+([.,;:!?])(?=\s|$)', r'\1\2', s)

        def sub(m):
            n = int(m.group(1))
            return '$' + self.formula_words(forms[n - 1]) + '$' if 1 <= n <= len(forms) else m.group(0)
        return re.sub(r'<F(\d+)>', sub, s)

    def translate_line(self, line: str) -> str:
        m = HEADING.match(line)
        prefix, body = (m.group(1), m.group(2)) if m else ('', line)
        if not m:
            m2 = LIST_ITEM.match(line)
            if m2:
                prefix, body = m2.group(1), m2.group(2)
        forms: list[str] = []
        unit = self.tag(body, forms)
        out, level, problems, warns = self.unit(unit)
        self.stats[f'livello_{level}'] += 1
        for p in problems:
            self.problems.append(f'{p["motivo"]} :: {p["testo"]}')
        return self.fix_title(prefix + self.untag(out, forms))

    def unit(self, unit: str):
        """translate_unit di V6; se l'unita' fallisce intera si riprova frase per frase: meglio mezza traduzione che nessuna."""
        out, level, problems, warns = self.tr.translate_unit(unit)
        if level < 5:
            return out, level, problems, warns
        sents = self.v6.split_sentences(unit)
        if len(sents) < 2:
            return out, level, problems, warns
        self.stats['unita_riprovate_per_frasi'] += 1
        parts, lv, probs, wr = [], 0, [], []
        for s in sents:
            o, l, p, w = self.tr.translate_unit(s)
            parts.append(o)
            lv, probs, wr = max(lv, l), probs + p, wr + w
        return ' '.join(parts), lv, probs, wr

    def plain(self, text: str) -> bool:
        return ('\n' not in text and not text.startswith(('#', '<', '![', '|')) and not LIST_ITEM.match(text))

    def translate_text_block(self, text: str) -> str:
        warn = WARN.search(text)
        if warn:
            text = text[:warn.start()]
        if text.lstrip().startswith('<'):                       # tabelle HTML ecc.: non tradotte
            self.stats['blocchi_non_tradotti'] += 1
            self.problems.append(f'blocco non tradotto (HTML/tabella): {text[:60]!r}')
            out = text
        else:
            out = '\n'.join(self.translate_line(ln) if ln.strip() else ln for ln in text.split('\n'))
        return out + (f'\n{warn.group(1)}' if warn else '')

    def merged(self, parts: list[str], eqs: list[str]) -> list[str]:
        """paragrafo + equazione + paragrafo che continua la frase -> una sola unita'; restituisce i blocchi in uscita."""
        warns = []
        tagged, forms = [], []
        for p in parts:
            w = WARN.search(p)
            warns.append(w.group(1) if w else '')
            tagged.append(self.tag(p[:w.start()] if w else p, forms))
        unit = tagged[0]
        for k in range(1, len(tagged)):
            unit += f' <E{k}> ' + tagged[k]
        out, level, problems, warns_ = self.unit(unit)
        self.stats[f'livello_{level}'] += 1
        self.stats['frasi_unite_attraverso_equazioni'] += len(eqs)
        for p in problems:
            self.problems.append(f'{p["motivo"]} :: {p["testo"]}')
        blocks = []
        pieces = re.split(r'(<E\d+>)', out)
        k = 0
        for piece in pieces:
            m = re.fullmatch(r'<E(\d+)>', piece)
            if m:
                n = int(m.group(1))
                blocks.append(self.equation(eqs[n - 1]) if 1 <= n <= len(eqs) else piece)
            elif piece.strip():
                blocks.append(self.untag(piece.strip(), forms) + (f'\n{warns[min(k, len(warns) - 1)]}' if warns[min(k, len(warns) - 1)] else ''))
                k += 1
        return blocks

    def equation(self, block: str) -> str:
        m = re.fullmatch(r'\$\$\n(.*?)\n\$\$', block, re.S)
        if not m:
            return block
        return '$$\n' + self.formula_words(m.group(1)) + '\n$$'

    def page(self, md: str) -> str:
        blocks = parse_page(md)
        out, i = [], 0
        while i < len(blocks):
            kind, text = blocks[i]
            if kind == 'text' and self.plain(text):
                parts, eqs = [text], []
                while (i + 2 < len(blocks) and blocks[i + 1][0] == 'eq' and blocks[i + 2][0] == 'text'
                       and self.plain(blocks[i + 2][1]) and self._mergeable(parts[-1], blocks[i + 2][1])):
                    eqs.append(blocks[i + 1][1])
                    parts.append(blocks[i + 2][1])
                    i += 2
                if eqs:
                    out += self.merged(parts, eqs)
                else:
                    out.append(self.translate_text_block(text))
            elif kind == 'text':
                out.append(self.translate_text_block(text))
            elif kind == 'eq':
                out.append(self.equation(text))
            else:
                out.append(text)
            i += 1
        return '\n\n'.join(out) + '\n'

    def _mergeable(self, a: str, b: str) -> bool:
        a, b = WARN.sub('', a), WARN.sub('', b)
        ta, tb = self.tag(a, []), self.tag(b, [])
        return self.v6.mergeable({'text': ta}, {'text': tb})


def main() -> int:
    ap = argparse.ArgumentParser(description='Ibrido, fase 3: Qwen traduce il Markdown verificato')
    ap.add_argument('cartella', type=Path, help='cartella di uscita della fase 2 (con i .md delle pagine)')
    ap.add_argument('--lingua', default='deu')
    ap.add_argument('--modello', type=Path)
    ap.add_argument('--cache', type=Path, default=HERE / 'lavoro' / 'cache_qwen.json')
    ap.add_argument('--fake', action='store_true', help='senza modello: prova di lettura/riscrittura (il testo resta com\'e\')')
    ap.add_argument('--riprova-falliti', action='store_true')
    args = ap.parse_args()

    run = args.cartella
    pages = sorted(p for p in run.glob('*_p[0-9][0-9][0-9][0-9].md'))
    if not pages:
        print(f'Nessuna pagina .md in {run}: lancia prima la fase 2.', file=sys.stderr)
        return 2
    config = HERE.parent / f'lingua_{args.lingua}.json'
    if not config.is_file():
        print(f'Manca {config.name}', file=sys.stderr)
        return 2
    v6 = load_engine()
    v6.configure(config)
    model = (args.modello or v6.DEFAULT_MODEL).expanduser()
    if not args.fake and not (model / 'config.json').is_file():
        print(f'Modello non trovato: {model}', file=sys.stderr)
        return 2
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tr = v6.Translator(model, v6.load_glossary(), args.cache, fake=args.fake, retry_failed=args.riprova_falliti)
    if not args.fake:
        print(f'Qwen caricato in {time.time() - t0:.1f} s', flush=True)
    lexicon = {w for w in (v6.RESIDUO | v6.VETO) if len(w) >= 2}
    extra = HERE / f'lingua_ibrido_{args.lingua}.json'
    fdict = json.loads(extra.read_text(encoding='utf-8')).get('parole_in_formula', {}) if extra.is_file() else {}
    lexicon |= {w for k in fdict for w in re.findall(r'[^\W\d_]+', k.lower()) if len(w) >= 2}
    pipe = Pipeline(v6, tr, lexicon, fdict)

    report, combined, changed = [], {}, 0
    for pg in pages:
        t1 = time.time()
        md = pg.read_text(encoding='utf-8')
        n_before = len(pipe.problems)
        it = pipe.page(md)
        out_f = pg.with_name(pg.stem + '_it.md')
        out_f.write_text(it, encoding='utf-8')
        same = fingerprint(md) == fingerprint(it)
        stem = re.sub(r'_p\d{4}$', '', pg.stem)
        combined.setdefault(stem, []).append((pg.stem[-4:], it))
        new = pipe.problems[n_before:]
        flag = '' if same else '  <-- FORMULE MODIFICATE (non dovrebbe succedere)'
        changed += 0 if same else 1
        report.append(f'=== {pg.stem}: {time.time() - t1:.0f} s, formule identiche: {"si" if same else "NO"}{flag}')
        report += [f'  [DA RIVEDERE] {p}' for p in new]
        print(f'{pg.stem}: {time.time() - t1:.0f} s | formule identiche: {"si" if same else "NO"} | da rivedere: {len(new)}', flush=True)
    for stem, items in combined.items():
        body = '\n\n'.join(f'<!-- pagina PDF {int(n)} -->\n\n{t.strip()}' for n, t in items) + '\n'
        (run / f'{stem}_italiano.md').write_text(body, encoding='utf-8')
    summary = ['', '--- STATISTICHE ---'] + [f'  {k}: {v}' for k, v in sorted((tr.stats + pipe.stats).items())]
    summary.append(f'  pagine con formule modificate: {changed}')
    (run / 'RAPPORTO_TRADUZIONE.txt').write_text('\n'.join(report + summary) + '\n', encoding='utf-8')
    print('\n'.join(summary))
    print(f'\nFASE 3 FINITA in {time.time() - t0:.0f} s. Leggi: {run / "RAPPORTO_TRADUZIONE.txt"}')
    return 0 if changed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
