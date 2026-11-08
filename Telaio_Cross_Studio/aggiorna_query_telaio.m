function S = aggiorna_query_telaio(figura, asta, x, lato)
% Aggiorna il pannello della figura. Usata anche per verificare le query.
  if nargin<4, lato='destra'; end
  info=getappdata(figura,'query_telaio');
  S=interroga_asta(info.R,asta,x,info.caso,lato);
  set(info.campo_asta,'string',num2str(asta));
  set(info.campo_x,'string',sprintf('%.8g',x));
  valore=[S.M S.V S.N];
  a=info.R.nodi(S.nodi(1),:); b=info.R.nodi(S.nodi(2),:);
  t=(b-a)/S.L; n=info.verso*[-t(2) t(1)];
  punto=a+x*t;
  diagramma=punto+info.scala*valore(info.grandezza)*n;
  set(info.marcatore,'xdata',diagramma(1),'ydata',diagramma(2));
  testo=sprintf(['Asta A%d: nodo %d -> %d\nCaso %d\nx = %.6f m / L = %.3f m\n\n' ...
    'M = %+.6f kN m\nV = %+.6f kN\nN = %+.6f kN\n\nN positivo: trazione\nN negativo: compressione'], ...
    asta,S.nodi(1),S.nodi(2),S.caso,x,S.L,S.M,S.V,S.N);
  if S.sul_carico_concentrato
    testo=[testo sprintf('\n\nSul carico concentrato:\nV sinistra = %+.6f kN\nV destra = %+.6f kN',S.V_sinistra,S.V_destra)];
  end
  set(info.testo,'string',testo);
  setappdata(figura,'ultima_query',S);
  drawnow;
end
