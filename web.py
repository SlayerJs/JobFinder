"""Run the private, single-user CV interface with python web.py."""
import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.ai_filter import AIFilter
from src.configuration import load_config
from src.cv import (CVService, active_source, categories, current_profile, digest,
                    one, recommendation, rows, save_source, source_facts)
from src.cv_documents import render_version
from src.cv_worker import CVWorker
from src.database import JobDatabase
from src.posting_list import posting_list

ROOT = Path(__file__).resolve().parent


def create_app(db_path='jobs.db', private_dir='private_cv', config=None, client=None):
    csrf_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        db = JobDatabase(db_path)
        app.state.db = db
        app.state.service = CVService(db, AIFilter(config if config is not None else load_config().get('ai', {}), db, client), private_dir)
        app.state.worker = CVWorker(app.state.service)
        try:
            app.state.worker.start()
            yield
        finally:
            await asyncio.to_thread(app.state.worker.stop)
            db.close()

    app = FastAPI(title='JobFinder CV workspace', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
    templates = Jinja2Templates(directory=ROOT / 'templates')

    @app.middleware('http')
    async def protect(request, call_next):
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            token = request.headers.get('x-csrf-token', '')
            origin = request.headers.get('origin')
            expected_origin = str(request.base_url).rstrip('/')
            if (not secrets.compare_digest(token, csrf_token) or
                (origin and origin != expected_origin) or
                request.headers.get('sec-fetch-site') == 'cross-site'):
                return JSONResponse({'error': 'Invalid local request token or origin'}, status_code=403)
        try:
            length = int(request.headers.get('content-length', '0') or 0)
        except ValueError:
            return JSONResponse({'error': 'Invalid content length'}, status_code=400)
        if length > 11 * 1024 * 1024:
            return JSONResponse({'error': 'Request exceeds 11 MB'}, status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=400)

    @app.get('/')
    def index(request: Request):
        db = request.app.state.db
        source = active_source(db)
        profile = current_profile(db)
        cats = categories(db)
        editable = [{**c['data'], 'id': c['id'], 'approved': bool(c['approved'])} for c in cats]
        versions = rows(db, '''SELECT v.*, c.data AS category_data, a.created_at AS approved_at
            FROM cv_versions v JOIN cv_categories c ON c.id=v.category_id
            LEFT JOIN cv_approvals a ON a.version_id=v.id ORDER BY v.id DESC''')
        for v in versions:
            v['category_name'] = json.loads(v['category_data'])['name']
        postings = posting_list(db, request.query_params)
        usage = rows(db, '''SELECT operation, SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,
            SUM(cost_usd) AS cost_usd FROM api_usage GROUP BY operation''')
        return templates.TemplateResponse(request=request, name='index.html', context={
            'token': csrf_token, 'source': source, 'profile': profile, 'cats': cats,
            'editable_categories': editable, 'versions': versions, 'jobs': postings['jobs'], 'postings': postings, 'usage': usage,
            'facts': source_facts(source) if source else [], 'tasks': rows(db, 'SELECT * FROM cv_tasks ORDER BY id DESC LIMIT 30')})

    @app.post('/api/import')
    async def upload(request: Request, file: UploadFile = File(...)):
        content = await file.read(10 * 1024 * 1024 + 1)
        return await asyncio.to_thread(request.app.state.service.import_file, file.filename or '', content)

    @app.post('/api/source')
    async def source(request: Request):
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get('filename', ''), str):
            raise ValueError('Invalid source document')
        return {'source_id': save_source(request.app.state.db, body.get('filename', 'corrected-cv'), body.get('text'), body.get('contacts', ''), body.get('latex_source'))}

    @app.post('/api/latex/extract')
    async def extract_latex_text(request: Request):
        from src.cv_latex import decode_latex, extract_latex
        from src.cv import split_contacts
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get('latex_source'), str):
            raise ValueError('Provide LaTeX source text')
        latex = decode_latex(body['latex_source'].encode('utf-8'))
        text = await asyncio.to_thread(extract_latex, latex)
        facts, contacts = split_contacts(text)
        return {'text': facts, 'contacts': contacts}

    @app.get('/sources/{source_id}/download/tex')
    def original_latex(request: Request, source_id: int):
        source = one(request.app.state.db, 'sources', source_id)
        if not source['latex_source']:
            raise ValueError('This source is not a LaTeX document')
        return Response(source['latex_source'], media_type='application/x-tex',
                        headers={'Content-Disposition': f'attachment; filename="cv-source-r{source_id}.tex"'})

    @app.post('/api/profile/{profile_id}')
    async def profile(request: Request, profile_id: int):
        return {'profile_id': request.app.state.service.edit_profile(profile_id, await request.json())}

    @app.post('/api/categories/{profile_id}')
    async def review_categories(request: Request, profile_id: int):
        return {'category_ids': request.app.state.service.save_categories(profile_id, await request.json())}

    def task_input(body):
        if not isinstance(body, dict) or body.get('operation') not in {'analyze', 'generate', 'classify'}:
            raise ValueError('Invalid operation')
        operation = body['operation']
        args = body.get('args', {})
        field = {'analyze': 'source_id', 'generate': 'category_id'}.get(operation)
        if not isinstance(args, dict) or set(args) != ({field} if field else set()) or (field and type(args[field]) is not int):
            raise ValueError('Invalid operation arguments')
        return operation, args

    def estimate_result(service, operation, args):
        estimate = service.estimate(operation, args)
        return {**estimate, 'estimate_key': digest([operation, args, estimate])}

    @app.post('/api/estimate')
    async def estimate(request: Request):
        operation, args = task_input(await request.json())
        return estimate_result(request.app.state.service, operation, args)

    @app.post('/api/tasks')
    async def enqueue(request: Request):
        body = await request.json()
        operation, args = task_input(body)
        current = estimate_result(request.app.state.service, operation, args)
        if body.get('estimate_key') != current['estimate_key']:
            raise ValueError('Review the current usage estimate before starting')
        return {'task_id': request.app.state.worker.enqueue(operation, args)}

    @app.get('/api/tasks')
    def tasks(request: Request):
        return rows(request.app.state.db, 'SELECT * FROM cv_tasks ORDER BY id DESC LIMIT 30')

    @app.get('/versions/{version_id}')
    def version(request: Request, version_id: int):
        db = request.app.state.db
        v = one(db, 'versions', version_id)
        category = one(db, 'categories', v['category_id'])
        profile = one(db, 'profiles', category['profile_id'])
        source = one(db, 'sources', profile['source_id'])
        return templates.TemplateResponse(request=request, name='version.html', context={
            'token': csrf_token, 'version': v, 'category': category, 'source': source,
            'fixed_fact_ids': [f['id'] for f in source_facts(source) if len(f['text']) <= 60],
            'facts': source_facts(source), 'approved': bool(rows(db, 'SELECT id FROM cv_approvals WHERE version_id=?', (version_id,)))})

    @app.post('/api/versions/{version_id}/edit')
    async def edit_version(request: Request, version_id: int):
        return {'version_id': request.app.state.service.edit_version(version_id, await request.json())}

    @app.post('/api/versions/{version_id}/approve')
    async def approve(request: Request, version_id: int):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Invalid approval')
        request.app.state.service.approve(version_id, body.get('reviewed'))
        return {'approved': True}

    @app.get('/versions/{version_id}/download/{extension}')
    def download(request: Request, version_id: int, extension: str):
        path = render_version(request.app.state.service, version_id, extension)
        media_types = {'pdf': 'application/pdf', 'tex': 'application/x-tex',
                       'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
        return FileResponse(path, filename=path.name, media_type=media_types[extension])

    return app


if __name__ == '__main__':
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv()
    uvicorn.run(create_app(), host='127.0.0.1', port=8000)
