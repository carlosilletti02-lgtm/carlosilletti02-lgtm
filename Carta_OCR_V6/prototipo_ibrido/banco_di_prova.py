#!/usr/bin/env python3
"""Banco di prova dell'ibrido: errori NOTI di DeepSeek da solo (trovati leggendo le pagine a occhio) che l'ibrido deve evitare.

Ogni controllo e' una frase vera/falsa sul Markdown prodotto dalla fase 2. Serve a non peggiorare modificando il codice:
se un controllo passa da OK a FALLITO, l'ultima modifica ha fatto un danno.
Gli errori noti sono quelli del 12 novembre 2026 sulle pagine PDE p.25, economia p.34, matematica p.208.

Uso:  "$PY" -B banco_di_prova.py uscita/<cartella>          (cartella prodotta da fase2_assembla.py)
"""
import re
import sys
from pathlib import Path

CHECKS = [
    # (pagina, descrizione, funzione(md, cartella) -> bool)
    ('1783639_p0025', 'parola sbagliata "beratendes" corretta in "berandetes"', lambda t, d: 'berandetes' in t and 'beratendes' not in t),
    ('1783639_p0025', 'parola sbagliata "Nettofuss" corretta in "Nettofluss"', lambda t, d: 'Nettofluss' in t and 'Nettofuss' not in t),
    ('1783639_p0025', 'accento inventato "GREENSCHÉ" tolto', lambda t, d: 'GREENSCHÉ' not in t),
    ('1783639_p0025', 'niente parole lettera-per-lettera nelle formule ("f u r", "u n d", "s o n s t")',
     lambda t, d: not re.search(r'f u r|u n d|s o n s t|f\\mathrm\{u\}r', t)),
    ('1783639_p0025', '"für", "und", "sonst" presenti dentro le formule con l\'accento giusto',
     lambda t, d: '\\text{für' in t and '\\text{und}' in t and '\\text{sonst}' in t),
    ('1783639_p0025', 'insiemi con R maiuscola resi \\mathbb{R} ("I \\subseteq R")', lambda t, d: not re.search(r'\\subseteq R(?![A-Za-z])', t)),
    ('1783639_p0025', 'nessuna correzione sbagliata tipo "ωexistiert"', lambda t, d: 'ωexistiert' not in t and 'ωschreiben' not in t),
    ('1783639_p0025', 'le 6 equazioni sono tutte accettate (nessun ritaglio inutile)', lambda t, d: t.count('$$') == 12),
    ('978-3-658-41641-6_p0208', 'ERRORE SILENZIOSO: f_{p^i_k,p^j_k} (indice l diventato k) NON compare nel Markdown come LaTeX',
     lambda t, d: 'f_{p_{k}^{i},p_{k}^{j}}' not in re.sub(r'<!--.*?-->', '', t, flags=re.S)),
    ('978-3-658-41641-6_p0208', 'la formula sbagliata e\' sostituita dal ritaglio dell\'originale', lambda t, d: '_eq05.png' in t),
    ('978-3-658-41641-6_p0208', 'LaTeX non compilabile \\colonR / \\toR / \\timesR riparato', lambda t, d: not re.search(r'\\(colonR|toR|timesR)', re.sub(r'<!--.*?-->', '', t, flags=re.S))),
    ('978-3-658-41641-6_p0208', 'la grande matrice con indici e\' accettata come LaTeX', lambda t, d: 'pmatrix' in re.sub(r'<!--.*?-->', '', t, flags=re.S)),
    ('978-3-658-41641-6_p0208', 'R maiuscole di insiemi rese \\mathbb{R} (X \\in R^{3})', lambda t, d: not re.search(r'\\in R\^', re.sub(r'<!--.*?-->', '', t, flags=re.S))),
    ('978-3-658-50521-9_p0034', 'le 6 dimostrazioni conservano i segni (4. Fall: -a - b = -|a| + |b|)', lambda t, d: '-a - b = -|a| + |b|' in t),
    ('978-3-658-50521-9_p0034', 'il disegno ad albero (figura 1.6) NON e\' perso: c\'e\' il ritaglio', lambda t, d: 'figure/' in t and '_fig01.png' in t),
    ('978-3-658-50521-9_p0034', 'nessuna parola cambiata per errore ("Also gilt" intatto)', lambda t, d: 'Also gilt' in t),
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    d = Path(sys.argv[1])
    bad = 0
    for stem, desc, fn in CHECKS:
        f = d / f'{stem.rsplit("_p", 1)[0]}_p{stem.rsplit("_p", 1)[1]}.md'
        if not f.is_file():
            print(f'  MANCA   [{stem}] {desc}  (file {f.name} assente)')
            bad += 1
            continue
        ok = bool(fn(f.read_text(encoding='utf-8'), d))
        bad += 0 if ok else 1
        print(f'  {"OK     " if ok else "FALLITO"} [{stem}] {desc}')
    print(f'\nControlli: {len(CHECKS) - bad}/{len(CHECKS)} superati.')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
