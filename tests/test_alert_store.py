import tempfile
import unittest
from pathlib import Path
from alert_store import AlertStore


class StoreTests(unittest.TestCase):
    def test_restart_and_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'alerts.db')
            store = AlertStore(path)
            store.add(-123, 1, {'pair': 'BTCUSDT'})
            store.add(-123, 1, {'pair': 'BTCUSDT'})
            row = store.pending(900)[0]
            store.update(row['id'], push_count=2, next_push=123)
            store.db.close()
            store = AlertStore(path)
            rows = store.pending(900)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['push_count'], 2)
            self.assertFalse(store.acknowledge(row['id'], -999))
            self.assertTrue(store.acknowledge(row['id'], -123))
            store.update(row['id'], card_sent=1)
            self.assertEqual(store.pending(900), [])
            store.db.close()

    def test_expired_alerts_not_replayed(self):
        store = AlertStore(':memory:')
        store.add(1, 1, {})
        store.db.execute('UPDATE alerts SET created=0')
        store.db.commit()
        self.assertEqual(store.pending(900), [])
        store.db.close()


if __name__ == '__main__':
    unittest.main()
