import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import main
from src.ai_filter import AIFilter
from src.database import JobDatabase
from src.models import JobPosting
from src.configuration import load_config
from pathlib import Path
from src.cv import CVService, categories, one, recommendation, save_source
from test_cv import FakeProvider, SOURCE


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.config_patch = patch.object(main, "USER_CONFIG", load_config(Path(__file__).resolve().parents[1] / "config.example.yaml"))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.db = JobDatabase(':memory:')
        self.jobs = [JobPosting(str(i),f'Stage {i}','Example','France',f'https://example.com/{i}',
                     (f'Stage cloud security project {i} in France. '*15),'Test') for i in range(3)]
        for job in self.jobs:
            self.db.add_job(job)

    def tearDown(self):
        self.db.close()

    def test_process_persists_decisions_and_report(self):
        ai = AIFilter({'batch_input_tokens':20000})
        ai.evaluate_batch = Mock(return_value={
            '0':{'decision':'APPROVED','tier':4,'reason_code':'MATCH','reason':'Suitable','evidence':'Stage cloud'},
            '1':{'decision':'REJECTED','tier':None,'reason_code':'CONTRACT','reason':'Wrong contract','evidence':'project 1'}})
        notifier = Mock()
        notifier.send_job_alert.return_value = True
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.multiple(main,db=self.db,ai=ai,notifier=notifier):
                    main.process_pending_jobs()
                states = {r['id']:r['status'] for r in self.db.conn.execute('SELECT id,status FROM jobs')}
                self.assertEqual(states,{'0':'APPROVED','1':'REJECTED','2':'PENDING'})
                notifier.send_job_alert.assert_called_once()
                notifier.send_run_summary.assert_called_once()
                report = notifier.send_run_summary.call_args.args[0]
                from openpyxl import load_workbook
                workbook = load_workbook(report)
                self.assertEqual(workbook.active.max_row,4)
                workbook.close()
                self.assertEqual(len(self.db.pending_notifications()),0)
            finally:
                os.chdir(old_cwd)

    def test_dry_run_has_no_external_calls_or_status_changes(self):
        ai = AIFilter()
        ai.evaluate_batch = Mock(side_effect=AssertionError('API forbidden'))
        notifier = Mock()
        with patch.multiple(main,db=self.db,ai=ai,notifier=notifier), contextlib.redirect_stdout(io.StringIO()) as output:
            main.process_pending_jobs(dry_run=True)
        self.assertIn('estimated_input_tokens',output.getvalue())
        self.assertEqual(len(self.db.get_pending_jobs()),3)
        ai.evaluate_batch.assert_not_called()
        self.assertFalse(notifier.mock_calls)

    def test_cv_recommendation_reaches_excel_and_discord(self):
        provider = FakeProvider()
        ai = AIFilter({'max_retries': 0}, self.db, provider.client)
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            service = CVService(self.db, ai, Path(directory) / 'private')
            sid = save_source(self.db, 'fixture.docx', SOURCE)
            pid = service.analyze(sid)
            category = categories(self.db)[0]
            cid = service.save_categories(pid, [{**category['data'], 'id': category['id'], 'approved': True}])[0]
            vid = service.generate(cid)
            service.approve(vid, True)
            ai.evaluate_batch = Mock(return_value={
                '0': {'decision': 'APPROVED', 'tier': 2, 'reason_code': 'MATCH', 'reason': 'Suitable',
                      'evidence': 'Stage cloud', 'category_id': cid, 'matching_reason': 'Software experience'},
                '1': {'decision': 'APPROVED', 'tier': 3, 'reason_code': 'MATCH', 'reason': 'Suitable',
                      'evidence': 'Stage cloud', 'category_id': 99999, 'matching_reason': 'Invalid fixture category'}})
            notifier = Mock()
            notifier.send_job_alert.return_value = True
            try:
                os.chdir(directory)
                with patch.multiple(main, db=self.db, ai=ai, notifier=notifier):
                    main.process_pending_jobs()
                self.assertEqual(recommendation(self.db, '0')['version_id'], vid)
                self.assertEqual(self.db.conn.execute("SELECT status FROM jobs WHERE id='1'").fetchone()[0], 'APPROVED')
                alert = notifier.send_job_alert.call_args_list[0].args[3]
                self.assertIn(f'r{vid}.pdf', alert['cv'])
                from openpyxl import load_workbook
                workbook = load_workbook(notifier.send_run_summary.call_args.args[0])
                sheet = workbook.active
                self.assertEqual(sheet.cell(1, 9).value, 'Application category')
                self.assertEqual(sheet.cell(2, 10).value, alert['cv'])
                self.assertEqual(sheet.cell(2, 11).value, 'Software experience')
                workbook.close()
                # A separate matching retry repairs only the missing assignment.
                self.assertEqual(service.classify()['matched'], 1)
                self.assertEqual(len(self.db.pending_notifications()), 0)
            finally:
                os.chdir(old_cwd)
