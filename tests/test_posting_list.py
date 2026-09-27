import tempfile
import unittest
from pathlib import Path

from src.ai_filter import AIFilter
from src.cv import CVService, categories, save_source, store_match
from src.database import JobDatabase
from src.posting_list import posting_list
from test_cv import FakeProvider, SOURCE


class PostingListTests(unittest.TestCase):
    def setUp(self):
        self.db = JobDatabase(':memory:')
        self.addCleanup(self.db.close)
        with self.db.conn:
            for i in range(620):
                self.db.conn.execute('''INSERT INTO jobs(id,title,company,location,url,description,source,status,tier,date_added)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''', (str(i), f'Role {i:04d}', 'Acme' if i % 2 else 'Beta',
                    'Paris' if i % 2 else 'Berlin', 'https://example.test/' + str(i), 'fixture',
                    'Board A' if i % 2 else 'Board B', 'APPROVED' if i % 3 else 'REJECTED',
                    str(i % 4 + 1), f'2026-09-{i % 28 + 1:02d} 00:00:00'))

    def test_full_database_search_combined_filters_and_pagination(self):
        result = posting_list(self.db, {})
        self.assertEqual(result['total'], 620)
        self.assertEqual(len(result['jobs']), 25)
        self.assertEqual(result['pages'], 25)
        result = posting_list(self.db, {'q': 'Role 0001', 'status': 'APPROVED', 'source': 'Board A', 'tier': '2'})
        self.assertEqual([j['id'] for j in result['jobs']], ['1'])
        result = posting_list(self.db, {'q': 'pArIs', 'sort': 'title', 'page_size': '50', 'page': '2'})
        self.assertEqual(result['total'], 310)
        self.assertEqual(result['first'], 51)
        self.assertEqual(result['jobs'][0]['title'], 'Role 0101')
        self.assertIn('q=pArIs', result['next_url'])
        self.assertIn('sort=title', result['previous_url'])
        self.assertTrue(result['next_url'].endswith('#postings'))

    def test_stable_sorts_bad_parameters_and_safe_links(self):
        result = posting_list(self.db, {'sort': 'tier', 'page_size': '100'})
        self.assertTrue(all(job['tier'] == '1' for job in result['jobs']))
        self.assertEqual(posting_list(self.db, {'sort': 'company'})['jobs'][0]['company'], 'Acme')
        self.assertEqual(posting_list(self.db, {'sort': 'oldest'})['jobs'][0]['date_added'], '2026-09-01 00:00:00')
        self.assertEqual(posting_list(self.db, {'sort': 'newest'})['jobs'][0]['date_added'], '2026-09-28 00:00:00')
        result = posting_list(self.db, {'sort': 'title; DROP TABLE jobs', 'page_size': '90000', 'page': '-1'})
        self.assertEqual(result['filters']['sort'], 'newest')
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['filters']['page_size'], '25')
        self.assertEqual(posting_list(self.db, {'page': '9999'})['page'], 25)
        self.assertEqual(posting_list(self.db, {'q': "' OR 1=1 --"})['total'], 0)
        self.assertEqual(posting_list(self.db, {'q': '%'})['total'], 0)
        with self.db.conn:
            self.db.conn.execute("UPDATE jobs SET url='javascript:alert(1)' WHERE id='1'")
        self.assertEqual(posting_list(self.db, {'q': 'Role 0001'})['jobs'][0]['safe_url'], '')

    def test_category_and_readiness_filters_preserve_notifications(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            service = CVService(self.db, AIFilter({'max_retries': 0}, self.db, provider.client), temp)
            sid = save_source(self.db, 'cv.docx', SOURCE)
            pid = service.analyze(sid)
            c = categories(self.db)[0]
            cid = service.save_categories(pid, [{**c['data'], 'id': c['id'], 'approved': True}])[0]
            store_match(self.db, '1', {'category_id': cid, 'matching_reason': 'Fit'})
            result = posting_list(self.db, {'category': str(cid), 'cv': 'awaiting'})
            self.assertEqual([j['id'] for j in result['jobs']], ['1'])
            vid = service.generate(cid)
            service.approve(vid, True)
            self.assertEqual(posting_list(self.db, {'cv': 'ready'})['total'], 1)
            self.assertEqual(posting_list(self.db, {'cv': 'awaiting'})['total'], 0)
            save_source(self.db, 'cv.docx', SOURCE + '\nNew fact')
            self.assertEqual(posting_list(self.db, {'cv': 'stale'})['total'], 1)
            self.assertEqual(posting_list(self.db, {'cv': 'ready'})['total'], 0)
            self.assertEqual(len(self.db.pending_notifications()), 0)


if __name__ == '__main__':
    unittest.main()
