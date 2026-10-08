import csv, urllib.request, os, bisect
from datetime import datetime, time, timedelta

YEARS = range(2020, 2025)
BASE = 'https://raw.githubusercontent.com/worldtradingchampion-source/btcdata/main/ES_1min_{year}.csv'
POINT_VALUE = 20.0  # 4 MES = 4 * $5/point
TARGET_PTS = 20.0
STOP_PTS = 20.0

# Build true ES daily candles from the Globex session:
# 18:00 ET prior calendar day through 17:00 ET session date.
sessions = {}      # session_date -> [open, close]
trade_days = {}    # calendar trade date -> {entry, bars}


def parse_dt(s):
    return datetime.fromisoformat(s)

for year in YEARS:
    fn = f'ES_1min_{year}.csv'
    if not os.path.exists(fn):
        print(f'Downloading {year}...', flush=True)
        urllib.request.urlretrieve(BASE.format(year=year), fn)
    print(f'Processing {fn}...', flush=True)
    with open(fn, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = parse_dt(row['datetime_et'])
            d = dt.date()
            t = dt.timetz().replace(tzinfo=None)
            o = float(row['open']); h = float(row['high']); l = float(row['low']); c = float(row['close'])

            # CME equity-index futures trading day: evening bars belong to next session date.
            sess_date = d + timedelta(days=1) if t >= time(18,0) else d
            if sess_date not in sessions:
                sessions[sess_date] = [o, c]
            else:
                sessions[sess_date][1] = c

            td = trade_days.setdefault(d, {'entry': None, 'bars': []})
            if t == time(8,45):
                td['entry'] = o
            if time(8,45) <= t <= time(16,0):
                td['bars'].append((dt,o,h,l,c))

session_dates = sorted(sessions)
trades = []
dojs = 0
missing_845 = 0
ambiguous_same_minute = 0

for d in sorted(trade_days):
    if not (2020 <= d.year <= 2024):
        continue
    day = trade_days[d]
    if day['entry'] is None:
        continue

    # Most recent COMPLETED daily Globex candle strictly before today's session date.
    i = bisect.bisect_left(session_dates, d) - 1
    if i < 0:
        continue
    prev_date = session_dates[i]
    prev_open, prev_close = sessions[prev_date]
    if prev_close > prev_open:
        prev_color = 'green'
        direction = 'LONG'
    elif prev_close < prev_open:
        prev_color = 'red'
        direction = 'SHORT'
    else:
        dojs += 1
        continue

    entry = day['entry']
    bars = day['bars']
    sign = 1 if direction == 'LONG' else -1
    target = entry + sign * TARGET_PTS
    stop = entry - sign * STOP_PTS
    outcome = None
    exit_price = None
    exit_time = None
    ambiguous = False

    for dt,o,h,l,c in bars:
        if direction == 'LONG':
            t_hit = h >= target
            s_hit = l <= stop
        else:
            t_hit = l <= target
            s_hit = h >= stop
        if t_hit and s_hit:
            # 1-minute OHLC cannot tell which came first; conservative treatment = stop.
            ambiguous = True
            ambiguous_same_minute += 1
            outcome = 'STOP'
            exit_price = stop
            exit_time = dt
            break
        elif t_hit:
            outcome = 'TARGET'; exit_price = target; exit_time = dt; break
        elif s_hit:
            outcome = 'STOP'; exit_price = stop; exit_time = dt; break

    if outcome is None:
        if bars:
            exit_time, _, _, _, exit_price = bars[-1]
        else:
            exit_price = entry
        outcome = 'EOD'

    points = sign * (exit_price - entry)
    pnl = points * POINT_VALUE
    result = 'WIN' if pnl > 1e-9 else ('LOSS' if pnl < -1e-9 else 'FLAT')
    trades.append({
        'date': str(d), 'year': d.year, 'signal_from': str(prev_date),
        'prev_color': prev_color, 'direction': direction,
        'entry': entry, 'target': target, 'stop': stop,
        'outcome': outcome, 'result': result,
        'exit_price': exit_price,
        'exit_time': exit_time.isoformat() if exit_time else '',
        'points': points, 'pnl': pnl, 'ambiguous': ambiguous
    })

wins = sum(t['result']=='WIN' for t in trades)
losses = sum(t['result']=='LOSS' for t in trades)
flats = sum(t['result']=='FLAT' for t in trades)
targets = sum(t['outcome']=='TARGET' for t in trades)
stops = sum(t['outcome']=='STOP' for t in trades)
eods = sum(t['outcome']=='EOD' for t in trades)
net = sum(t['pnl'] for t in trades)

max_w = max_l = cur_w = cur_l = 0
for t in trades:
    if t['result']=='WIN':
        cur_w += 1; cur_l = 0; max_w = max(max_w,cur_w)
    elif t['result']=='LOSS':
        cur_l += 1; cur_w = 0; max_l = max(max_l,cur_l)
    else:
        cur_w = cur_l = 0

cum = 0.0; peak = 0.0; max_dd = 0.0
for t in trades:
    cum += t['pnl']
    peak = max(peak,cum)
    max_dd = max(max_dd, peak-cum)

print('\n=== SUMMARY GLOBEX DAILY SIGNAL ===')
print('PERIOD=2020-2024')
print(f'TRADES={len(trades)}')
print(f'WINS={wins}')
print(f'LOSSES={losses}')
print(f'FLATS={flats}')
print(f'WIN_RATE={wins/len(trades)*100:.4f}' if trades else 'WIN_RATE=NA')
print(f'LOSS_RATE={losses/len(trades)*100:.4f}' if trades else 'LOSS_RATE=NA')
print(f'TARGET_HITS={targets}')
print(f'STOP_HITS={stops}')
print(f'EOD_EXITS={eods}')
print(f'NET_PNL=${net:.2f}')
print(f'AVG_PNL_PER_TRADE=${net/len(trades):.2f}' if trades else 'AVG_PNL_PER_TRADE=NA')
print(f'LONGEST_WIN_STREAK={max_w}')
print(f'LONGEST_LOSS_STREAK={max_l}')
print(f'MAX_DRAWDOWN=${max_dd:.2f}')
print(f'AMBIGUOUS_SAME_MINUTE={ambiguous_same_minute}')
print(f'DOJI_SKIPS={dojs}')
print('\n=== YEARLY ===')
for y in YEARS:
    ys=[t for t in trades if t['year']==y]
    if not ys: continue
    yw=sum(t['result']=='WIN' for t in ys); yl=sum(t['result']=='LOSS' for t in ys); yf=sum(t['result']=='FLAT' for t in ys)
    yp=sum(t['pnl'] for t in ys)
    print(f'{y}: trades={len(ys)} wins={yw} losses={yl} flats={yf} win_rate={yw/len(ys)*100:.2f}% pnl=${yp:.2f}')

print('\n=== FIRST 5 TRADES ===')
for t in trades[:5]: print(t)
print('\n=== LAST 5 TRADES ===')
for t in trades[-5:]: print(t)
