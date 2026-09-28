"""One durable local worker. Interrupted work is retried only on explicit request."""
import json
import os
import threading

from src.cv import encode, one, rows


class CVWorker:
    def __init__(self, service):
        self.service = service
        self.db = service.db
        self.stop_event = threading.Event()
        self.thread = None
        self.file_lock = None

    def start(self):
        # A second web process must not reset or steal an in-flight task.
        self.file_lock = (self.service.private_dir / 'worker.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.file_lock.write(b'0')
                self.file_lock.flush()
                self.file_lock.seek(0)
                msvcrt.locking(self.file_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file_lock.close()
            raise RuntimeError('Another CV web worker is running for this private directory')
        with self.db.lock, self.db.conn:
            self.db.conn.execute("UPDATE cv_tasks SET status='INTERRUPTED',progress='Interrupted; retry explicitly' WHERE status='RUNNING'")
        self.thread = threading.Thread(target=self.run, name='cv-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        if self.file_lock:
            self.file_lock.close()

    def enqueue(self, operation, args):
        estimate = self.service.estimate(operation, args)
        with self.db.lock, self.db.conn:
            pending = rows(self.db, "SELECT id FROM cv_tasks WHERE operation=? AND args=? AND status IN ('QUEUED','RUNNING')",
                           (operation, encode(args)))
            if pending:
                return pending[0]['id']
            return self.db.conn.execute('INSERT INTO cv_tasks(operation,args,estimate) VALUES (?,?,?)',
                                        (operation, encode(args), encode(estimate))).lastrowid

    def retry(self, task_id):
        task = one(self.db, 'tasks', task_id)
        if task['status'] not in {'FAILED', 'INTERRUPTED'}:
            raise ValueError('Only failed or interrupted operations can be retried')
        return self.enqueue(task['operation'], json.loads(task['args']))

    def execute(self, task):
        def progress(message):
            with self.db.lock, self.db.conn:
                self.db.conn.execute('UPDATE cv_tasks SET progress=? WHERE id=?', (message, task['id']))
        try:
            self.service.ai.reset_run()
            progress('Running; waiting for validated response')
            args = json.loads(task['args'])
            if task['operation'] == 'analyze':
                result = {'profile_id': self.service.analyze(args['source_id'])}
            elif task['operation'] == 'generate':
                result = {'version_id': self.service.generate(args['category_id'], args.get('output_format', 'standard'))}
            elif task['operation'] == 'classify':
                result = self.service.classify(progress)
            else:
                raise ValueError('Unknown operation')
            with self.db.lock, self.db.conn:
                self.db.conn.execute("UPDATE cv_tasks SET status='COMPLETED',progress='Complete',result=? WHERE id=?",
                                     (encode(result), task['id']))
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else type(exc).__name__
            with self.db.lock, self.db.conn:
                self.db.conn.execute("UPDATE cv_tasks SET status='FAILED',progress='Failed; review and retry',error=? WHERE id=?",
                                     (message[:500], task['id']))

    def run(self):
        while not self.stop_event.is_set():
            with self.db.lock, self.db.conn:
                pending = rows(self.db, "SELECT * FROM cv_tasks WHERE status='QUEUED' ORDER BY id LIMIT 1")
                if pending:
                    self.db.conn.execute("UPDATE cv_tasks SET status='RUNNING' WHERE id=?", (pending[0]['id'],))
            if pending:
                self.execute(pending[0])
            else:
                self.stop_event.wait(.25)
