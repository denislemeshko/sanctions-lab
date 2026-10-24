"""Integration smoke check executed inside the pipeline container."""
import os
import psycopg

with psycopg.connect(host='db', dbname='research', user='datalens_reader',
                      password=os.environ['READER_PASSWORD']) as conn:
    count = conn.execute('SELECT count(*) FROM dashboard_events').fetchone()[0]
    assert count > 0, 'No research results published'
    writable = conn.execute("SELECT has_table_privilege(current_user, 'fx_rates', 'INSERT')").fetchone()[0]
    assert not writable, 'Reader unexpectedly has write access'
    print(f'PASS: read-only login; {count} event reaction rows')
