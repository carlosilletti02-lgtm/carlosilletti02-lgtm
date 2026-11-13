# Parti piu' fragili del motore V6 e come renderle robuste

Stato: 12 novembre 2026, motore 6.7. Ogni riga nasce da difetti VISTI su libri reali (non ipotetici).
Priorita': A = poca fatica e rischio basso, B = media, C = lavoro grosso (nuova architettura).

| # | Parte fragile | Perche' (evidenza) | Soluzione possibile | Prior. |
|---|---|---|---|---|
| 1 | **Riconoscere cosa e' formula, parola per parola** (`word_is_math` + liste per lingua) | Ogni libro codifica le formule in modo diverso: simboli in blocchi separati, simboli come immagini (R doppio), parole incollate alla formula («Omega-existiert»), formule solo in ASCII (`a+b`), parole scambiate per variabili (Zahl, Form) | Regole piu' marcate e verificabili: gia' fatto per i casi visti; passo successivo = decidere per REGIONE della riga (cosa e' fra due parole di testo = formula) e non per parola | B |
| 2 | **Ricostruire le righe** dai blocchi di PyMuPDF (`lines_of`, `merge_split_lines`, `merge_inline_blocks`) | Soglie numeriche (0.5 corpo, 0.4 sovrapposizione, 25 pt, 15 pt): una regola troppo larga fonde due righe (successo a p.37 economia) | Tutte le soglie in costanti con nome + un test per ogni caso gia' visto; alternativa: rifare le righe dai singoli CARATTERI (rawdict) | B |
| 3 | **Ordine di lettura** (ordino per posizione verticale se colonna singola) | Euristica a 2 colonne (4+4 elementi); tabelle e note a margine possono confonderla | Rilevare le colonne davvero (istogramma delle x) e tenere l'ordine del PDF quando e' gia' coerente | B |
| 4 | **Raggruppare le equazioni** (`group_equation_blocks`, `absorb_fragments`, soglie 19 pt / 48% pagina) | Frammenti di una stessa formula in blocchi lontani nel flusso; righe con una parola dentro («A und B») spezzate | Raggruppare per GEOMETRIA (vicinanza e sovrapposizione), non per adiacenza nell'elenco; tenere insieme le righe con parole connettive se la riga e' per lo piu' formula | A/B |
| 5 | **Ritaglio delle immagini** (margini fissi) | Parentesi grandi tagliate (Gamma(w), p.26 PDE); margini piu' larghi fanno entrare pezzi della riga sopra (provato e annullato) | Misurare l'ingombro REALE dei glifi (rawdict / inchiostro a 4x) e stringere/allargare per ogni formula; escludere il testo vicino con una maschera | B |
| 6 | **Impaginazione** (righe a mano, niente tabelle, niente divisione in sillabe) | Una formula non deve restare tagliata o staccata da quella contigua | Regole gia' in `GAP_*` (formule contigue insieme, spazi fissi); da aggiungere: «tieni la formula con la riga che la introduce» e tabelle come immagine unica | A |
| 7 | **Figure e tabelle** (`find_figures`: >= 8 tratti, >= 100x50 pt) | Figure con poche linee non rilevate; le tabelle restano a pezzi; le scritte nelle figure restano in tedesco | Tabelle come immagine unica (+ didascalia tradotta); figure con soglia adattiva; traduzione delle etichette sovrapposta (lavoro grosso) | B/C |
| 8 | **Traduzione**: validazione e prompt | Qwen puo' inventare testo («blabla»); i titoli della bibliografia vengono tradotti; qualche termine tecnico incoerente (entkoppelt) | Controllo di ripetizioni senza senso; saltare la bibliografia ('Literatur'); glossario piu' ricco per materia | A |
| 9 | **Numerazione blocchi/parole di PyMuPDF incoerente** (`realign_words`) | In molti PDF i numeri non coincidono: testo mescolato | Gia' corretto; aggiungere un avviso quando le parole riassegnate superano una soglia | A |
| 10 | **Nessuna misura della correttezza VISIVA delle formule** | `regressione.py` misura testo e ordine, non se una formula e' tagliata o ha perso un simbolo | Pagine «oro» con confronto d'immagine (originale contro ritaglio) e conteggio dei ritagli con testo vicino per pagina | B |

## Regole di impaginazione (un solo posto: inizio di `traduci_pdf_matematica_offline_v6.py`)

- `GAP_DISPLAY = 8` pt sopra e sotto ogni formula display: il testo non la tocca mai (riga per riga con baseline reale).
- `GAP_KEEP = 24` pt: equazioni piu' vicine di cosi' nell'originale restano insieme sulla stessa pagina (se ci stanno).
- `PAD_DISPLAY_X/Y = 3.5 / 2.0` pt: margini dei ritagli. Non alzarli (vedi riga 5).
- Una formula display non viene mai divisa tra due pagine: se non ci sta intera passa alla pagina dopo (scalata se piu' grande della pagina).
- Figure: immagine unica, scala 4x, didascalia tradotta sotto.

## Come provare un cambiamento in modo sicuro

1. `"$PY" strumenti_test/regressione.py` prima e dopo: deve dire «Peggioramenti: 0».
2. Guardare a occhio 3-5 pagine con formule (originale a sinistra, traduzione a destra).
3. Annotare la modifica in `CAMBIAMENTI.md` (versione, difetto visto, verifica).
