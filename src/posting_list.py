"""Validated, database-wide filters and stable pagination for the local workspace."""
from urllib.parse import urlencode, urlsplit

from src.cv import match_key, recommendation, rows

SORTS = {'newest': 'date_added DESC', 'oldest': 'date_added ASC',
         'tier': "CASE WHEN tier IN ('1','2','3','4') THEN CAST(tier AS INTEGER) ELSE 99 END ASC",
         'title': 'title COLLATE NOCASE ASC', 'company': 'company COLLATE NOCASE ASC',
         'location': 'location COLLATE NOCASE ASC', 'category': 'category_name COLLATE NOCASE ASC'}
STATUSES = ('APPROVED', 'REVIEW', 'PENDING', 'REJECTED', 'INVALID', 'DUPLICATE')


def posting_list(db, params):
    filters = {k: str(params.get(k, '')).strip()[:200] for k in
               ('q', 'status', 'tier', 'source', 'category', 'cv', 'sort', 'page_size')}
    if filters['status'] not in STATUSES:
        filters['status'] = ''
    if filters['tier'] not in ('1', '2', '3', '4'):
        filters['tier'] = ''
    if filters['cv'] not in ('ready', 'awaiting', 'unassigned', 'stale'):
        filters['cv'] = ''
    if filters['sort'] not in SORTS:
        filters['sort'] = 'newest'
    if filters['page_size'] not in ('25', '50', '100'):
        filters['page_size'] = '25'
    size = int(filters['page_size'])
    try:
        page = max(1, int(params.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    # Match state is computed before LIMIT, so filters cover the entire database.
    base = '''WITH listed AS (
        SELECT j.*, c.id AS category_id, json_extract(c.data,'$.name') AS category_name,
        CASE WHEN j.status!='APPROVED' THEN 'unassigned'
             WHEN m.id IS NULL THEN 'unassigned'
             WHEN m.stale=1 OR m.context_key!=? OR c.stale=1 THEN 'stale'
             WHEN m.category_id IS NULL THEN 'unassigned'
             WHEN v.id IS NOT NULL AND v.stale=0 AND a.id IS NOT NULL THEN 'ready'
             ELSE 'awaiting' END AS cv_state
        FROM jobs j
        LEFT JOIN cv_matches m ON m.id=(SELECT MAX(id) FROM cv_matches WHERE job_id=j.id)
        LEFT JOIN cv_categories c ON c.id=m.category_id
        LEFT JOIN cv_versions v ON v.id=m.version_id
        LEFT JOIN cv_approvals a ON a.version_id=v.id
    ) '''
    clauses, args = [], [match_key(db)]
    if filters['q']:
        clauses.append("instr(lower(coalesce(title,'') || ' ' || coalesce(company,'') || ' ' || coalesce(location,'')),lower(?))>0")
        args.append(filters['q'])
    for key in ('status', 'tier', 'source'):
        if filters[key]:
            clauses.append(f'{key}=?')
            args.append(filters[key])
    if filters['category']:
        clauses.append("category_id=? AND cv_state IN ('ready','awaiting')")
        args.append(filters['category'])
    if filters['cv']:
        clauses.append('cv_state=?')
        args.append(filters['cv'])
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with db.lock:
        total = rows(db, base + 'SELECT COUNT(*) AS n FROM listed' + where, args)[0]['n']
        pages = max(1, (total + size - 1) // size)
        page = min(page, pages)
        jobs = rows(db, base + 'SELECT * FROM listed' + where +
                    f" ORDER BY {SORTS[filters['sort']]}, id ASC LIMIT ? OFFSET ?", args + [size, (page-1)*size])
        for job in jobs:
            job.update(recommendation(db, job['id']))
            try:
                job['safe_url'] = job['url'] if urlsplit(job['url'] or '').scheme.lower() in {'http', 'https'} else ''
            except ValueError:
                job['safe_url'] = ''
        stats = {r['status']: r['n'] for r in rows(db, 'SELECT status,COUNT(*) AS n FROM jobs GROUP BY status')}
        sources = [r['source'] for r in rows(db, 'SELECT DISTINCT source FROM jobs WHERE source IS NOT NULL ORDER BY source')]
    def page_url(number):
        return '/?' + urlencode({**{k: v for k, v in filters.items() if v}, 'page': number}) + '#postings'
    return {'jobs': jobs, 'filters': filters, 'total': total, 'page': page, 'pages': pages,
            'first': (page-1)*size+1 if total else 0, 'last': min(page*size, total),
            'previous_url': page_url(page-1) if page > 1 else None,
            'next_url': page_url(page+1) if page < pages else None,
            'sources': sources, 'statuses': STATUSES, 'stats': stats, 'all_jobs': sum(stats.values())}
