import sqlite3,json,os
from pathlib import Path
from app.errors import DomainError

SCHEMA=('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL, '
        'version INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核", '
        'parent TEXT, kind TEXT NOT NULL DEFAULT "ORIGINAL")')

def connection():
    path=Path(os.environ.get('DB_PATH','data/records.db'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute(SCHEMA)
    columns={row[1] for row in db.execute('PRAGMA table_info(runs)')}
    # Existing volumes predate revisions: add columns without dropping rows.
    if 'parent' not in columns:db.execute('ALTER TABLE runs ADD COLUMN parent TEXT')
    if 'kind' not in columns:db.execute('ALTER TABLE runs ADD COLUMN kind TEXT NOT NULL DEFAULT "ORIGINAL"')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    return db

def save(run_id, body, parent=None):
    """Commit a run atomically; the latest pointer moves only after the write."""
    body=dict(body)
    revision={'parent':parent,'kind':'REVISION' if parent else 'ORIGINAL'}
    body['revision']=revision
    payload=json.dumps(body,ensure_ascii=False)
    with connection() as db:
        existing=db.execute('SELECT parent,kind FROM runs WHERE id=?',(run_id,)).fetchone()
        if existing is not None:
            # Same identity means the exact same input bytes, parameters and rule
            # version: the stored revision is authoritative, so a rerun can never
            # add or remove samples.  A different parent is a caller mistake.
            if parent and existing['parent'] not in (None,parent):
                raise DomainError('REVISION','批次号已用于其他修订来源',409)
        else:
            db.execute('INSERT INTO runs(id,body,parent,kind) VALUES (?,?,?,?)',(run_id,payload,parent,revision['kind']))
        db.execute("INSERT INTO meta(key,value) VALUES ('latest',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(run_id,))
    return get(run_id)

def get(run_id):
    with connection() as db:r=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if not r:raise DomainError('NOT_FOUND','批次不存在',404)
    body=json.loads(r['body']);body.update(run_id=r['id'],review_version=r['version'],decision=r['decision'])
    body['revision']={'parent':r['parent'],'kind':r['kind']}
    return body

def history():
    with connection() as db:rows=db.execute("SELECT id,version,decision,parent,kind FROM runs ORDER BY CASE WHEN id=(SELECT value FROM meta WHERE key='latest') THEN 0 ELSE 1 END,rowid DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]

def review(run_id, version, decision):
    if decision not in ('通过','退回'):raise DomainError('DECISION','复核状态无效')
    with connection() as db:
        cur=db.execute('UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?',(decision,run_id,version))
        if cur.rowcount!=1:
            if not db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():raise DomainError('NOT_FOUND','批次不存在',404)
            raise DomainError('STALE','复核版本已更新，请刷新',409)
    return get(run_id)
