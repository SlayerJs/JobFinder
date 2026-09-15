"""Conservative extraction and validation; never truncate eligibility evidence."""
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def clean_description(text):
    lines, seen = [], set()
    for line in (text or '').splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if not line or line in seen:
            continue
        if line.casefold() in {'accepter tous les cookies', 'refuser tous les cookies', 'paramétrer les cookies', 'menu', 'faq'}:
            continue
        seen.add(line)
        lines.append(line)
    return '\n'.join(lines)


def invalid_reason(text):
    text = (text or '').casefold().replace('’', "'")
    for marker in ("l'offre que vous souhaitez afficher n'est plus disponible", 'offre introuvable', 'verify you are human', 'access denied', 'just a moment...'):
        if marker in text:
            return 'Unavailable or blocked listing'
    if len(text.strip()) < 150:
        return 'Missing or insufficient description'
    return None


def canonical_url(url):
    p = urlsplit(url)
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in {'trackingid', 'ref', 'trk'}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))


def fingerprint(job):
    # Exact normalized content plus title: avoids merging different jobs at unknown companies.
    payload = ' '.join((job.title + ' ' + clean_description(job.description)).casefold().split())
    return hashlib.sha256(payload.encode()).hexdigest()


def extract_description(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    def postings(value):
        if isinstance(value, list):
            for item in value:
                yield from postings(item)
        elif isinstance(value, dict):
            kind = value.get('@type', [])
            if kind == 'JobPosting' or isinstance(kind, list) and 'JobPosting' in kind:
                yield value
            yield from postings(value.get('@graph', []))
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            for item in postings(json.loads(script.string or script.get_text())):
                desc = item.get('description')
                if isinstance(desc, str) and len(desc) >= 150:
                    parts = [BeautifulSoup(desc, 'html.parser').get_text('\n')]
                    for key in ('employmentType', 'jobLocation', 'hiringOrganization', 'baseSalary', 'jobStartDate', 'applicantLocationRequirements'):
                        if item.get(key):
                            parts.append(f'{key}: {json.dumps(item[key], ensure_ascii=False)}')
                    return clean_description('\n'.join(parts))
        except (ValueError, TypeError):
            continue
    for node in soup.select('script, style, nav, footer, header, [role="dialog"]'):
        node.decompose()
    node = soup.select_one("section[data-tw-component='job-description'], [itemprop='description'], .description-offre, main, [role='main']")
    return clean_description((node or soup).get_text('\n'))
