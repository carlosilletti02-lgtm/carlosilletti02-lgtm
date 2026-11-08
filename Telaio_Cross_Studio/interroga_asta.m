function S = interroga_asta(R, asta, x, caso, lato)
% Query esatta di una sezione, con x misurata dal nodo iniziale.
% S = interroga_asta(R,7,1.5);     % asta 7, x=1.5 m, caso 1
% lato='sinistra' oppure 'destra' quando x coincide con una forza puntuale.
% Le formule di equilibrio evitano l'interpolazione dei punti del grafico.
  if nargin < 4, caso = 1; end
  if nargin < 5, lato = 'destra'; end
  assert(isscalar(asta) && asta == fix(asta) && asta>=1 && asta<=size(R.aste,1));
  assert(isscalar(caso) && caso == fix(caso) && caso>=1 && caso<=size(R.schemi,1));
  assert(any(strcmp(lato,{'sinistra','destra'})), 'Lato non valido.');
  i=R.aste(asta,1); j=R.aste(asta,2);
  L=norm(R.nodi(j,:)-R.nodi(i,:));
  assert(isscalar(x) && isfinite(x) && x>=0 && x<=L, 'x deve essere fra 0 e L.');
  b=find(R.aste_travi==asta,1);
  qy=0; Py=0; a=0;
  if ~isempty(b)
    p=R.parametri;
    qy=-(p.g(b)+R.schemi(caso,b)*p.q(b));
    if isfield(p,'P')
      Py=-R.schemi(caso,b)*p.P(b);
      a=p.posizione(b)*L;
    end
  end
  forze=R.azioni_estremi{asta}(:,caso);
  sul_carico = abs(Py)>0 && abs(x-a)<=1e-10*max(1,L);
  oltre = x>a;
  if sul_carico, oltre=strcmp(lato,'destra'); end
  S.asta=asta; S.caso=caso; S.x=x; S.L=L; S.lato=lato;
  S.nodi=[i j];
  S.M=-forze(3)+forze(2)*x+qy*x^2/2+Py*max(x-a,0);
  S.V=forze(2)+qy*x+Py*oltre;
  S.N=-forze(1);
  S.sul_carico_concentrato=sul_carico;
  if sul_carico
    S.V_sinistra=forze(2)+qy*x;
    S.V_destra=S.V_sinistra+Py;
  end
end
