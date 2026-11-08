function R = cross_telai_multipiano(grafici, dati)
% CROSS_TELAI  Telaio piano multipiano, con tutte le basi incastrate.
% Esempio: R = cross_telai_multipiano();
% Senza grafici: R = cross_telai_multipiano(false);
% Una sola trave: R = cross_telai_multipiano(true, struct('schemi', [1 0 0 0]));
% Unita': m, kN, kN*m. Materiale elastico, analisi del primo ordine.
%
% Cross equilibra le ROTAZIONI. Le traslazioni vengono determinate
% mediante condensazione statica: non e' Cross puro a nodi fissi.

  if nargin < 1, grafici = true; end
  if nargin < 2, dati = struct(); end

  % 1. DATI: modificare qui oppure passare una struttura "dati".
  p.luci = [3 3];             % lunghezze delle campate [m]
  p.altezze = [3 3];              % altezza di ciascun piano [m]
  p.E = 30e6;                % modulo elastico comune [kN/m^2]
  p.A_pilastri = 0.09;        % area di ciascun pilastro [m^2]
  p.I_pilastri = 0.000675;    % inerzia di ciascun pilastro [m^4]
  p.A_travi = 0.09;           % area di ciascuna trave [m^2]
  p.I_travi = 0.000675;       % inerzia di ciascuna trave [m^4]
  p.g = 0;               % permanente sulle travi, positivo in basso
  p.q = 0;             % variabile sulle travi, positivo in basso
  p.P = 10;                  % forza concentrata su ogni trave [kN], in basso
  p.posizione = 0.5;          % frazione della luce: 0.5 = mezzeria
  p.inviluppo = false;        % SOLO true abilita il calcolo dell'inviluppo
  p.schemi = [];              % vuoto: un caso tutto carico, se inviluppo=false
  p.punti = 101;             % sezioni per asta per grafici/inviluppo

  nomi = fieldnames(dati);
  for i = 1:numel(nomi)
    nome = nomi{i};
    assert(isfield(p, nome), ['Parametro sconosciuto: ' nome]);
    p.(nome) = dati.(nome);
  end
  p.luci = p.luci(:)';
  p.g = p.g(:)';
  p.q = p.q(:)';
  p.altezze = p.altezze(:)';
  ncampate = numel(p.luci);
  npiani = numel(p.altezze);
  nb = ncampate*npiani;
  assert(ncampate >= 1 && npiani >= 1);
  % Uno scalare assegna lo stesso valore a tutte le travi.
  for nome = {'g','q','P','posizione'}
    valore = p.(nome{1});
    if isscalar(valore), valore = repmat(valore,1,nb); end
    p.(nome{1}) = valore(:)';
    assert(numel(p.(nome{1})) == nb, 'Servono valori per tutte le travi.');
  end
  assert(all(isfinite(p.P)) && all(p.P >= 0));
  assert(all(isfinite(p.posizione)) && all(p.posizione > 0 & p.posizione < 1));
  assert(isscalar(p.inviluppo) && any(p.inviluppo == [0 1]));

  positivi = [p.luci, p.altezze, p.E, p.A_pilastri, ...
              p.I_pilastri, p.A_travi, p.I_travi];
  assert(nb >= 1 && all(isfinite(positivi)) && all(positivi > 0));
  assert(numel(p.g) == nb && numel(p.q) == nb);
  assert(all(isfinite([p.g p.q])) && all([p.g p.q] >= 0));
  assert(isscalar(p.punti) && p.punti >= 2 && p.punti == fix(p.punti));

  if ~p.inviluppo
    if isempty(p.schemi), schemi = ones(1,nb); else, schemi = p.schemi; end
    assert(isequal(size(schemi),[1 nb]), ...
      'Senza inviluppo specificare un solo caso di carico.');
    assert(all(schemi(:) == 0 | schemi(:) == 1));
  elseif isempty(p.schemi)
    assert(nb <= 10, 'Oltre 10 travi specificare gli schemi manualmente.');
    schemi = zeros(2^nb, nb);
    for c = 1:2^nb
      for b = 1:nb
        schemi(c,b) = bitget(c-1, b);
      end
    end
  else
    schemi = p.schemi;
    assert(columns(schemi) == nb && rows(schemi) >= 1);
    assert(all(schemi(:) == 0 | schemi(:) == 1));
  end
  nc = rows(schemi);

  % 2. Nodi ordinati per livello, da sinistra a destra.
  % Aste: prima tutti i pilastri, poi tutte le travi; per piano.
  np = ncampate + 1;
  ncol = np*npiani;
  X = [0 cumsum(p.luci)]';
  quote = [0 cumsum(p.altezze)];
  nodi = zeros(np*(npiani+1),2);
  pilastri = []; travi = [];
  for piano = 0:npiani
    id = piano*np+(1:np);
    nodi(id,:) = [X quote(piano+1)*ones(np,1)];
    if piano > 0
      inferiori = (piano-1)*np+(1:np)';
      superiori = piano*np+(1:np)';
      pilastri = [pilastri; inferiori superiori];
      travi = [travi; superiori(1:end-1) superiori(2:end)];
    end
  end
  aste = [pilastri; travi];
  ne = rows(aste);
  nd = 3*rows(nodi);
  area = [p.A_pilastri*ones(ncol,1); p.A_travi*ones(nb,1)];
  inerzia = [p.I_pilastri*ones(ncol,1); p.I_travi*ones(nb,1)];
  K = zeros(nd);

  % 3. RIGIDEZZE DELLE ASTE E MATRICE GLOBALE.
  for e = 1:ne
    a = aste(e,1); b = aste(e,2);
    delta = nodi(b,:) - nodi(a,:);
    L(e) = norm(delta);
    co = delta(1)/L(e); si = delta(2)/L(e);
    rot = [co si 0; -si co 0; 0 0 1];
    T{e} = blkdiag(rot, rot); % da spostamenti globali a locali
    ind{e} = [3*a-2:3*a, 3*b-2:3*b];
    kl{e} = rigidezza_asta(p.E, area(e), inerzia(e), L(e));
    id = ind{e};
    K(id,id) = K(id,id) + T{e}'*kl{e}*T{e};
  end

  fissi = 1:3*np;             % ux = uy = theta = 0 alle basi
  liberi = 3*np+1:nd;
  r = 3*(np+1:rows(nodi));          % rotazioni libere
  t = setdiff(liberi, r);     % traslazioni libere
  Krr = K(r,r);

  % 4. TRASLAZIONI: risposta a spostamenti unitari.
  % Theta = theta0 + H*u_t. Ogni colonna di H si calcola con Cross.
  H = zeros(numel(r), numel(t));
  for j = 1:numel(t)
    H(:,j) = cross_rotazioni(Krr, -K(r,t(j)));
  end
  S = K(t,t) + K(t,r)*H;      % rigidezza dopo equilibrio delle rotazioni
  assert(rcond(S) > 1e-12, 'Sistema instabile o troppo mal condizionato.');

  R.parametri = p; R.schemi = schemi;
  R.nodi = nodi; R.aste = aste; R.aste_travi = ncol+(1:nb);
  R.spostamenti = zeros(nd,nc);
  R.reazioni = zeros(numel(fissi),nc);
  R.errore_equilibrio = zeros(1,nc);
  R.errore_confronto = zeros(1,nc);
  R.iterazioni = zeros(1,nc);

  % 5. UN'ANALISI PER CIASCUNA DISPOSIZIONE DEL CARICO.
  for c = 1:nc
    F = zeros(nd,1);
    qlocale = zeros(ne,1);
    Plocale = zeros(ne,1);
    for e = 1:ne
      if e > ncol
        b = e-ncol;
        qlocale(e) = -(p.g(b) + schemi(c,b)*p.q(b));
        Plocale(e) = -schemi(c,b)*p.P(b);
      end
      qy = qlocale(e); le = L(e);
      % Carico uniforme trasversale: forze nodali equivalenti.
      fe{e} = [0; qy*le/2; qy*le^2/12; 0; qy*le/2; -qy*le^2/12];
      if e > ncol
        % Funzioni di forma cubiche di Hermite al punto del carico.
        z = p.posizione(e-ncol);
        H1 = 1-3*z^2+2*z^3; H2 = le*(z-2*z^2+z^3);
        H3 = 3*z^2-2*z^3;   H4 = le*(-z^2+z^3);
        fe{e} = fe{e} + Plocale(e)*[0;H1;H2;0;H3;H4];
      end
      id = ind{e};
      F(id) = F(id) + T{e}'*fe{e};
    end

    theta0 = cross_rotazioni(Krr, F(r));
    u = zeros(nd,1);
    u(t) = S \ (F(t) - K(t,r)*theta0);
    [u(r), R.iterazioni(c)] = cross_rotazioni(Krr, F(r)-K(r,t)*u(t));
    reazioni = K*u-F;
    R.spostamenti(:,c) = u;
    R.reazioni(:,c) = reazioni(fissi);
    R.errore_equilibrio(c) = norm(reazioni(liberi),inf)/max(1,norm(F,inf));

    % Controllo numerico: soluzione diretta dello stesso modello.
    % Questa soluzione NON viene usata per produrre i diagrammi.
    diretto = K(liberi,liberi) \ F(liberi);
    R.errore_confronto(c) = norm(u(liberi)-diretto,inf)/max(1e-12,norm(diretto,inf));

    % 6. DIAGRAMMI: colonne nell'ordine M, V, N.
    for e = 1:ne
      azioni = kl{e}*T{e}*u(ind{e})-fe{e};
      x = linspace(0,L(e),p.punti)';
      attraversato = zeros(size(x));
      distanza = zeros(size(x));
      if e > ncol && p.P(e-ncol) > 0
        posizione = p.posizione(e-ncol)*L(e);
        % Due sezioni coincidenti: subito prima e subito dopo il carico.
        x = [x(x < posizione); posizione; posizione; x(x > posizione)];
        indici = find(x == posizione);
        attraversato = double(x > posizione);
        attraversato(indici(end)) = 1;
        distanza = max(x-posizione,0);
      end
      qy = qlocale(e);
      momento = -azioni(3) + azioni(2)*x + qy*x.^2/2 + Plocale(e)*distanza;
      taglio = azioni(2) + qy*x + Plocale(e)*attraversato;
      normale = -azioni(1)*ones(size(x));
      R.x{e} = x;
      R.diagrammi{e}(:,:,c) = [momento taglio normale];
      R.azioni_estremi{e}(:,c) = azioni;
    end
  end

  % 7. INVILUPPO E INDICI DEI CASI CHE LO PRODUCONO.
  if p.inviluppo
  for e = 1:ne
    [R.minimo{e}, R.caso_minimo{e}] = min(R.diagrammi{e},[],3);
    [R.massimo{e}, R.caso_massimo{e}] = max(R.diagrammi{e},[],3);
  end
  end
  fprintf('\nSchemi: righe = casi, colonne = travi (0 esclude q e P, 1 applica q e P; g sempre presente).\n');
  disp(schemi);
  fprintf('Residuo relativo massimo di equilibrio: %.3e\n', max(R.errore_equilibrio));
  fprintf('Scarto relativo dalla soluzione diretta: %.3e\n', max(R.errore_confronto));

  % 8. GRAFICI: schema e diagrammi separati per ogni asta.
  if grafici
    figure('name','Geometria e numerazione');
    hold on;
    for e = 1:ne
      xy = nodi(aste(e,:),:);
      plot(xy(:,1),xy(:,2),'b-o','linewidth',2);
      text(mean(xy(:,1)),mean(xy(:,2)),sprintf(' A%d',e));
    end
    plot(nodi(1:np,1),nodi(1:np,2),'ks','markersize',10,'markerfacecolor','k');
    % Frecce rosse: forze concentrate verticali verso il basso.
    for b = 1:nb
      if p.P(b) > 0 && any(schemi(:,b))
        estremi = nodi(aste(ncol+b,:),:);
        punto = estremi(1,:) + p.posizione(b)*(estremi(2,:)-estremi(1,:));
        quiver(punto(1),punto(2)+0.65,0,-0.65,0,'r','linewidth',2);
        text(punto(1)+0.08,punto(2)+0.65,sprintf('%g kN',p.P(b)));
      end
    end
    axis equal; grid on; xlabel('X [m]'); ylabel('Y [m]');
    title('Quadrati neri: incastri; aste orientate dal primo al secondo nodo');
    nomi = {'Momento M [kN m]', 'Taglio V [kN]', 'Normale N [kN]'};
    for e = 1:ne
      figure('name',sprintf('Asta %d: nodo %d -> %d',e,aste(e,1),aste(e,2)));
      for d = 1:3
        subplot(3,1,d); hold on;
        if p.inviluppo
          for c = 1:nc
            plot(R.x{e},R.diagrammi{e}(:,d,c),'color',[0.75 0.75 0.75]);
          end
          h1 = plot(R.x{e},R.minimo{e}(:,d),'b-','linewidth',1.8);
          h2 = plot(R.x{e},R.massimo{e}(:,d),'r--','linewidth',1.8);
          legend([h1 h2],{'Minimo','Massimo'});
        else
          plot(R.x{e},R.diagrammi{e}(:,d,1),'b-','linewidth',1.8);
          title(sprintf('Asta %d - caso singolo, senza inviluppo',e));
        end
        plot([0 L(e)],[0 0],'k:');
        grid on; xlabel('x locale [m]'); ylabel(nomi{d});
      end
    end
  end
end

function k = rigidezza_asta(E,A,I,L)
% Asta di Eulero-Bernoulli: deformazione assiale e flessione.
% Ordine dei gradi di liberta' locali: ui, vi, theta_i, uj, vj, theta_j.
  a = E*A/L; b = 12*E*I/L^3; c = 6*E*I/L^2;
  d = 4*E*I/L; h = 2*E*I/L;
  k = [ a  0  0 -a  0  0;
        0  b  c  0 -b  c;
        0  c  d  0 -c  h;
       -a  0  0  a  0  0;
        0 -b -c  0  b -c;
        0  c  h  0 -c  d];
end

function [theta, iter] = cross_rotazioni(Krr, carico)
% Cross in forma algebrica, a traslazioni fissate.
% La diagonale somma i contributi 4EI/L delle aste del nodo.
% Il termine fuori diagonale 2EI/L trasporta meta' della correzione.
% Correggere una rotazione distribuisce lo squilibrio in proporzione
% alle rigidezze delle aste: e' l'equilibratura di Cross.
  theta = zeros(size(carico));
  tolleranza = 1e-12*max(1,norm(carico,inf));
  for iter = 1:10000
    for i = 1:numel(theta)
      squilibrio = carico(i) - Krr(i,:)*theta;
      theta(i) = theta(i) + squilibrio/Krr(i,i);
    end
    if norm(carico-Krr*theta,inf) <= tolleranza
      return;
    end
  end
  error('Cross non converge: controllare modello e rigidezze.');
end
