import copy
import io
import tempfile
import unittest
import sys
from unittest.mock import patch
from pathlib import Path

from src.ai_filter import AIFilter
from src.cv import CVService, categories, extract_cv, one, save_source, source_facts
from src.cv_documents import render_version
from src.cv_latex import bind_facts, extract_latex, latex_slots, tailor_latex
from src.database import JobDatabase
from test_cv import FakeProvider, SOURCE


LATEX = r'''\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=2cm]{geometry}
\newcommand{\resumeItem}[1]{\item #1}
% The original layout and comments must survive.
\begin{document}
\begin{center}\textbf{Élise Example}\end{center}
elise@example.test
\section*{Expérience}
\textbf{Acme} \hfill 2022--2024
\begin{itemize}
\resumeItem{Développement de services Python pour les équipes et maintenance des outils de production.}
\item R\&D et caf\'e
\end{itemize}
\section*{Formation}
Master informatique
\end{document}
'''
PROSE = 'Développement de services Python pour les équipes et maintenance des outils de production.'
REWRITE = 'Maintenance des outils de production et développement de services Python pour les équipes.'


class LatexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = JobDatabase(':memory:')
        self.addCleanup(self.db.close)
        self.provider = FakeProvider()
        self.service = CVService(self.db, AIFilter({'max_retries': 0}, self.db, self.provider.client), self.temp.name)

    def prepared(self):
        imported = self.service.import_file('original.tex', LATEX.encode())
        sid = save_source(self.db, imported['filename'], imported['text'], imported['contacts'], imported['latex_source'])
        pid = self.service.analyze(sid)
        category = categories(self.db)[0]
        cid = self.service.save_categories(pid, [{**category['data'], 'id': category['id'], 'approved': True}])[0]
        return sid, cid, self.service.generate(cid)

    def test_missing_parser_reports_environment_fix_not_invalid_document(self):
        with patch.dict(sys.modules, {'pylatexenc.latexwalker': None}):
            with self.assertRaisesRegex(ValueError, 'pylatexenc dependency') as caught:
                extract_cv('valid.tex', LATEX.encode())
        self.assertIn('python -m pip install -r requirements.txt', str(caught.exception))
        self.assertIn('same Python environment', str(caught.exception))

    def test_standalone_output_requested_cached_and_updated_with_edits(self):
        sid = save_source(self.db, 'cv.docx', SOURCE, 'Name & Contact\nprivate@example.test')
        pid = self.service.analyze(sid)
        category = categories(self.db)[0]
        cid = self.service.save_categories(pid, [{**category['data'], 'id': category['id'], 'approved': True}])[0]
        standard = self.service.generate(cid)
        self.assertNotIn('latex_source', one(self.db, 'versions', standard)['data'])
        self.assertFalse(self.service.estimate('generate', {'category_id': cid, 'output_format': 'latex'})['cached'])
        latex = self.service.generate(cid, 'latex')
        self.assertNotEqual(standard, latex)
        self.assertIn('Output format: standalone LaTeX', self.provider.calls[-1]['messages'][0]['content'])
        self.assertNotIn('private@example.test', str(self.provider.calls))
        output = render_version(self.service, latex, 'tex').read_text(encoding='utf-8')
        self.assertIn(r'\documentclass[11pt,a4paper]{article}', output)
        self.assertIn(r'Name \& Contact', output)
        self.assertIn('private@example.test', output)
        self.assertNotIn('Préciser les projets', output)
        self.assertEqual(self.service.generate(cid, 'latex'), latex)
        self.assertTrue(self.service.estimate('generate', {'category_id': cid, 'output_format': 'latex'})['cached'])
        self.service.approve(latex, True)
        data = one(self.db, 'versions', latex)['data']
        data['title'] = r'CV & Python_\input{test}'
        data['latex_source'] = r'\input{/private-file}'
        edited = self.service.edit_version(latex, data)
        text = render_version(self.service, edited, 'tex').read_text(encoding='utf-8')
        self.assertIn(r'CV \& Python\_\textbackslash{}input\{test\}', text)
        self.assertNotIn('/private-file', text)
        self.assertEqual(render_version(self.service, latex, 'tex').read_text(encoding='utf-8'), output)
        self.assertEqual(len(self.provider.calls), 3)

    def test_invalid_standalone_layout_is_rejected(self):
        from src.cv_latex import standalone_latex
        for layout in (None, {}, {'font_size': True, 'margin_mm': 18},
                       {'font_size': 11, 'margin_mm': 0}, {'font_size': 11, 'margin_mm': '18'}):
            with self.assertRaises(ValueError):
                standalone_latex({}, '', layout)
        with self.assertRaises(ValueError):
            self.service.generation_prompt({'latex_source': None}, 'unknown')

    def test_extracts_macros_accents_and_dates_without_executing(self):
        text = extract_cv('cv.tex', LATEX.encode())
        self.assertIn('R&D et café', text)
        self.assertIn('2022–2024', text)
        self.assertIn(PROSE, text)
        self.assertNotIn('geometry', text)
        self.assertNotIn('original layout', text)
        # An input path is never followed, even when it points at a readable private file.
        secret = Path(self.temp.name) / 'secret.tex'
        secret.write_text('DO NOT READ THIS', encoding='utf-8')
        altered = LATEX.replace(r'\end{document}', '\\input{' + str(secret) + '}\n\\end{document}')
        self.assertNotIn('DO NOT READ THIS', extract_latex(altered))
        for data in (b'\xff', b'plain text without a document', b'\\begin{document}{unclosed\\end{document}'):
            with self.assertRaises(ValueError):
                extract_cv('broken.tex', data)

    def test_preserves_template_and_exports_tailored_revision(self):
        sid, cid, vid = self.prepared()
        source = one(self.db, 'sources', sid)
        version = one(self.db, 'versions', vid)['data']
        self.assertEqual(version['latex_source'], LATEX)
        self.assertEqual(render_version(self.service, vid, 'tex').read_text(encoding='utf-8'), LATEX)
        self.service.approve(vid, True)
        edited = copy.deepcopy(version)
        for section in edited['sections']:
            for item in section['items']:
                if item['text'] == PROSE:
                    item['text'] = REWRITE
        new_id = self.service.edit_version(vid, edited)
        new_tex = render_version(self.service, new_id, 'tex').read_text(encoding='utf-8')
        self.assertEqual(new_tex, LATEX.replace(PROSE, REWRITE))
        self.assertEqual(one(self.db, 'versions', vid)['data']['latex_source'], LATEX)
        self.assertEqual(len(latex_slots(new_tex)), len(latex_slots(LATEX)))
        self.assertTrue(self.service.estimate('generate', {'category_id': cid})['cached'])
        payloads = str(self.provider.calls)
        self.assertNotIn('elise@example.test', payloads)
        self.assertNotIn('documentclass', payloads)
        self.assertNotIn('geometry', payloads)

    def test_rejects_layout_changes_missing_facts_and_mutated_short_fields(self):
        sid, _, vid = self.prepared()
        data = one(self.db, 'versions', vid)['data']
        bad = copy.deepcopy(data)
        bad['sections'][0]['items'].pop()
        with self.assertRaises(ValueError):
            self.service.edit_version(vid, bad)
        bad = copy.deepcopy(data)
        bad['sections'][0]['items'][0]['text'] = 'Someone Else'
        with self.assertRaises(ValueError):
            self.service.edit_version(vid, bad)
        source = one(self.db, 'sources', sid)
        source['text'] = source['text'].replace('Acme', 'Another employer')
        with self.assertRaisesRegex(ValueError, 'LaTeX source'):
            bind_facts(source)

    def test_latex_escapes_generated_prose_and_ignores_injected_template(self):
        sid, _, vid = self.prepared()
        data = one(self.db, 'versions', vid)['data']
        data['latex_source'] = r'\input{/etc/passwd}'
        for item in data['sections'][0]['items']:
            if item['text'] == PROSE:
                item['text'] = 'Production & Python : ' + r'\input{unwanted}'
        new_id = self.service.edit_version(vid, data)
        text = render_version(self.service, new_id, 'tex').read_text(encoding='utf-8')
        self.assertIn(r'Production \& Python : \textbackslash{}input\{unwanted\}', text)
        self.assertNotIn('/etc/passwd', text)
        self.assertTrue(text.startswith(r'\documentclass'))

    def test_template_only_change_creates_new_source_revision(self):
        imported = self.service.import_file('original.tex', LATEX.encode())
        args = (imported['filename'], imported['text'], imported['contacts'])
        first = save_source(self.db, *args, LATEX)
        self.assertEqual(save_source(self.db, *args, LATEX), first)
        second = save_source(self.db, *args, LATEX.replace('margin=2cm', 'margin=3cm'))
        self.assertNotEqual(first, second)

    def test_tex_web_import_edit_extract_and_download(self):
        from bs4 import BeautifulSoup
        from fastapi.testclient import TestClient
        from web import create_app
        app = create_app(Path(self.temp.name) / 'web.db', Path(self.temp.name) / 'web-private',
                         {'max_retries': 0}, self.provider.client)
        with TestClient(app, base_url='http://127.0.0.1') as client:
            token = BeautifulSoup(client.get('/').text, 'html.parser').find('meta', attrs={'name': 'csrf-token'})['content']
            headers = {'x-csrf-token': token}
            with patch.dict(sys.modules, {'pylatexenc.latexwalker': None}):
                unavailable = client.post('/api/import', files={'file': ('cv.tex', LATEX.encode())}, headers=headers)
            self.assertEqual(unavailable.status_code, 400)
            self.assertIn('pylatexenc dependency', unavailable.json()['error'])
            result = client.post('/api/import', files={'file': ('cv.tex', LATEX.encode())}, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            imported = result.json()
            self.assertEqual(imported['latex_source'], LATEX)
            sid = client.post('/api/source', json=imported, headers=headers).json()['source_id']
            download = client.get(f'/sources/{sid}/download/tex')
            self.assertEqual(download.text, LATEX)
            self.assertIn('attachment', download.headers['content-disposition'])
            corrected = LATEX.replace('Acme', 'Corrected employer')
            result = client.post('/api/latex/extract', json={'latex_source': corrected}, headers=headers)
            self.assertIn('Corrected employer', result.json()['text'])
            pid = app.state.service.analyze(sid)
            cat = categories(app.state.db)[0]
            cid = app.state.service.save_categories(pid, [{**cat['data'], 'id': cat['id'], 'approved': True}])[0]
            vid = app.state.service.generate(cid)
            self.assertEqual(client.get(f'/versions/{vid}/download/tex').text, LATEX)


if __name__ == '__main__':
    unittest.main()
