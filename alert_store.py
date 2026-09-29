"""Durable delivery state. Keep ALERT_DB on persistent storage in production."""
import json
import sqlite3
import time


class AlertStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER,
            payload TEXT, created REAL, acknowledged INTEGER DEFAULT 0,
            push_count INTEGER DEFAULT 0, next_push REAL DEFAULT 0,
            card_sent INTEGER DEFAULT 0, next_card REAL DEFAULT 0,
            UNIQUE(chat_id, message_id))''')
        self.db.commit()

    def add(self, chat_id, message_id, payload):
        self.db.execute('INSERT OR IGNORE INTO alerts (chat_id,message_id,payload,created) VALUES (?,?,?,?)',
                        (chat_id, message_id, json.dumps(payload), time.time()))
        self.db.commit()

    def pending(self, lifetime):
        return self.db.execute('SELECT * FROM alerts WHERE created > ? AND (card_sent=0 OR acknowledged=0)',
                               (time.time() - lifetime,)).fetchall()

    def update(self, alert_id, **fields):
        allowed = {'acknowledged', 'push_count', 'next_push', 'card_sent', 'next_card'}
        if not fields or not fields.keys() <= allowed:
            raise ValueError('Invalid alert update')
        self.db.execute('UPDATE alerts SET ' + ','.join(f'{key}=?' for key in fields) + ' WHERE id=?',
                        (*fields.values(), alert_id))
        self.db.commit()

    def acknowledge(self, alert_id, chat_id):
        cursor = self.db.execute('UPDATE alerts SET acknowledged=1 WHERE id=? AND chat_id=?', (alert_id, chat_id))
        self.db.commit()
        return cursor.rowcount > 0
