import json
import sqlite3
import threading
from dataclasses import asdict
from src.models import JobPosting
from src.content import clean_description, invalid_reason, canonical_url, fingerprint


class JobDatabase:
    def __init__(self, db_path='jobs.db'):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.create_table()

    def create_table(self):
        with self.lock, self.conn:
            self.conn.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
                url TEXT, description TEXT, source TEXT, status TEXT DEFAULT 'PENDING',
                tier TEXT, ai_reason TEXT, date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            existing = {r['name'] for r in self.conn.execute('PRAGMA table_info(jobs)')}
            for name, kind in {'criteria_version':'TEXT', 'fingerprint':'TEXT', 'canonical_url':'TEXT', 'duplicate_of':'TEXT', 'notification_status':"TEXT DEFAULT 'NONE'", 'application_status':"TEXT DEFAULT 'saved'", 'notes':"TEXT DEFAULT ''", 'deadline':'TEXT'}.items():
                if name not in existing:
                    self.conn.execute(f'ALTER TABLE jobs ADD COLUMN {name} {kind}')
            self.conn.execute('CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS jobs_fingerprint ON jobs(fingerprint)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS jobs_url ON jobs(canonical_url)')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                run_id TEXT, model TEXT, jobs INTEGER, input_tokens INTEGER,
                output_tokens INTEGER, cache_hit_tokens INTEGER, cache_miss_tokens INTEGER,
                estimated INTEGER, cost_usd REAL, latency REAL, error TEXT)''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY, job_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT, tier TEXT, reason TEXT, criteria_version TEXT)''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS scraper_runs (
                id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                source TEXT, fetched INTEGER, added INTEGER, invalid INTEGER, duplicates INTEGER, error TEXT)''')

    def is_job_seen(self, job_id):
        with self.lock:
            return self.conn.execute("SELECT 1 FROM jobs WHERE id=? AND status != 'INVALID'", (job_id,)).fetchone() is not None

    def add_job(self, job):
        job.description = clean_description(job.description)
        reason = invalid_reason(job.description)
        fp, url = fingerprint(job), canonical_url(job.url)
        with self.lock, self.conn:
            duplicate = self.conn.execute("SELECT id FROM jobs WHERE id != ? AND status NOT IN ('INVALID','DUPLICATE') AND (fingerprint=? OR canonical_url=?) LIMIT 1", (job.id, fp, url)).fetchone()
            status = 'INVALID' if reason else 'DUPLICATE' if duplicate else 'PENDING'
            values = asdict(job)
            values.update(status=status, ai_reason=reason, fingerprint=fp, canonical_url=url, duplicate_of=duplicate['id'] if duplicate else None)
            fields = ','.join(values)
            placeholders = ','.join(':'+k for k in values)
            updates = ','.join(f'{k}=excluded.{k}' for k in values if k != 'id')
            cursor = self.conn.execute(f"INSERT INTO jobs ({fields}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates} WHERE jobs.status='INVALID'", values)
            return status if cursor.rowcount else 'SEEN'

    def get_pending_jobs(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM jobs WHERE status='PENDING' ORDER BY date_added,id").fetchall()
        return [self.to_job(r) for r in rows]

    @staticmethod
    def to_job(row):
        return JobPosting(**{k: row[k] for k in JobPosting.__dataclass_fields__})

    def update_job_status(self, job_id, status, reason='', tier='NONE', criteria_version=None):
        with self.lock, self.conn:
            self.conn.execute('INSERT INTO evaluations(job_id,status,tier,reason,criteria_version) VALUES (?,?,?,?,?)', (job_id,status,tier,reason,criteria_version))
            self.conn.execute("UPDATE jobs SET status=?,ai_reason=?,tier=?,criteria_version=?,notification_status=CASE WHEN ?='APPROVED' THEN CASE WHEN notification_status='SENT' THEN 'SENT' ELSE 'PENDING' END ELSE 'NONE' END WHERE id=?", (status,reason,tier,criteria_version,status,job_id))

    def audit(self):
        """Preserve old decisions in history before flagging damaged descriptions."""
        counts = {'invalid':0, 'duplicates':0}
        with self.lock, self.conn:
            rows = self.conn.execute('SELECT * FROM jobs ORDER BY date_added,id').fetchall()
            seen_fp, seen_url = {}, {}
            for row in rows:
                job = self.to_job(row)
                fp, url = fingerprint(job), canonical_url(job.url)
                self.conn.execute('UPDATE jobs SET fingerprint=?,canonical_url=? WHERE id=?', (fp,url,job.id))
                reason = invalid_reason(job.description)
                if reason:
                    if row['status'] != 'INVALID':
                        self.conn.execute('INSERT INTO evaluations(job_id,status,tier,reason,criteria_version) VALUES (?,?,?,?,?)', (job.id,row['status'],row['tier'],row['ai_reason'],row['criteria_version']))
                        self.conn.execute("UPDATE jobs SET status='INVALID',ai_reason=?,notification_status='NONE' WHERE id=?", (reason,job.id))
                        counts['invalid'] += 1
                    continue
                duplicate = seen_fp.get(fp) or seen_url.get(url)
                if duplicate:
                    self.conn.execute('UPDATE jobs SET duplicate_of=? WHERE id=?', (duplicate,job.id))
                    if row['status'] == 'PENDING':
                        self.conn.execute("UPDATE jobs SET status='DUPLICATE' WHERE id=?", (job.id,))
                    counts['duplicates'] += 1
                else:
                    seen_fp[fp], seen_url[url] = job.id, job.id
        return counts

    def record_usage(self, **values):
        with self.lock, self.conn:
            self.conn.execute(f"INSERT INTO api_usage ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))

    def pending_notifications(self):
        with self.lock:
            return self.conn.execute("SELECT * FROM jobs WHERE status='APPROVED' AND notification_status='PENDING'").fetchall()

    def notification_sent(self, job_id):
        with self.lock, self.conn:
            self.conn.execute("UPDATE jobs SET notification_status='SENT' WHERE id=?", (job_id,))

    def close(self):
        self.conn.close()
