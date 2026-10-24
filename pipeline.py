"""Daily CBR ingestion. Standard library local mode; optional PostgreSQL publication."""
import argparse
import bisect
import csv
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import ssl
import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
EXPORTS = ROOT / 'exports'
CURRENCIES = {'USD': 'R01235', 'EUR': 'R01239', 'CNY': 'R01375'}
LOG = logging.getLogger('pipeline')

def number(value):
    return Decimal(value.replace(',', '.').replace('\u00a0', '').replace(' ', ''))

def parse_rates(payload, currency):
    root = ET.fromstring(payload)
    if root.tag != 'ValCurs':
        raise ValueError('Unexpected CBR response')
    rows = []
    for item in root.findall('Record'):
        day = datetime.strptime(item.attrib['Date'], '%d.%m.%Y').date().isoformat()
        rate = number(item.findtext('Value')) / number(item.findtext('Nominal'))
        if rate <= 0:
            raise ValueError('Non-positive exchange rate')
        rows.append((currency, day, float(rate)))
    return rows

def fetch(url):
    for attempt in range(4):
        try:
            try:
                with urlopen(Request(url, headers={'User-Agent': 'SanctionsResearch/0.1'}), timeout=60) as response:
                    payload = response.read()
            except URLError as exc:
                if os.name != 'nt' or not isinstance(exc.reason, ssl.SSLCertVerificationError):
                    raise
                # Windows HTTPS client validates against the OS certificate store.
                # Never disable TLS verification to work around Python trust errors.
                with tempfile.TemporaryDirectory(dir=DATA) as folder:
                    output = Path(folder) / 'response.bin'
                    subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'fetch-windows.ps1'),
                                    '-Url', url, '-Destination', str(output)], check=True, timeout=90,
                                   capture_output=True)
                    payload = output.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            raw = DATA / 'raw'
            raw.mkdir(parents=True, exist_ok=True)
            (raw / (digest + '.bin')).write_bytes(payload)
            with (raw / 'manifest.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps({'url': url, 'sha256': digest, 'fetched_at': datetime.now(timezone.utc).isoformat()}) + '\n')
            return payload
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)

def init_db(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS rates(currency TEXT, effective_date TEXT, rub_per_unit REAL CHECK(rub_per_unit>0), PRIMARY KEY(currency,effective_date));
    CREATE TABLE IF NOT EXISTS runs(started_at TEXT, finished_at TEXT, status TEXT, detail TEXT);
    ''')

def load_events():
    with (ROOT / 'events.csv').open(encoding='utf-8-sig', newline='') as f:
        events = list(csv.DictReader(f))
    if len({e['event_id'] for e in events}) != len(events):
        raise ValueError('Duplicate event ID')
    for event in events:
        date.fromisoformat(event['announcement_date'])
        if event['jurisdiction'] not in ('US', 'EU') or not event['source_url'].startswith('https://'):
            raise ValueError('Invalid event')
    return events

def reaction_rows(rates, events):
    """Descriptive effective-date alignment; not intraday or causal estimates."""
    output = []
    for currency in CURRENCIES:
        series = sorted((day, value) for c, day, value in rates if c == currency)
        days = [row[0] for row in series]
        for event in events:
            if event['review_status'] != 'source_verified':
                continue
            # Same-date effective rate is treated as the last already-known baseline.
            anchor = bisect.bisect_right(days, event['announcement_date']) - 1
            if anchor < 0:
                continue
            for horizon in (1, 5, 20):
                target = anchor + horizon
                if target >= len(series):
                    continue  # No invented future observations.
                start, baseline = series[anchor]
                end, after = series[target]
                overlap = sum(e['event_id'] != event['event_id'] and start <= e['announcement_date'] <= end for e in events)
                output.append({**event, 'currency': currency, 'horizon_observations': horizon,
                    'baseline_date': start, 'end_date': end,
                    'change_pct': (after / baseline - 1) * 100,
                    'other_events_in_window': overlap,
                    'methodology_break': int(currency in ('USD', 'EUR') and start < '2024-06-14' <= end),
                    'interpretation': 'Positive = RUB depreciation; descriptive, not causal'})
    return output

def write_csv(name, rows, fields):
    with (EXPORTS / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def publish_postgres(rates, events, reactions):
    import psycopg
    from psycopg import sql
    with psycopg.connect('', connect_timeout=15) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS fx_rates(currency text,effective_date date,rub_per_unit double precision,PRIMARY KEY(currency,effective_date))')
        conn.execute('CREATE TABLE IF NOT EXISTS sanctions_events(event_id text PRIMARY KEY,announcement_date date,jurisdiction text,category text,action text,title text,source_url text,review_status text,effective_date date)')
        conn.execute('CREATE TABLE IF NOT EXISTS event_reactions(event_id text,currency text,horizon_observations integer,baseline_date date,end_date date,change_pct double precision,other_events_in_window integer,methodology_break integer,PRIMARY KEY(event_id,currency,horizon_observations))')
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO fx_rates VALUES(%s,%s,%s) ON CONFLICT(currency,effective_date) DO UPDATE SET rub_per_unit=excluded.rub_per_unit', rates)
            conn.execute('DELETE FROM event_reactions')
            conn.execute('DELETE FROM sanctions_events')
            cur.executemany('INSERT INTO sanctions_events VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)', [tuple(e[k] or None for k in ('event_id','announcement_date','jurisdiction','category','action','title','source_url','review_status','effective_date')) for e in events])
            cur.executemany('INSERT INTO event_reactions VALUES(%s,%s,%s,%s,%s,%s,%s,%s)', [tuple(r[k] for k in ('event_id','currency','horizon_observations','baseline_date','end_date','change_pct','other_events_in_window','methodology_break')) for r in reactions])
        conn.execute('CREATE OR REPLACE VIEW dashboard_events AS SELECT r.*,e.announcement_date,e.jurisdiction,e.category,e.title,e.source_url FROM event_reactions r JOIN sanctions_events e USING(event_id)')
        if os.getenv('READER_PASSWORD'):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='datalens_reader'").fetchone():
                conn.execute('CREATE ROLE datalens_reader LOGIN')
            conn.execute(sql.SQL('ALTER ROLE datalens_reader PASSWORD {}').format(sql.Literal(os.environ['READER_PASSWORD'])))
            conn.execute('GRANT USAGE ON SCHEMA public TO datalens_reader')
            conn.execute('GRANT SELECT ON ALL TABLES IN SCHEMA public TO datalens_reader')

def run(offline=False):
    DATA.mkdir(exist_ok=True)
    EXPORTS.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATA / 'research.sqlite') as conn:
        init_db(conn)
        conn.execute('INSERT INTO runs VALUES(?,NULL,?,?)', (started, 'running', ''))
        conn.commit()
        try:
            if not offline:
                today = datetime.now(timezone(timedelta(hours=3))).date()
                for currency, code in CURRENCIES.items():
                    latest = conn.execute('SELECT MAX(effective_date) FROM rates WHERE currency=?', (currency,)).fetchone()[0]
                    begin = max(date(2014,1,1), date.fromisoformat(latest)-timedelta(days=40)) if latest else date(2014,1,1)
                    while begin <= today:
                        end = min(date(begin.year,12,31), today)
                        params = urlencode({'date_req1': begin.strftime('%d/%m/%Y'), 'date_req2': end.strftime('%d/%m/%Y'), 'VAL_NM_RQ': code})
                        rows = parse_rates(fetch('https://www.cbr.ru/scripts/XML_dynamic.asp?' + params), currency)
                        if not rows and (end-begin).days > 14:
                            raise ValueError(f'Empty response for {currency} {begin} {end}')
                        if any(not begin.isoformat() <= row[1] <= end.isoformat() for row in rows):
                            raise ValueError('Out-of-range observations')
                        conn.executemany('INSERT INTO rates VALUES(?,?,?) ON CONFLICT(currency,effective_date) DO UPDATE SET rub_per_unit=excluded.rub_per_unit', rows)
                        conn.commit()
                        LOG.info('%s %s..%s: %s rows', currency, begin, end, len(rows))
                        begin = end + timedelta(days=1)
                        time.sleep(0.25)
            rates = conn.execute('SELECT currency,effective_date,rub_per_unit FROM rates ORDER BY currency,effective_date').fetchall()
            if not rates:
                raise ValueError('No data loaded')
            events = load_events()
            reactions = reaction_rows(rates, events)
            write_csv('fx_rates.csv', [dict(zip(('currency','effective_date','rub_per_unit'), r)) for r in rates], ['currency','effective_date','rub_per_unit'])
            write_csv('sanctions_events.csv', events, list(events[0]))
            if reactions:
                write_csv('event_reactions.csv', reactions, list(reactions[0]))
            if os.getenv('PGHOST'):
                publish_postgres(rates, events, reactions)
            quality = {'generated_at': datetime.now(timezone.utc).isoformat(), 'rate_rows': len(rates), 'event_count': len(events), 'calendar_complete': False, 'latest_dates': {c:max(d for cc,d,v in rates if cc==c) for c in CURRENCIES}, 'warning': 'Starter event sample. No population-level or causal conclusions.'}
            (EXPORTS / 'quality.json').write_text(json.dumps(quality, indent=2), encoding='utf-8')
            conn.execute('UPDATE runs SET finished_at=?,status=?,detail=? WHERE started_at=?', (datetime.now(timezone.utc).isoformat(), 'ok', json.dumps(quality), started))
            conn.commit()
            LOG.info('Completed: %s rates, %s events, %s reactions', len(rates), len(events), len(reactions))
        except Exception as exc:
            conn.rollback()
            conn.execute('UPDATE runs SET finished_at=?,status=?,detail=? WHERE started_at=?', (datetime.now(timezone.utc).isoformat(), 'error', str(exc), started))
            conn.commit()
            raise

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    while True:
        delay = 86400
        try:
            run(args.offline)
        except Exception:
            LOG.exception('Pipeline failed')
            if not args.watch:
                raise
            delay = 60
        if not args.watch:
            break
        time.sleep(delay)
