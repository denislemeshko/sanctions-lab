import unittest
from pipeline import parse_rates, reaction_rows, init_db
import sqlite3

class PipelineTests(unittest.TestCase):
    def test_nominal_and_decimal(self):
        xml = b'<ValCurs><Record Date="11.01.2014"><Nominal>10</Nominal><Value>55,1234</Value></Record></ValCurs>'
        self.assertEqual(parse_rates(xml, 'CNY'), [('CNY','2014-01-11',5.51234)])

    def test_negative_rate_rejected(self):
        with self.assertRaises(ValueError):
            parse_rates(b'<ValCurs><Record Date="11.01.2014"><Nominal>1</Nominal><Value>-1</Value></Record></ValCurs>', 'USD')

    def test_weekend_alignment_and_missing_future(self):
        rates = [('USD','2024-06-08',90),('USD','2024-06-11',99),('USD','2024-06-14',100)]
        events = [{'event_id':'a','announcement_date':'2024-06-09','review_status':'source_verified'}]
        rows = reaction_rows(rates, events)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['baseline_date'],'2024-06-08')
        self.assertEqual(rows[0]['end_date'],'2024-06-11')
        self.assertAlmostEqual(rows[0]['change_pct'],10)

    def test_unreviewed_excluded(self):
        self.assertEqual(reaction_rows([('USD','2024-01-01',1),('USD','2024-01-02',2)], [{'event_id':'a','announcement_date':'2024-01-01','review_status':'pending'}]), [])

    def test_structural_break_and_overlap(self):
        rates = [('USD','2024-06-13',90),('USD','2024-06-14',91)]
        events = [{'event_id':i,'announcement_date':'2024-06-13','review_status':'source_verified'} for i in ('a','b')]
        row = reaction_rows(rates, events)[0]
        self.assertEqual(row['methodology_break'],1)
        self.assertEqual(row['other_events_in_window'],1)

    def test_unique_rate_key(self):
        conn = sqlite3.connect(':memory:')
        init_db(conn)
        conn.execute('INSERT INTO rates VALUES(?,?,?)',('USD','2014-01-01',33))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO rates VALUES(?,?,?)',('USD','2014-01-01',34))

if __name__ == '__main__':
    unittest.main()
