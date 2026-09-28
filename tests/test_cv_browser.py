"""Opt-in Chromium workflow. JOBFINDER_BROWSER_TEST=1 enables it; all API calls are mocked."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_cv import FakeProvider, docx_fixture


@unittest.skipUnless(os.getenv('JOBFINDER_BROWSER_TEST') == '1', 'Set JOBFINDER_BROWSER_TEST=1 and install Chromium')
class BrowserWorkflowTests(unittest.TestCase):
    def test_import_analyze_generate_approve_match_and_edit(self):
        import uvicorn
        from playwright.sync_api import sync_playwright, expect
        from src.database import JobDatabase
        from src.models import JobPosting
        from web import create_app
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / 'jobs.db'
            db = JobDatabase(db_path)
            job = JobPosting('browser-job', 'Python engineer', 'Example', 'Paris', 'https://example.test/job',
                             'Python software development in France. ' * 20, 'fixture')
            db.add_job(job)
            db.update_job_status(job.id, 'APPROVED', 'Previously approved', '2')
            db.notification_sent(job.id)
            db.close()
            provider = FakeProvider()
            app = create_app(db_path, Path(temp) / 'private', {'max_retries': 0}, provider.client)
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(server.started)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{port}')
                    page.locator('input[type=file]').set_input_files({'name': 'cv.docx', 'mimeType':
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'buffer': docx_fixture()})
                    page.get_by_role('button', name='Extract text', exact=True).click()
                    expect(page.locator('#message')).to_contain_text('Text extracted')
                    self.assertIn('Compétences | Python', page.locator('textarea[name=text]').input_value())
                    page.locator('textarea[name=contacts]').fill('Élise Example\nelise@example.test')
                    page.get_by_role('button', name='Save source revision', exact=True).click()
                    def operation(button_name):
                        page.get_by_role('button', name=button_name, exact=True).click()
                        expect(page.locator('#estimate-dialog')).to_be_visible()
                        expect(page.locator('#estimate-content')).to_contain_text('estimated_input_tokens')
                        page.get_by_role('button', name='Start operation', exact=True).click()
                    operation('Estimate profile analysis')
                    expect(page.get_by_role('heading', name='2. Review profile and application categories')).to_be_visible(timeout=15000)
                    category_form = page.locator('form[data-url^="/api/categories/"]')
                    category_form.get_by_label('Approve this category').check()
                    category_form.get_by_role('button', name='Save category review').click()
                    page.get_by_label('Output formats', exact=True).select_option('latex')
                    operation('Estimate CV generation')
                    revision = page.locator('a[href^="/versions/"]').first
                    expect(revision).to_be_visible(timeout=15000)
                    revision.click()
                    expect(page.get_by_text('Draft: not recommendable', exact=True)).to_be_visible()
                    for name in ['Download DOCX', 'Download PDF', 'Download LaTeX']:
                        with page.expect_download() as info:
                            page.get_by_role('link', name=name).click()
                        download = info.value
                        self.assertIsNone(download.failure())
                    page.locator('input[name=reviewed]').check()
                    page.get_by_role('button', name='Approve for recommendations').click()
                    expect(page.get_by_text('Approved', exact=True)).to_be_visible()
                    page.get_by_role('link', name='Back to workspace').click()
                    operation('Estimate posting classification')
                    expect(page.locator('table').first).to_contain_text('cv-category-', timeout=15000)
                    page.screenshot(path='/tmp/jobfinder-cv-workspace.png', full_page=True)
                    page.locator('a[href^="/versions/"]').first.click()
                    edit_form = page.locator('.json-form')
                    edit_form.get_by_label('CV title', exact=True).fill('CV révisé')
                    edit_form.get_by_role('button', name='Save new draft').click()
                    expect(page.get_by_text('Draft: not recommendable', exact=True)).to_be_visible()
                    # Filtering operates through shareable URLs and survives a reload.
                    page.get_by_role('link', name='Back to workspace').click()
                    filters = page.locator('#posting-filters')
                    filters.get_by_label('Search postings').fill('no such role')
                    filters.get_by_role('button', name='Apply filters').click()
                    expect(page.get_by_role('heading', name='No postings match these filters')).to_be_visible()
                    filters.get_by_label('Search postings').fill('Python')
                    filters.get_by_label('Eligibility', exact=True).select_option('APPROVED')
                    filters.get_by_label('Sort by').select_option('company')
                    filters.get_by_role('button', name='Apply filters').click()
                    expect(page.locator('#postings-table')).to_contain_text('Python engineer')
                    self.assertIn('sort=company', page.url)
                    page.reload()
                    expect(filters.get_by_label('Search postings')).to_have_value('Python')
                    # Import and generate from a real LaTeX fixture through the same UI.
                    from test_latex import LATEX
                    page.locator('input[type=file]').set_input_files({'name': 'cv.tex', 'mimeType': 'application/x-tex', 'buffer': LATEX.encode()})
                    page.get_by_role('button', name='Extract text', exact=True).click()
                    expect(page.locator('#message')).to_contain_text('LaTeX template is preserved')
                    expect(page.locator('#latex-source-editor')).to_be_visible()
                    page.get_by_role('button', name='Save source revision', exact=True).click()
                    operation('Estimate profile analysis')
                    expect(page.get_by_role('heading', name='2. Review profile and application categories')).to_be_visible(timeout=15000)
                    category_form = page.locator('form[data-url^="/api/categories/"]')
                    category_form.get_by_label('Approve this category').check()
                    category_form.get_by_role('button', name='Save category review').click()
                    operation('Estimate CV generation')
                    expect(page.locator('.version-card').first).to_contain_text('Draft', timeout=15000)
                    page.locator('.version-card h3 a').first.click()
                    with page.expect_download() as info:
                        page.get_by_role('link', name='Download LaTeX', exact=True).click()
                    self.assertEqual(Path(info.value.path()).read_text(encoding='utf-8'), LATEX)
                    page.get_by_role('link', name='Back to workspace').click()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.screenshot(path='/tmp/jobfinder-mobile.png', full_page=True)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.should_exit = True
                thread.join(timeout=15)
                listener.close()


if __name__ == '__main__':
    unittest.main()
