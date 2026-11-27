"""Uji ciri antrean penutupan IDX (kiriman laptop): IC harian terhadap hasil 1-5 hari dan versi ketat
(beli di penutupan besok). Jalankan lokal: python scripts/riset_antrean.py"""
from pathlib import Path
import json,glob,numpy as np,pandas as pd
rows=[]
for f in sorted(glob.glob(str(Path(__file__).resolve().parent.parent/'docs'/'data'/'broker'/'hari'/'*.json'))):
    d=json.load(open(f))
    if not d.get('idx'): continue
    t=d['tanggal']
    for k,v in d['idx'].items():
        if len(v)<13: continue
        fb,fs,c,prev,val,frek,ls,bid,bidv,off,offv,vol,nego=v
        rows.append(dict(t=t,kode=k,c=c,prev=prev,val=val,frek=frek,fb=fb,fs=fs,bid=bid,bidv=bidv,off=off,offv=offv,vol=vol,nego=nego))
d=pd.DataFrame(rows).sort_values(['kode','t'])
g=d.groupby('kode')
d['r1']=d.c/d.prev-1
for h in (1,3,5):
    d[f'f{h}']=g.c.shift(-h)/d.c-1
d['nilai20']=g.val.transform(lambda x:x.rolling(20,min_periods=10).mean())
d=d[(d.c>=50)]
d['lot_trx']=d.vol/100/d.frek.replace(0,np.nan)
d['rasio_lot']=d.lot_trx/g.lot_trx.transform(lambda x:x.shift(1).rolling(20,min_periods=10).mean()) if False else np.nan
d=d.sort_values(['kode','t']);g=d.groupby('kode')
d['rasio_lot']=d.lot_trx/g.lot_trx.transform(lambda x:x.shift(1).rolling(20,min_periods=10).mean())
d['rasio_frek']=d.frek/g.frek.transform(lambda x:x.shift(1).rolling(20,min_periods=10).mean())
d['antrean']=d.bidv/(d.bidv+d.offv).replace(0,np.nan)
d['tutup_offer']=((d.off>0)&(d.c>=d.off)).astype(float)
d['tutup_bid']=((d.bid>0)&(d.c<=d.bid)).astype(float)
d['nego_pct']=d.nego/(d.val+d.nego).replace(0,np.nan)
d['asing']=(d.fb-d.fs)*d.c/d.val.replace(0,np.nan)
d['asing5']=g.apply(lambda x:((x.fb-x.fs)*x.c).rolling(5).sum()/x.val.rolling(5).sum()).reset_index(level=0,drop=True)
L=d[(d.nilai20>=1e9)&(d.val>0)].copy()
print('baris',len(L),'hari',L.t.nunique(),'saham/hari ~',round(len(L)/L.t.nunique()))
ciri=['antrean','tutup_offer','tutup_bid','rasio_lot','rasio_frek','nego_pct','asing','asing5','r1']
out=[]
for c in ciri:
    for h in (1,3,5):
        ics=[]
        for t,x in L.dropna(subset=[c,f'f{h}']).groupby('t'):
            if len(x)<30 or x[c].nunique()<3: continue
            ics.append(x[c].rank().corr(x[f'f{h}'].rank()))
        ics=np.array(ics)
        if len(ics)<10: continue
        # selisih 20% teratas vs terbawah
        sel=[]
        for t,x in L.dropna(subset=[c,f'f{h}']).groupby('t'):
            if len(x)<30 or x[c].nunique()<3: continue
            q=x[c].rank(pct=True,method='first')
            sel.append(x.loc[q>0.8,f'f{h}'].mean()-x.loc[q<=0.2,f'f{h}'].mean())
        sel=np.array(sel)
        out.append(dict(ciri=c,hari=h,n_hari=len(ics),IC=round(ics.mean(),3),t_IC=round(ics.mean()/(ics.std()/np.sqrt(len(ics)))*np.sqrt(1/h) if h>1 else ics.mean()/(ics.std()/np.sqrt(len(ics))),2),atas_vs_bawah=round(sel.mean()*100,2)))
print(pd.DataFrame(out).to_string(index=False))
# biner
for c in ['tutup_offer','tutup_bid']:
    for h in (1,3):
        x=L.dropna(subset=[f'f{h}']).copy(); x['ex']=x[f'f{h}']-x.groupby('t')[f'f{h}'].transform('mean')
        a=x[x[c]==1].ex
        print(c,h,'n',len(a),'selisih% ',round(a.mean()*100,3),'t',round(a.mean()/(a.std()/np.sqrt(len(a))),2))
print("\n=== UJI KETAT: beli di penutupan BESOK (t+1), ukur sampai t+4 / t+6 ===")
d=d.sort_values(['kode','t']);g=d.groupby('kode')
d['g14']=g.c.shift(-4)/g.c.shift(-1)-1
d['g16']=g.c.shift(-6)/g.c.shift(-1)-1
L=d[(d.nilai20>=1e9)&(d.val>0)].copy()
def ic(df,c,y):
    v=[]
    for t,x in df.dropna(subset=[c,y]).groupby('t'):
        if len(x)<30 or x[c].nunique()<3: continue
        q=x[c].rank(pct=True,method='first')
        v.append((x[c].rank().corr(x[y].rank()),x.loc[q>0.8,y].mean()-x.loc[q<=0.2,y].mean()))
    v=np.array(v);return len(v),round(v[:,0].mean(),3),round(v[:,0].mean()/(v[:,0].std()/np.sqrt(len(v))),2),round(v[:,1].mean()*100,2)
for nm,sub in [("semua",L),("hanya tutup di tengah (bukan di bid/offer)",L[(L.tutup_offer==0)&(L.tutup_bid==0)]),("hanya tutup di offer",L[L.tutup_offer==1]),("hanya tutup di bid",L[L.tutup_bid==1])]:
    for y in ['f1','g14','g16']:
        print(nm,'| antrean |',y,'| hari,IC,t,atas-bawah%:',ic(sub,'antrean',y))
for c in ['rasio_lot','asing','tutup_bid','tutup_offer']:
    print(c,'g14',ic(L,c,'g14'))
