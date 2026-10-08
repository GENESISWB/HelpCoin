import csv, os, urllib.request
from collections import defaultdict
from datetime import datetime, time, timedelta

YEARS = range(2010, 2025)
BASE = 'https://raw.githubusercontent.com/worldtradingchampion-source/btcdata/main/ES_1min_{year}.csv'
POINT_VALUE = 20.0  # 4 MES total dollars per ES point
TP = 20.0
SL = 20.0

sessions = {}  # session_date -> {'open':x,'close':y}
days = {}      # calendar date -> intraday data

def sgn(x):
    return 1 if x >= 0 else -1

def new_day(d):
    return {'date': d, 'p800': None, 'p830': None, 'p844': None, 'entry': None, 'bars': []}

for year in YEARS:
    fn = f'ES_1min_{year}.csv'
    if not os.path.exists(fn):
        print(f'Downloading {year}...', flush=True)
        urllib.request.urlretrieve(BASE.format(year=year), fn)
    print(f'Processing {year}...', flush=True)
    with open(fn, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            dt = datetime.fromisoformat(row['datetime_et'])
            d = dt.date(); t = dt.timetz().replace(tzinfo=None)
            o=float(row['open']); h=float(row['high']); l=float(row['low']); c=float(row['close'])

            # Globex session date: 18:00 previous calendar day through 17:00 session date.
            sd = d + timedelta(days=1) if t >= time(18,0) else d
            if sd not in sessions:
                sessions[sd] = {'open': o, 'close': c}
            else:
                sessions[sd]['close'] = c

            day = days.setdefault(d, new_day(d))
            if t == time(8,0): day['p800'] = o
            if t == time(8,30): day['p830'] = o
            if t == time(8,44): day['p844'] = c
            if t == time(8,45): day['entry'] = o
            if time(8,45) <= t <= time(16,0):
                day['bars'].append((dt,o,h,l,c))

session_dates = sorted(sessions)
prev_session = {}
last = None
for sd in session_dates:
    prev_session[sd] = last
    last = sd

# Freeze a tiny menu of deterministic, obvious signals. No ML, no fitting of coefficients.
def signals_for(d):
    day = days[d]
    if day['entry'] is None or day['p844'] is None or day['p800'] is None or day['p830'] is None:
        return None
    cur_sess = sessions.get(d)
    psd = prev_session.get(d)
    prev_sess = sessions.get(psd) if psd else None
    if not cur_sess or not prev_sess:
        return None
    a = sgn(day['p844'] - day['p800'])
    b = sgn(day['p844'] - day['p830'])
    c = sgn(day['p844'] - cur_sess['open'])
    p = sgn(prev_sess['close'] - prev_sess['open'])
    def maj(x,y,z): return 1 if x+y+z >= 1 else -1
    return {
        'S1': a,
        'S2': b,
        'S3': c,
        'S4': p,
        'S5': maj(a,b,c),
        'S6': maj(a,c,p),
    }

def simulate_trade(d, direction):
    day = days[d]
    entry = day['entry']
    target = entry + direction*TP
    stop = entry - direction*SL
    outcome='EOD'; exitp=entry
    for dt,o,h,l,c in day['bars']:
        if direction == 1:
            th = h >= target; sh = l <= stop
        else:
            th = l <= target; sh = h >= stop
        if th and sh:
            # conservative on any ambiguous 1-min bar
            exitp = stop; outcome='STOP'; break
        if th:
            exitp = target; outcome='TARGET'; break
        if sh:
            exitp = stop; outcome='STOP'; break
        exitp = c
    pts = direction*(exitp-entry)
    pnl = pts*POINT_VALUE
    result = 'WIN' if pnl>1e-9 else ('LOSS' if pnl<-1e-9 else 'FLAT')
    return result,pnl,outcome

eligible=[]
for d in sorted(days):
    if d.year < 2010 or d.year > 2024: continue
    sigs=signals_for(d)
    if sigs is not None and days[d]['bars']:
        eligible.append((d,sigs))

candidates=['S1','S2','S3','S4','S5','S6']

def stats(rule, y0, y1):
    rec=[]
    for d,sigs in eligible:
        if y0 <= d.year <= y1:
            res,pnl,out=simulate_trade(d,sigs[rule])
            rec.append((d,res,pnl,out))
    n=len(rec); w=sum(r[1]=='WIN' for r in rec); l=sum(r[1]=='LOSS' for r in rec); f=n-w-l
    net=sum(r[2] for r in rec)
    wr=w/n*100 if n else 0
    return {'n':n,'w':w,'l':l,'f':f,'wr':wr,'net':net,'rec':rec}

print('\n=== DEVELOPMENT 2010-2016 ===')
dev={}
for r in candidates:
    dev[r]=stats(r,2010,2016)
    print(f'{r}: n={dev[r]["n"]} win_rate={dev[r]["wr"]:.3f}% net=${dev[r]["net"]:.0f}')

print('\n=== VALIDATION 2017-2019 ===')
val={}
for r in candidates:
    val[r]=stats(r,2017,2019)
    print(f'{r}: n={val[r]["n"]} win_rate={val[r]["wr"]:.3f}% net=${val[r]["net"]:.0f}')

# Robustly prefer a rule that held up in BOTH pre-2020 windows.
# Primary score is the worse of development/validation win rates; validation breaks ties.
selected=max(candidates, key=lambda r:(min(dev[r]['wr'],val[r]['wr']), val[r]['wr'], dev[r]['wr']))
print(f'\nSELECTED={selected}')
print(f'SELECTION_FLOOR={min(dev[selected]["wr"],val[selected]["wr"]):.3f}%')

# One untouched shot on 2020-2024.
test=stats(selected,2020,2024)
rec=test['rec']
maxw=maxl=cw=cl=0
cum=peak=maxdd=0.0
targets=stops=eods=0
byyear=defaultdict(list)
for d,res,pnl,out in rec:
    byyear[d.year].append((res,pnl,out))
    if res=='WIN': cw+=1; cl=0; maxw=max(maxw,cw)
    elif res=='LOSS': cl+=1; cw=0; maxl=max(maxl,cl)
    else: cw=cl=0
    cum += pnl; peak=max(peak,cum); maxdd=max(maxdd,peak-cum)
    targets += out=='TARGET'; stops += out=='STOP'; eods += out=='EOD'

print('\n=== FROZEN OUT-OF-SAMPLE 2020-2024 ===')
print(f'TRADES={test["n"]}')
print(f'WINS={test["w"]}')
print(f'LOSSES={test["l"]}')
print(f'FLATS={test["f"]}')
print(f'WIN_RATE={test["wr"]:.4f}%')
print(f'NET_PNL=${test["net"]:.2f}')
print(f'AVG_PNL=${test["net"]/test["n"]:.2f}')
print(f'LONGEST_WIN_STREAK={maxw}')
print(f'LONGEST_LOSS_STREAK={maxl}')
print(f'MAX_DRAWDOWN=${maxdd:.2f}')
print(f'TARGET_HITS={targets}')
print(f'STOP_HITS={stops}')
print(f'EOD_EXITS={eods}')
print('\n=== YEARLY ===')
for y in range(2020,2025):
    rr=byyear[y]; n=len(rr); w=sum(x[0]=='WIN' for x in rr); l=sum(x[0]=='LOSS' for x in rr); f=n-w-l; net=sum(x[1] for x in rr)
    print(f'{y}: trades={n} wins={w} losses={l} flats={f} win_rate={w/n*100:.2f}% pnl=${net:.2f}')
