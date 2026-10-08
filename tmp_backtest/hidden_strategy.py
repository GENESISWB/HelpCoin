import csv, os, urllib.request, math, statistics
from datetime import datetime, time
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score

BASE='https://raw.githubusercontent.com/worldtradingchampion-source/btcdata/main/ES_1min_{year}.csv'
YEARS=range(2010,2025)
POINT_VALUE=20.0  # 4 MES
TARGET=20.0
STOP=20.0

# Daily records are calendar-date based. For each date we retain only data known by 08:45 for features,
# and 08:45-16:00 for outcome simulation. Previous completed RTH metrics are carried forward.
records=[]
prev_rth=None
rolling=[]

def safe_div(a,b): return a/b if b and abs(b)>1e-12 else 0.0

def process_day(d):
    global prev_rth, rolling
    if d is None: return
    if d['rth_open'] is None or d['rth_close'] is None:
        return
    # Build trade only if exact 08:45 open exists and previous RTH exists.
    if d['entry'] is not None and prev_rth is not None:
        e=d['entry']
        bars=d['post']
        def sim(direction):
            sign=1 if direction==1 else -1
            tgt=e+sign*TARGET; stp=e-sign*STOP
            for dt,o,h,l,c in bars:
                th=(h>=tgt) if direction==1 else (l<=tgt)
                sh=(l<=stp) if direction==1 else (h>=stp)
                if th and sh:
                    return -STOP, 'STOP', dt
                if th: return TARGET, 'TARGET', dt
                if sh: return -STOP, 'STOP', dt
            if bars:
                px=bars[-1][4]
                return sign*(px-e), 'EOD', bars[-1][0]
            return 0.0,'EOD',None
        lp,lo,lt=sim(1); sp,so,st=sim(-1)
        # Supervised target: direction with higher realized PnL that day. Ties use sign of close-entry.
        if lp>sp: y=1
        elif sp>lp: y=0
        else: y=1 if (d['rth_close']-e)>=0 else 0

        pre=d['pre']
        if pre:
            pre_open=pre[0][1]; pre_close=pre[-1][4]
            pre_high=max(x[2] for x in pre); pre_low=min(x[3] for x in pre)
            vols=[x[5] for x in pre]
            total_v=sum(vols)
            vwap=sum(((x[2]+x[3]+x[4])/3)*x[5] for x in pre)/total_v if total_v else pre_close
            # Last 15 and 30 minute momentum before 08:45.
            p15=pre[-16][4] if len(pre)>=16 else pre_open
            p30=pre[-31][4] if len(pre)>=31 else pre_open
            # Realized 1-min absolute movement as simple volatility proxy.
            abs_move=sum(abs(pre[i][4]-pre[i-1][4]) for i in range(1,len(pre)))
        else:
            pre_open=pre_close=pre_high=pre_low=vwap=e; p15=p30=e; abs_move=0.0

        pr=prev_rth
        # Past completed RTH ranges/returns only.
        recent_ranges=[x['range'] for x in rolling[-10:]]
        recent_rets=[x['ret'] for x in rolling[-10:]]
        avg5r=np.mean(recent_ranges[-5:]) if recent_ranges else 0.0
        avg10r=np.mean(recent_ranges) if recent_ranges else 0.0
        sum3=np.sum(recent_rets[-3:]) if recent_rets else 0.0
        sum5=np.sum(recent_rets[-5:]) if recent_rets else 0.0

        feats=[
            pre_close-pre_open,
            e-pre_open,
            e-vwap,
            safe_div(e-pre_low, pre_high-pre_low),
            pre_high-pre_low,
            e-p15,
            e-p30,
            abs_move,
            pr['close']-pr['open'],
            pr['high']-pr['low'],
            e-pr['close'],
            safe_div(pr['close']-pr['low'], pr['high']-pr['low']),
            avg5r, avg10r, sum3, sum5,
            d['date'].weekday(),
        ]
        records.append({'date':d['date'],'year':d['date'].year,'x':feats,'y':y,'long_p':lp,'short_p':sp,'long_o':lo,'short_o':so})

    # update previous completed RTH after today's decision/feature generation
    ret=d['rth_close']-d['rth_open']
    rr={'date':d['date'],'open':d['rth_open'],'close':d['rth_close'],'high':d['rth_high'],'low':d['rth_low'],'ret':ret,'range':d['rth_high']-d['rth_low']}
    prev_rth=rr
    rolling.append(rr)

for year in YEARS:
    fn=f'ES_1min_{year}.csv'
    if not os.path.exists(fn):
        print(f'Downloading {year}...', flush=True)
        urllib.request.urlretrieve(BASE.format(year=year), fn)
    print(f'Processing {year}...', flush=True)
    cur=None
    with open(fn,newline='') as f:
        rd=csv.DictReader(f)
        for row in rd:
            dt=datetime.fromisoformat(row['datetime_et']); date=dt.date(); t=dt.timetz().replace(tzinfo=None)
            if cur is None or date!=cur['date']:
                process_day(cur)
                cur={'date':date,'pre':[],'post':[],'entry':None,'rth_open':None,'rth_close':None,'rth_high':None,'rth_low':None}
            o=float(row['open']); h=float(row['high']); l=float(row['low']); c=float(row['close']); v=float(row['volume']); rth=row['rth'].lower()=='true'
            # current calendar-day overnight/pre-market info available by 08:44
            if t < time(8,45): cur['pre'].append((dt,o,h,l,c,v))
            if t == time(8,45): cur['entry']=o
            if time(8,45) <= t <= time(16,0): cur['post'].append((dt,o,h,l,c))
            if rth:
                if cur['rth_open'] is None: cur['rth_open']=o
                cur['rth_close']=c
                cur['rth_high']=h if cur['rth_high'] is None else max(cur['rth_high'],h)
                cur['rth_low']=l if cur['rth_low'] is None else min(cur['rth_low'],l)
    process_day(cur)

# split strictly by time
train=[r for r in records if r['year']<=2016]
val=[r for r in records if 2017<=r['year']<=2019]
test=[r for r in records if 2020<=r['year']<=2024]

def xy(rows):
    return np.array([r['x'] for r in rows],dtype=float), np.array([r['y'] for r in rows],dtype=int)
Xtr,ytr=xy(train); Xv,yv=xy(val); Xtest,ytest=xy(test)

# Candidate models chosen before touching 2020+. Selection is ONLY on 2017-2019 directional accuracy.
candidates={
 'logit': make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=0.2,max_iter=1000)),
 'rf': RandomForestClassifier(n_estimators=500,max_depth=5,min_samples_leaf=20,max_features=0.7,random_state=42,n_jobs=-1),
 'hgb': HistGradientBoostingClassifier(max_iter=200,learning_rate=0.04,max_depth=3,min_samples_leaf=25,l2_regularization=2.0,random_state=42),
}
vals=[]
for name,m in candidates.items():
    m.fit(Xtr,ytr); pv=m.predict(Xv); acc=accuracy_score(yv,pv); vals.append((acc,name))
    print(f'VALIDATION {name}: {acc*100:.3f}%')
vals.sort(reverse=True)
best_name=vals[0][1]
print('SELECTED_MODEL='+best_name)

# Refit selected architecture on all pre-2020 data only.
pre2020=train+val
Xpre,ypre=xy(pre2020)
model=candidates[best_name]
model.fit(Xpre,ypre)
pred=model.predict(Xtest)

# Apply the frozen predictions to actual 4-MES trades.
trades=[]
for r,p in zip(test,pred):
    direction='LONG' if p==1 else 'SHORT'
    pts=r['long_p'] if p==1 else r['short_p']
    pnl=pts*POINT_VALUE
    result='WIN' if pnl>1e-9 else ('LOSS' if pnl<-1e-9 else 'FLAT')
    outcome=r['long_o'] if p==1 else r['short_o']
    trades.append({'date':r['date'],'year':r['year'],'direction':direction,'points':pts,'pnl':pnl,'result':result,'outcome':outcome})

wins=sum(t['result']=='WIN' for t in trades); losses=sum(t['result']=='LOSS' for t in trades); flats=sum(t['result']=='FLAT' for t in trades)
net=sum(t['pnl'] for t in trades)
maxw=maxl=cw=cl=0; cum=peak=maxdd=0.0
for t in trades:
    if t['result']=='WIN': cw+=1;cl=0;maxw=max(maxw,cw)
    elif t['result']=='LOSS': cl+=1;cw=0;maxl=max(maxl,cl)
    else: cw=cl=0
    cum+=t['pnl']; peak=max(peak,cum); maxdd=max(maxdd,peak-cum)

print('\n=== FROZEN OUT-OF-SAMPLE TEST ===')
print('TEST_PERIOD=2020-2024')
print(f'TRAIN_ROWS={len(train)} VALIDATION_ROWS={len(val)} TEST_ROWS={len(test)}')
print(f'TRADES={len(trades)} WINS={wins} LOSSES={losses} FLATS={flats}')
print(f'WIN_RATE={wins/len(trades)*100:.4f}%')
print(f'LOSS_RATE={losses/len(trades)*100:.4f}%')
print(f'NET_PNL=${net:.2f}')
print(f'AVG_PNL=${net/len(trades):.2f}')
print(f'LONGEST_WIN_STREAK={maxw}')
print(f'LONGEST_LOSS_STREAK={maxl}')
print(f'MAX_DRAWDOWN=${maxdd:.2f}')
print(f'TARGET_HITS={sum(t["outcome"]=="TARGET" for t in trades)}')
print(f'STOP_HITS={sum(t["outcome"]=="STOP" for t in trades)}')
print(f'EOD_EXITS={sum(t["outcome"]=="EOD" for t in trades)}')
print('\n=== YEARLY ===')
for y in range(2020,2025):
    ys=[t for t in trades if t['year']==y]; yw=sum(t['result']=='WIN' for t in ys); yl=sum(t['result']=='LOSS' for t in ys); yp=sum(t['pnl'] for t in ys)
    print(f'{y}: trades={len(ys)} wins={yw} losses={yl} win_rate={yw/len(ys)*100:.2f}% pnl=${yp:.2f}')
