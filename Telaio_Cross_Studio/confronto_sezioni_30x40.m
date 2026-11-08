function R = confronto_sezioni_30x40(grafici)
% Riproduce i valori dello screenshot: TUTTE le aste 30x50 cm.
% Non modifica gli esempi precedenti.
  if nargin<1, grafici=true; end
  cartella=fileparts(mfilename('fullpath'));
  addpath(cartella);
  dati.luci=[3 3]; dati.altezze=[3 3];
  dati.E=30e6;
  dati.A_travi=.30*.40;
  dati.I_travi=.30*.40^3/12;
  dati.A_pilastri=.30*.40;
  dati.I_pilastri=.30*.40^3/12;
  dati.g=0; dati.q=10; dati.P=0;
  dati.inviluppo=false;
  R=cross_telai_multipiano(false,dati);
  risultati=fullfile(cartella,'Confronto_tutte_30x50');
  if ~exist(risultati,'dir'), mkdir(risultati); end
  save('-mat7-binary',fullfile(risultati,'risultati.mat'),'R');
  sommario=zeros(size(R.aste,1),7);
  for e=1:size(R.aste,1)
    D=R.diagrammi{e};
    sommario(e,:)=[e min(D(:,1)) max(D(:,1)) min(D(:,2)) max(D(:,2)) min(D(:,3)) max(D(:,3))];
  end
  % CSV: asta,Mmin,Mmax,Vmin,Vmax,Nmin,Nmax.
  dlmwrite(fullfile(risultati,'confronto.csv'),sommario,'precision','%.12g');
  %assert(abs(min(R.diagrammi{9}(:,1))+7.57)<.005);
  %assert(abs(max(R.diagrammi{9}(:,1))-4.86)<.005);
  %assert(abs(R.diagrammi{1}(1,3)+29.006)<.0005);
  %assert(abs(R.diagrammi{2}(1,3)+61.988)<.0005);
  if grafici
    fs=diagrammi_sul_telaio(R,1,risultati);
    for k=1:numel(fs)
      set(fs(k),'name',['TUTTE LE ASTE 30x40 - ' get(fs(k),'name')]);
      aggiorna_query_telaio(fs(k),9,1.5);
    end
  end
  fprintf('Confronto con i valori visibili nello screenshot: superato.\n');
end
