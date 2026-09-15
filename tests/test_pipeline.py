import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
from src.ai_filter import AIFilter
from src.content import extract_description, invalid_reason
from src.database import JobDatabase
from src.models import JobPosting


def job(i='1', description=None):
    return JobPosting(i,'Stage cloud','Acme','France','https://example.com/'+i,description or ('Stage cloud security en France. '*20),'Test')


def result(i='1', tier=4):
    return {'id':i,'decision':'APPROVED','tier':tier,'reason_code':'MATCH','reason':'Matches criteria','evidence':'Stage cloud security en France.'}


class PipelineTests(unittest.TestCase):
    def test_invalid_page(self):
        self.assertIsNotNone(invalid_reason("L’offre que vous souhaitez afficher n’est plus disponible"))

    def test_structured_extraction(self):
        desc = 'Internship with security work. '*20
        html = '<nav>Noise</nav><script type="application/ld+json">'+json.dumps({'@type':'JobPosting','description':desc,'employmentType':'INTERN'})+'</script>'
        text = extract_description(html)
        self.assertIn('INTERN',text)
        self.assertNotIn('Noise',text)

    def test_strict_results(self):
        self.assertEqual(AIFilter.validate(json.dumps({'results':[result()]}),[job()])['1']['tier'],4)
        self.assertEqual(AIFilter.validate(json.dumps({'results':[result(tier=True)]}),[job()]),{})
        with self.assertRaises(ValueError):
            AIFilter.validate(json.dumps({'results':[result(),result()]}),[job()])
        with self.assertRaises(ValueError):
            AIFilter.validate('APPROVED: YES',[job()])
        bad = result(); bad['evidence'] = 'invented quotation'
        self.assertEqual(AIFilter.validate(json.dumps({'results':[bad]}),[job()]),{})

    def test_batch_limits(self):
        ai = AIFilter({'batch_input_tokens':3000,'max_jobs_per_batch':2})
        batches, oversized = ai.plan([job('1'),job('2'),job('3'),job('4','x'*9000)],'rules')
        self.assertEqual(len(oversized),1)
        self.assertEqual(sum(map(len,batches)),3)
        self.assertTrue(all(len(b)<=2 for b in batches))

    def test_missing_only_retry_and_usage(self):
        calls=[]
        def create(**kw):
            ids=[r['id'] for r in json.loads(kw['messages'][1]['content'])]
            calls.append(ids)
            rows=[result(ids[0])]
            return NS(usage=NS(prompt_tokens=100,completion_tokens=40,prompt_cache_hit_tokens=20,prompt_cache_miss_tokens=80),choices=[NS(finish_reason='stop',message=NS(content=json.dumps({'results':rows})))])
        db=JobDatabase(':memory:')
        ai=AIFilter({'max_retries':1},db,NS(chat=NS(completions=NS(create=create))))
        self.assertEqual(set(ai.evaluate_batch([job('1'),job('2')],'rules')),{'1','2'})
        self.assertEqual(calls,[['1','2'],['2']])
        self.assertEqual(ai.input_used,200)
        self.assertEqual(db.conn.execute('SELECT count(*) FROM api_usage').fetchone()[0],2)
        db.close()

    def test_budget_prevents_call(self):
        ai=AIFilter({'run_input_tokens':1},client=object())
        self.assertEqual(ai.evaluate_batch([job()],'rules'),{})

    def test_database_concurrency_dedup_and_notifications(self):
        db=JobDatabase(':memory:')
        with ThreadPoolExecutor(max_workers=5) as pool:
            statuses=list(pool.map(db.add_job,[job(str(i)) for i in range(20)]))
        self.assertEqual(statuses.count('PENDING'),1)
        self.assertEqual(statuses.count('DUPLICATE'),19)
        pending=db.get_pending_jobs()[0]
        db.update_job_status(pending.id,'APPROVED','match','4','v1')
        self.assertEqual(len(db.pending_notifications()),1)
        db.notification_sent(pending.id)
        db.update_job_status(pending.id,'APPROVED','match','4','v2')
        self.assertEqual(len(db.pending_notifications()),0)
        db.close()

    def test_failed_request_reserves_budget(self):
        def create(**kw):
            raise TimeoutError('offline')
        db = JobDatabase(':memory:')
        ai = AIFilter({'max_retries':0}, db, NS(chat=NS(completions=NS(create=create))))
        self.assertEqual(ai.evaluate_batch([job()], 'rules'), {})
        row = db.conn.execute('SELECT * FROM api_usage').fetchone()
        self.assertEqual(row['estimated'], 1)
        self.assertGreater(row['input_tokens'], 0)
        self.assertEqual(row['output_tokens'], ai.output_budget([job()]))
        db.close()

    def test_refetch_repairs_invalid_without_losing_notes(self):
        db = JobDatabase(':memory:')
        db.add_job(job(description='Access denied'))
        db.conn.execute("UPDATE jobs SET notes='keep me'")
        self.assertEqual(db.add_job(job()), 'PENDING')
        self.assertEqual(db.conn.execute('SELECT notes FROM jobs').fetchone()[0], 'keep me')
        db.close()

    def test_bad_config_fails_early(self):
        for config in ({'run_input_tokens':-1},{'max_retries':-1},{'max_jobs_per_batch':True}):
            with self.assertRaises(ValueError):
                AIFilter(config)

    def test_audit_preserves_decision(self):
        db=JobDatabase(':memory:')
        j=job(description="L'offre que vous souhaitez afficher n'est plus disponible")
        db.add_job(j)
        db.update_job_status(j.id,'REJECTED','old decision')
        self.assertEqual(db.audit()['invalid'],1)
        self.assertEqual(db.conn.execute('SELECT status FROM jobs').fetchone()[0],'INVALID')
        self.assertTrue(db.conn.execute("SELECT 1 FROM evaluations WHERE reason='old decision'").fetchone())
        self.assertFalse(db.is_job_seen(j.id))
        db.close()

if __name__ == '__main__':
    unittest.main()
