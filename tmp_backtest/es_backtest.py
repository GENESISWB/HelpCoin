import csv, urllib.request, os, math
from collections import defaultdict
from datetime import datetime, time

YEARS = range(2020, 2025)
BASE = 'https://raw.githubusercontent.com/worldtradingchampion-source/btcdata/main/ES_1min_{year}.csv'
POINT_VALUE = 20.0  # 4 MES = 4 * $5/point
TARGET_PTS = 20.0
STOP_PTS = 20.0

# Keep prior completed RTH candle color. User's earlier constraint was 2020-2024, excluding 2025.
prev_rth_color = None
prev_rth_date = None
trades = []
doji_skips = 0
missing_845 = 0
ambiguous_same_minute = 0


def parse_dt(s):
    return datetime.fromisoformat(s)


def finalize_day(day):
    global prev_rth_color, prev_rth_date, doji_skips, missing_845, ambiguous_same_minute
    if day is None:
        return
    date = day['date']
    rth_open = day['rth_open']
    rth_close = day['rth_close']
    entry = day['entry']
    bars = day['bars']

    # Trade today's 08:45 using ONLY the previous completed RTH candle.
    if prev_rth_color is not None:
        if entry is None:
            # Only count this as missing if there was an RTH session today.
            if rth_open is not None:
                missing_845 += 1
        elif prev_rth_color == 'doji':
            doji_skips += 1
        else:
            direction = 'LONG' if prev_rth_color == 'green' else 'SHORT'
            sign = 1 if direction == 'LONG' else -1
            target = entry + sign * TARGET_PTS
            stop = entry - sign * STOP_PTS
            outcome = None
            exit_price = None
            exit_time = None
            ambiguous = False

            for dt, o, h, l, c in bars:
                if direction == 'LONG':
                    t_hit = h >= target
                    s_hit = l <= stop
                else:
                    t_hit = l <= target
                    s_hit = h >= stop
                if t_hit and s_hit:
                    # Minute OHLC cannot determine path. Count conservatively as a stop-loss.
                    ambiguous = True
                    ambiguous_same_minute += 1
                    outcome = 'STOP'
                    exit_price = stop
                    exit_time = dt
                    break
                elif t_hit:
                    outcome = 'TARGET'
                    exit_price = target
                    exit_time = dt
                    break
                elif s_hit:
                    outcome = 'STOP'
                    exit_price = stop
                    exit_time = dt
                    break

            if outcome is None:
                if bars:
                    exit_time, _, _, _, exit_price = bars[-1]
                    outcome = 'EOD'
                else:
                    exit_price = entry
                    exit_time = None
                    outcome = 'EOD'

            points = sign * (exit_price - entry)
            pnl = points * POINT_VALUE
            result = 'WIN' if pnl > 1e-9 else ('LOSS' if pnl < -1e-9 else 'FLAT')
            trades.append({
                'date': str(date), 'year': date.year, 'signal_from': str(prev_rth_date),
                'prev_color': prev_rth_color, 'direction': direction,
                'entry': entry, 'target': target, 'stop': stop,
                'outcome': outcome, 'result': result, 'exit_price': exit_price,
                'exit_time': exit_time.isoformat() if exit_time else '',
                'points': points, 'pnl': pnl, 'ambiguous': ambiguous
            })

    # Update previous daily candle only after today's trade is determined.
    if rth_open is not None and rth_close is not None:
        if rth_close > rth_open:
            prev_rth_color = 'green'
        elif rth_close < rth_open:
            prev_rth_color = 'red'
        else:
            prev_rth_color = 'doji'
        prev_rth_date = date


def new_day(date):
    return {'date': date, 'rth_open': None, 'rth_close': None, 'entry': None, 'bars': []}

for year in YEARS:
    fn = f'ES_1min_{year}.csv'
    if not os.path.exists(fn):
        print(f'Downloading {year}...', flush=True)
        urllib.request.urlretrieve(BASE.format(year=year), fn)
    print(f'Processing {fn}...', flush=True)
    current = None
    with open(fn, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = parse_dt(row['datetime_et'])
            d = dt.date()
            if current is None:
                current = new_day(d)
            elif d != current['date']:
                finalize_day(current)
                current = new_day(d)

            o = float(row['open']); h = float(row['high']); l = float(row['low']); c = float(row['close'])
            rth = row['rth'].strip().lower() == 'true'
            t = dt.timetz().replace(tzinfo=None)

            if rth:
                if current['rth_open'] is None:
                    current['rth_open'] = o
                current['rth_close'] = c

            if t == time(8,45):
                current['entry'] = o

            if time(8,45) <= t <= time(16,0):
                current['bars'].append((dt,o,h,l,c))
    finalize_day(current)

# Restrict to actual requested test dates 2020-01-01 through 2024-12-31.
trades = [t for t in trades if 2020 <= t['year'] <= 2024]

wins = sum(t['result']=='WIN' for t in trades)
losses = sum(t['result']=='LOSS' for t in trades)
flats = sum(t['result']=='FLAT' for t in trades)
targets = sum(t['outcome']=='TARGET' for t in trades)
stops = sum(t['outcome']=='STOP' for t in trades)
eods = sum(t['outcome']=='EOD' for t in trades)
net = sum(t['pnl'] for t in trades)

# streaks (flat breaks both)
max_w = max_l = cur_w = cur_l = 0
for t in trades:
    if t['result']=='WIN':
        cur_w += 1; cur_l = 0; max_w = max(max_w,cur_w)
    elif t['result']=='LOSS':
        cur_l += 1; cur_w = 0; max_l = max(max_l,cur_l)
    else:
        cur_w = cur_l = 0

# max drawdown
cum = 0.0; peak = 0.0; max_dd = 0.0
for t in trades:
    cum += t['pnl']
    peak = max(peak,cum)
    max_dd = max(max_dd, peak-cum)

print('\n=== SUMMARY ===')
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
print(f'DOJI_SKIPS={doji_skips}')
print(f'MISSING_845={missing_845}')
print('\n=== YEARLY ===')
for y in YEARS:
    ys=[t for t in trades if t['year']==y]
    if not ys: continue
    yw=sum(t['result']=='WIN' for t in ys); yl=sum(t['result']=='LOSS' for t in ys); yf=sum(t['result']=='FLAT' for t in ys)
    yp=sum(t['pnl'] for t in ys)
    print(f'{y}: trades={len(ys)} wins={yw} losses={yl} flats={yf} win_rate={yw/len(ys)*100:.2f}% pnl=${yp:.2f}')

print('\n=== OUTCOME BREAKDOWN ===')
print(f'Full +20 targets: {targets}')
print(f'Full -20 stops: {stops}')
print(f'Closed at 16:00 without either barrier: {eods}')

# Print compact first/last samples for auditability.
print('\n=== FIRST 5 TRADES ===')
for t in trades[:5]: print(t)
print('\n=== LAST 5 TRADES ===')
for t in trades[-5:]: print(t)
