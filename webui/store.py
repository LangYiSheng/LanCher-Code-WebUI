"""Web 元数据和有限事件缓存；Agent 历史始终由 SDK 保存。"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preferences(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS file_baselines(chat_id TEXT,path TEXT,content TEXT,PRIMARY KEY(chat_id,path));
        CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,project_id TEXT,chat_id TEXT,server_id TEXT,data TEXT NOT NULL);
        ''')
        self.db.commit()

    def load(self, table):
        if table not in {'projects','chats','preferences'}:
            raise ValueError('未知元数据表')
        return {row[0]:json.loads(row[1]) for row in self.db.execute(f'SELECT id,data FROM {table}')}

    def put(self, table, identity, data):
        if table not in {'projects','chats','preferences'}:
            raise ValueError('未知元数据表')
        self.db.execute(f'INSERT INTO {table} VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (identity,json.dumps(data,ensure_ascii=False)))
        self.db.commit()

    def remove(self, table, identity):
        if table not in {'projects','chats'}:
            raise ValueError('未知元数据表')
        self.db.execute(f'DELETE FROM {table} WHERE id=?',(identity,))
        self.db.commit()

    @property
    def watermark(self):
        return self.db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]

    def event(self, data):
        cursor=self.db.execute('INSERT INTO events(data) VALUES(?)',(json.dumps(data,ensure_ascii=False),))
        sequence=cursor.lastrowid
        if sequence % 100 == 0:
            self.db.execute('DELETE FROM events WHERE sequence < ?',(sequence-2000,))
        self.db.commit()
        return {**data,'sequence':sequence}

    def events_after(self, after):
        return [{**json.loads(row[1]),'sequence':row[0]} for row in self.db.execute(
            'SELECT sequence,data FROM events WHERE sequence>? ORDER BY sequence LIMIT 500',(after,))]

    def cursor_valid(self, after):
        minimum=self.db.execute('SELECT MIN(sequence) FROM events').fetchone()[0]
        return not after or minimum is None or minimum-1 <= after <= self.watermark

    def request(self, record, project_id, chat_id, server_id):
        self.db.execute('''INSERT INTO requests VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
          project_id=excluded.project_id,chat_id=excluded.chat_id,server_id=COALESCE(excluded.server_id,requests.server_id),data=excluded.data''',
          (record['request_id'],project_id,chat_id,server_id,json.dumps(record,ensure_ascii=False)))
        self.db.commit()

    def requests(self, *, project_id=None, chat_id=None, server_id=None):
        filters=[]; values=[]
        for key,value in [('project_id',project_id),('chat_id',chat_id),('server_id',server_id)]:
            if value is not None:
                filters.append(key+'=?');values.append(value)
        query='SELECT data FROM requests'+(' WHERE '+' AND '.join(filters) if filters else '')
        return [json.loads(row[0]) for row in self.db.execute(query,values)]

    def file_baseline(self,chat_id,path,content):
        self.db.execute('INSERT OR IGNORE INTO file_baselines VALUES(?,?,?)',(chat_id,path,content))
        self.db.commit()

    def file_baselines(self,chat_id):
        return dict(self.db.execute('SELECT path,content FROM file_baselines WHERE chat_id=?',(chat_id,)))

    def close(self):
        self.db.close()
