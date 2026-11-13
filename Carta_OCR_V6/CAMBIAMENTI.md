# Registro dei cambiamenti del motore V6

Ogni risultato (`rapporto.json`) riporta `versione_motore`: sai sempre con quale versione e' stato prodotto.
Prima di accettare una modifica si esegue `strumenti_test/regressione.py` (5 gruppi di pagine, 4 libri).
Le versioni precedenti sono in `backup/`.

| Versione | Cosa cambia | Perche' (difetto visto) | Verifica |
|---|---|---|---|
| 6.0 | Motore V6 iniziale: tag ASCII, validazione, recupero a livelli, impaginazione a righe | difetti di V5 (formule spezzate, tedesco residuo) | libro di matematica pp.194-220 |
| 6.1 | Figure come immagine unica (`--senza-figure` per disattivare) | figure vettoriali smontate | 3 capitoli di simulazione |
| 6.2 | Parole riassegnate per posizione se la numerazione blocchi/parole e' incoerente | testo mescolato in ~4 pagine su 10 | 58 pagine |
| 6.3 | Blocchi-simbolo (-, =>, parentesi, apici) fusi nella riga di testo; '+' e '|' = matematica; guardia corsivo (Zahl, Form...); ordine per y su colonna singola | simboli persi, frammenti in cima | economia pp.32-41; matematica e PDE invariati |
| 6.4 | Frammenti piccoli si attaccano a UNA riga (niente ponti fra righe) | paragrafo mescolato (economia p.37) | matematica e PDE: 0 pagine cambiate |
| 6.5 | Immagini piccole (simboli come l'R doppio) = parte della formula | colonne di righe 'R' isolate (economia pp.167-187) | 4 libri: 0 pagine cambiate |
| 6.6 | Parola incollata a una formula ("Omega-existiert") separata dal resto; margini dei display piu' larghi | parole tedesche dentro le immagini (PDE cap.2 p.25); parentesi grandi tagliate | vedi regressione.py |
| 6.7 | Regole di impaginazione in un solo posto (`GAP_DISPLAY`, `GAP_KEEP`, `PAD_DISPLAY_*`); equazioni contigue (<24 pt) tenute INSIEME sulla stessa pagina; il controllo dei numeri non scarta piu' '1. Ordnung' -> 'primo ordine' | spazi e vincoli sparsi nel codice; intestazione di pagina marcata «da rivedere» | regressione: 0 peggioramenti. Provato e ANNULLATO: margine verticale dei ritagli 4 pt (faceva entrare pezzi della riga sopra, non risolveva la parentesi tagliata) |

Limiti noti aperti: righe di display con una parola dentro ("A und B") spezzate; "R^d" reso come testo in alcuni PDF;
coefficienti binomiali in linea; tabelle; scritte dentro le figure.

## Finestra grafica (12 nov 2026)
- Nuovo `frontend_v6.py` + `Avvia_Frontend.command`: scegli il PDF, pagina iniziale/finale (anche da indice capitoli),
  anteprime delle pagine scelte, lingua, prova veloce, avanzamento, Ferma, apertura dei risultati.
- Il motore NON e' stato toccato (resta 6.7); la finestra chiama `avvia_v6.py`, quindi rete bloccata come prima.
- Provata senza clic umani: caricamento PDF, anteprime, pagine non valide rifiutate, prova veloce completa, Ferma (nessun processo rimasto).

## Nota del 13 nov 2026 (dal prototipo ibrido)
- BUG NOTO, non corretto in V6: `validate()` toglie `\d{1,2}\.(?=\s)` come numero ordinale; cosi' "... teorema 4.24. Per ..." perde una cifra e una traduzione corretta e' bocciata ("numeri modificati"). Correzione di una riga: `(?<![\d.])` davanti al pattern. Il prototipo `prototipo_ibrido/` la applica in memoria.
