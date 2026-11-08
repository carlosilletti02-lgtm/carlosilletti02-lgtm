function figure_create = diagrammi_sul_telaio(R, caso, cartella)
% DIAGRAMMI_SUL_TELAIO Disegna M, V e N accanto alle aste del telaio.
% Uso: diagrammi_sul_telaio(R);
% Oppure: diagrammi_sul_telaio(R,1,'cartella_di_esportazione');
% Non calcola un inviluppo: rappresenta un caso scelto.
%
% x locale: dal nodo iniziale al finale.
% y locale: rotazione di 90 gradi antioraria rispetto a x locale.
% M: disegno sul lato delle fibre tese; positivo sotto le travi.
% V e N: positivi verso +y locale. I segni numerici non cambiano.
% Una scala unica per grandezza permette il confronto fra tutte le aste.
  if nargin < 2, caso = 1; end
  if nargin < 3, cartella = ''; end
  assert(isscalar(caso) && caso == fix(caso) && ...
         caso >= 1 && caso <= size(R.schemi,1), 'Caso inesistente.');
  if ~isempty(cartella) && ~exist(cartella,'dir'), mkdir(cartella); end

  nomi = {'Momento flettente M','Taglio V','Sforzo normale N'};
  unita = {'kN m','kN','kN'};
  file = {'momento_sul_telaio.png','taglio_sul_telaio.png','normale_sul_telaio.png'};
  blu = [0.10 0.32 0.85]; rosso = [0.85 0.16 0.18];
  figura_aste = [0.18 0.20 0.24];
  ne = size(R.aste,1);
  lunghezze = zeros(ne,1);
  for e = 1:ne
    a = R.nodi(R.aste(e,1),:); b = R.nodi(R.aste(e,2),:);
    lunghezze(e) = norm(b-a);
  end
  ampiezza = 0.20*min(lunghezze);
  if exist('OCTAVE_VERSION','builtin')
    figure_create = zeros(1,3);
  else
    figure_create = gobjects(1,3);
  end

  for d = 1:3
    verso = 1;
    if d == 1, verso = -1; end % SOLO il momento viene ribaltato graficamente
    massimo = 0;
    for e = 1:ne
      massimo = max(massimo,max(abs(R.diagrammi{e}(:,d,caso))));
    end
    scala = ampiezza/max(massimo,1e-12);
    f = figure('name',[nomi{d} ' sul telaio - caso ' num2str(caso)], ...
               'position',[60 60 1200 900],'color','w');
    figure_create(d) = f;
    ax = axes('parent',f);
    hold(ax,'on');

    for e = 1:ne
      oggetti_prima = get(ax,'children');
      a = R.nodi(R.aste(e,1),:); b = R.nodi(R.aste(e,2),:);
      tangente = (b-a)/lunghezze(e);
      normale = verso*[-tangente(2) tangente(1)];
      x = R.x{e}(:);
      valori = R.diagrammi{e}(:,d,caso);
      asse = ones(numel(x),1)*a + x*tangente;
      curva = asse + (scala*valori)*normale;

      % Aree positive e negative, con colori e segni distinti.
      for segno = [1 -1]
        if segno == 1
          parte = max(valori,0); colore = blu;
        else
          parte = min(valori,0); colore = rosso;
        end
        if any(abs(parte)>1e-10)
          bordo = asse + (scala*parte)*normale;
          patch([asse(:,1);flipud(bordo(:,1))], ...
                [asse(:,2);flipud(bordo(:,2))], ...
                0.82+0.18*colore,'edgecolor','none');
          traccia = curva;
          traccia(segno*valori < -1e-10,:) = NaN;
          plot(traccia(:,1),traccia(:,2),'color',colore,'linewidth',2);
        end
      end

      % Trattini collegano l'asse dell'asta al diagramma.
      campioni = unique(round(linspace(1,numel(x),13)));
      for j = campioni
        if valori(j) >= 0, colore = blu; else, colore = rosso; end
        plot([asse(j,1) curva(j,1)],[asse(j,2) curva(j,2)], ...
             'color',0.55+0.45*colore,'linewidth',0.6);
      end

      plot([a(1) b(1)],[a(2) b(2)],'-','color',figura_aste,'linewidth',2.5);
      centro = (a+b)/2;
      text(centro(1),centro(2),sprintf('A%d',e), ...
           'fontsize',9,'backgroundcolor','w','horizontalalignment','center');

      % Etichettiamo il minimo e il massimo campionati di ciascuna asta.
      [vmin, imin] = min(valori); [vmax, imax] = max(valori);
      if max(abs(valori)) < 1e-7*max(1,massimo)
        punto = centro + 0.16*normale;
        text(punto(1),punto(2),'0','fontsize',10,'horizontalalignment','center');
      else
        if abs(vmax-vmin) < 1e-7*max(1,massimo)
          indici = round((numel(x)+1)/2);
        else
          indici = unique([imin imax]);
        end
        for j = indici(:)'
          valore = valori(j);
          direzione = sign(valore); if direzione == 0, direzione = 1; end
          % Spostiamo le etichette degli estremi verso l'interno dell'asta
          % per evitare la sovrapposizione di numeri nei nodi.
          ascissa = min(max(x(j),0.30),lunghezze(e)-0.30);
          punto = a + ascissa*tangente + (scala*valore+0.14*direzione)*normale;
          if valore >= 0, colore = blu; else, colore = rosso; end
          rotazione = 0;
          if abs(tangente(2)) > 0.5, rotazione = 90; end
          text(punto(1),punto(2),sprintf('%+.2f',valore), ...
               'color',colore,'fontsize',10,'fontweight','bold', ...
               'rotation',rotazione,'horizontalalignment','center', ...
               'backgroundcolor','w','margin',1);
        end
      end
      % Ogni oggetto dell'asta risponde al click, incluse le aree colorate.
      oggetti_dopo = get(ax,'children');
      for k = 1:numel(oggetti_dopo)
        h = oggetti_dopo(k);
        if ~any(h == oggetti_prima)
          set(h,'buttondownfcn',@(src,evt) click_asta(f,e));
          setappdata(h,'asta_query',e);
        end
      end
    end

    % Incastri solo nei nodi alla quota minima.
    base = find(abs(R.nodi(:,2)-min(R.nodi(:,2)))<1e-9);
    for j = base(:)'
      p = R.nodi(j,:);
      plot(p(1)+[-.20 .20],p(2)+[0 0],'k-','linewidth',4);
      for dx = -.20:.08:.20
        plot(p(1)+[dx-.07 dx],p(2)+[-.14 0],'k-');
      end
    end
    hp = plot(NaN,NaN,'-','color',blu,'linewidth',2);
    hn = plot(NaN,NaN,'-','color',rosso,'linewidth',2);
    hs = plot(NaN,NaN,'-','color',figura_aste,'linewidth',2);
    lg = legend([hp hn hs],{'Positivo (+)','Negativo (-)','Telaio: linea dello zero'}, ...
           'location','southoutside','orientation','horizontal');
    set(lg,'autoupdate','off');
    axis equal;
    xlim([min(R.nodi(:,1))-1.0 max(R.nodi(:,1))+1.0]);
    ylim([min(R.nodi(:,2))-0.9 max(R.nodi(:,2))+1.0]);
    set(gca,'fontsize',11,'box','off');
    grid on;
    title({[nomi{d} ' [' unita{d} '] - caso ' num2str(caso) ' (senza inviluppo)'], ...
           'Etichette: minimo e massimo di ogni asta, nelle sezioni campionate'}, ...
           'fontsize',13);
    if d == 1
      convenzione = 'M positivo sotto le travi: diagramma sul lato delle fibre tese';
    else
      convenzione = 'Positivi sopra le travi e a sinistra dei pilastri';
    end
    xlabel({'X del telaio [m]',convenzione, ...
      sprintf('Scala: %.3g m sul disegno per 1 %s',scala,unita{d})});
    ylabel('Y del telaio [m]');
    set(ax,'position',[0.075 0.20 0.57 0.69]);
    % Pannello di interrogazione: click oppure asta e x inseriti a mano.
    uicontrol('parent',f,'style','text','units','normalized', ...
      'position',[.72 .84 .26 .08],'string',{'INTERROGA IL DIAGRAMMA', ...
      'Clicca su una linea o area colorata.', 'Oppure inserisci asta e x:'}, ...
      'backgroundcolor','w','fontsize',11,'horizontalalignment','left');
    uicontrol('parent',f,'style','text','units','normalized', ...
      'position',[.72 .79 .06 .025],'string','Asta','backgroundcolor','w');
    campo_asta=uicontrol('parent',f,'style','edit','units','normalized', ...
      'position',[.79 .79 .07 .035],'string','7','backgroundcolor','w');
    uicontrol('parent',f,'style','text','units','normalized', ...
      'position',[.72 .74 .06 .025],'string','x [m]','backgroundcolor','w');
    campo_x=uicontrol('parent',f,'style','edit','units','normalized', ...
      'position',[.79 .74 .12 .035],'string','1.5','backgroundcolor','w');
    uicontrol('parent',f,'style','pushbutton','units','normalized', ...
      'position',[.72 .68 .19 .045],'string','Leggi M, V, N', ...
      'callback',@(src,evt) query_manuale(f));
    % Un testo in un asse separato viene incluso anche nelle immagini.
    ax_info=axes('parent',f,'position',[.72 .26 .27 .39],'visible','off');
    testo=text(ax_info,0,1,{'Nessuna sezione selezionata.', ...
      'Disattiva zoom/pan per cliccare.', 'x parte dal nodo iniziale.', ...
      'Ai nodi scegli il numero asta.'}, ...
      'units','normalized','verticalalignment','top','fontsize',11);
    marcatore=plot(ax,NaN,NaN,'ko','markersize',8, ...
      'markerfacecolor',[1 .8 .15],'hittest','off');
    info=struct('R',R,'caso',caso,'grandezza',d,'scala',scala, ...
      'verso',verso,'assi',ax,'campo_asta',campo_asta,'campo_x',campo_x, ...
      'testo',testo,'marcatore',marcatore);
    setappdata(f,'query_telaio',info);
    axes(ax);
    drawnow;
    set(ax,'position',[0.075 0.20 0.57 0.69]);
    drawnow;
    if ~isempty(cartella)
      print(f,fullfile(cartella,file{d}),'-dpng','-r150');
    end
  end
end


function click_asta(figura,asta)
% Callback: una funzione eseguita quando l'utente clicca sull'asta.
  info=getappdata(figura,'query_telaio');
  punto=get(info.assi,'currentpoint');
  a=info.R.nodi(info.R.aste(asta,1),:);
  b=info.R.nodi(info.R.aste(asta,2),:);
  L=norm(b-a); tangente=(b-a)/L;
  x=max(0,min(L,dot(punto(1,1:2)-a,tangente)));
  aggiorna_query_telaio(figura,asta,x);
end

function query_manuale(figura)
  info=getappdata(figura,'query_telaio');
  asta=str2double(get(info.campo_asta,'string'));
  x=str2double(get(info.campo_x,'string'));
  try
    aggiorna_query_telaio(figura,asta,x);
  catch err
    set(info.testo,'string',sprintf('Dati non validi:\n%s',err.message));
  end
end
