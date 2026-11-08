# Percorso di studio del programma

## Risultato del confronto
Con tutte le aste 30x50 cm (E=30 GPa, A=.15 m², I=.003125 m⁴)
il caso q=10 kN/m riproduce i numeri visibili nello screenshot:
M minimo trave superiore -7.571878 kN m, massimo +4.862550 kN m,
N pilastro inferiore sinistro -29.005992 kN.
La conferma testuale "pilastri 30x30" non coincide con la tabella dello
screenshot, che mostra pilastri E5/E6 30x50. La prova con TUTTE le aste
30x50 riproduce anche i valori dei pilastri inferiori dello screenshot.
L'esempio originale conserva invece le sezioni precedenti.
La convergenza non era la causa: passando da tolleranza 1e-12 a 1e-14,
le iterazioni finali passano da 17 a 20 e i momenti cambiano al massimo
di 2.312e-12 kN m (prova sul modello originario tutto 30x30).

## Ordine consigliato
1. confronto_sezioni_30x50.m
   Leggi i dati, le unità e la chiamata al solutore. Non serve capire subito
   l'esportazione CSV o i controlli assert. Questo è il caso che riproduce
   lo screenshot; tutte le sezioni sono 30x50.
2. cross_telai_multipiano.m, blocchi 1 e 2
   Parametri, nodi, aste e numerazione dei tre gradi di libertà per nodo.
3. cross_telai_multipiano.m, funzione finale cross_rotazioni
   Il nucleo di Cross a traslazioni assegnate: squilibrio del nodo,
   incremento della rotazione e controllo del residuo.
4. cross_telai_multipiano.m, rigidezza_asta e blocchi 3-5
   Rigidezza locale, cambio di coordinate e assemblaggio.
   Studia poi la condensazione delle traslazioni: richiede matrici a
   blocchi e sistemi lineari. È un metodo ibrido, non una tabella di Cross
   manuale che risolve da sola tutte le traslazioni.
5. cross_telai_multipiano.m, blocchi 6-7; interroga_asta.m
   Recupero delle azioni, equilibrio delle sezioni, M/V/N e inviluppo
   (quest'ultimo è disattivato per impostazione predefinita).
6. diagrammi_sul_telaio.m
   Rendering e interazione. Studialo solo quando conosci i valori da disegnare.
7. aggiorna_query_telaio.m
   Pannello di lettura e indicatore della sezione. Non risolve la struttura.

esempio_due_piani_distribuito.m è l'esempio originale a due piani con
carichi distribuiti e sezioni tutte 30x30. esempio_due_piani.m è quello
separato con forze concentrate: non confondere i due.
visualizza_distribuito_sul_telaio.m è solo un comando rapido per aprire
i grafici dell'esempio originale distribuito.

## Query nelle figure
Per il modello che riproduce lo screenshot:
```octave
cd('/Users/carlosilletti/Desktop/Telaio_Cross_Studio')
R = confronto_sezioni_30x50();
```
Clicca su una linea o area del diagramma: il pannello mostra asta, x, M,V,N.
Oppure inserisci asta e x e premi "Leggi M, V, N".
Disattiva gli strumenti zoom/pan durante le query con il clic.
Ai nodi, dove si incontrano più aste, usa il numero asta nel pannello.

Puoi interrogare anche dal terminale:
```octave
S = interroga_asta(R,9,1.5)
```
Le query usano le formule di equilibrio e non una semplice interpolazione
lineare dei punti disegnati. Per una forza concentrata si possono
distinguere i valori di taglio a sinistra e a destra.

## Verso del momento
Il momento è ora rappresentato sul lato delle fibre tese:
sulle travi orientate da sinistra a destra, M positivo sotto e M negativo sopra.
I valori numerici NON sono stati cambiati. V e N conservano la convenzione
grafica originale. I colori indicano i segni: blu positivo, rosso negativo.
Le immagini PNG sono statiche: le query funzionano nelle finestre Octave.

## MATLAB
Le funzioni diagrammi_sul_telaio, interroga_asta e aggiorna_query_telaio
usano sintassi predisposta anche per MATLAB, ma sono state eseguite e
verificate soltanto in Octave Qt. Il resto del progetto è scritto per Octave
e contiene ancora funzioni come rows/columns: non è dichiarato collaudato
integralmente in MATLAB.
Per provare solo i grafici in MATLAB, carica il MAT prodotto da Octave:
```matlab
load('Confronto_tutte_30x50/risultati.mat','R');
diagrammi_sul_telaio(R,1);
```
Documentazione ufficiale sulle callback:
https://www.mathworks.com/help/matlab/creating_plots/create-callbacks-for-graphics-objects.html

## Primo esercizio
Scrivi a mano:
b=.30; h=.50; A=b*h; I=b*h^3/12;
Poi scambia b e h. L'area resta uguale ma l'inerzia cambia.
Questo spiega perché la ripartizione dei momenti dipende anche
dall'orientamento della sezione, non solo dalla sua area.

Secondo esercizio: su una trave con q uniforme e nessuna forza puntuale,
controlla che V(x)=V(0)-q*x e M(x)=M(0)+V(0)*x-q*x^2/2.
