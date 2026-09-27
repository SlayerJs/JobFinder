"""Parse LaTeX without executing it; tailor text spans while preserving the template."""
import re

MAX_LATEX = 200000
LATEX_RULES = '''
This source is a LaTeX CV. Preserve its existing template and layout by editing text slots only.
Return exactly one CV item per supplied source fact, in source order, with exactly that single fact_id.
Do not merge, split, omit or reorder facts. Text fields of 60 characters or fewer are fixed labels,
names, dates or skills: copy them exactly. Rephrase longer prose for the category while preserving
all original numbers, employers, qualifications and facts. No extra summary or new CV claims.
Section headings in this JSON are for the review screen only; the original LaTeX headings remain.
Keep unsupported improvements in suggestions. The template and private contact fields stay local.
'''


def decode_latex(content):
    try:
        value = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Save your LaTeX file as UTF-8 before importing it') from exc
    if not value.strip() or len(value) > MAX_LATEX or '\x00' in value:
        raise ValueError('LaTeX source must contain 1–200,000 characters of UTF-8 text')
    return value


def latex_slots(source):
    """Return prose spans, leaving command syntax, whitespace and all other bytes intact.

    Unknown command arguments are traversed as groups, never expanded. Includes, packages,
    images and definitions are neither executed nor opened. Character escapes/accents stay
    together with their surrounding text; formatting command boundaries remain untouched.
    """
    try:
        from pylatexenc.latexwalker import LatexWalker, get_default_latex_context_db
        from pylatexenc.macrospec import MacroSpec
        from pylatexenc.latex2text import LatexNodes2Text
    except ImportError as exc:
        raise ValueError(
            'LaTeX support is unavailable: the pylatexenc dependency is missing or incompatible. '
            'In the same Python environment used to run web.py, run '
            'python -m pip install -r requirements.txt, then restart the web app. '
            'This is an environment issue, not an invalid document.'
        ) from exc
    source = decode_latex(source.encode('utf-8'))
    context = get_default_latex_context_db()
    definitions = re.findall(r'\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\\([A-Za-z@]+)\}?\s*(?:\[(\d)\])?(\s*\[[^\]]*\])?', source)
    custom = [MacroSpec(name, ('[' if optional else '') + '{' * max(0, int(count or 0)-bool(optional)))
              for name, count, optional in definitions]
    context.add_context_category('cv', macros=custom, prepend=True)
    converter = LatexNodes2Text()  # No input directory: \input and \include cannot read files.
    try:
        nodes, _, _ = LatexWalker(source, latex_context=context, tolerant_parsing=False).get_latex_nodes()
    except Exception as exc:
        raise ValueError('Unable to parse LaTeX; check balanced braces and document environments') from exc
    documents = [n for n in nodes if type(n).__name__ == 'LatexEnvironmentNode' and n.environmentname == 'document']
    if len(documents) != 1:
        raise ValueError('Use a complete .tex file with one \\begin{document} … \\end{document}')
    ignore = {'documentclass', 'usepackage', 'RequirePackage', 'newcommand', 'renewcommand', 'providecommand',
              'newenvironment', 'renewenvironment', 'def', 'let', 'input', 'include', 'includegraphics',
              'bibliography', 'bibliographystyle', 'label', 'ref', 'pageref', 'vspace', 'hspace', 'vskip', 'hskip',
              'setlength', 'addtolength', 'rule', 'cline', 'url', 'path', 'color', 'pagecolor', 'fontsize',
              'setmainfont', 'fontfamily', 'write', 'write18', 'openout', 'openin', 'read', 'directlua', 'special'}
    characters = {'&', '%', '$', '#', '_', '{', '}', 'textbackslash', 'textasciitilde', 'textasciicircum',
                  "'", '`', '"', '^', '~', '=', '.', 'c', 'v', 'u', 'H', 'r', 'k', 'b', 'd',
                  'LaTeX', 'TeX', 'ae', 'AE', 'oe', 'OE', 'ss', 'o', 'O', 'l', 'L', 'textendash', 'textemdash'}
    slots = []

    def add_run(run):
        if not run:
            return
        start, end = run[0].pos, run[-1].pos + run[-1].len
        raw = source[start:end]
        cursor = 0
        for split in re.finditer(r'\n[ \t]*\n|\Z', raw):
            piece = raw[cursor:split.start()]
            stripped = piece.strip()
            if stripped:
                offset = start + cursor + len(piece) - len(piece.lstrip())
                text = ' '.join(converter.latex_to_text(stripped).split())
                if text and any(c.isalnum() for c in text):
                    slots.append({'start': offset, 'end': offset+len(stripped), 'text': text})
            cursor = split.end()

    def visit(items):
        run = []
        for node in items or []:
            kind = type(node).__name__
            if (kind == 'LatexCharsNode' or (kind == 'LatexMacroNode' and node.macroname in characters)
                    or (kind == 'LatexSpecialsNode' and node.specials_chars in {'~', '--', '---', '``', "''"})):
                run.append(node)
                continue
            add_run(run)
            run = []
            if kind in {'LatexGroupNode', 'LatexEnvironmentNode'}:
                if kind == 'LatexEnvironmentNode' and node.environmentname in {'comment', 'verbatim', 'lstlisting', 'minted'}:
                    continue
                visit(node.nodelist)
            elif kind == 'LatexMacroNode' and node.macroname not in ignore:
                args = node.nodeargd.argnlist if node.nodeargd else []
                # URLs/color names are formatting, while link labels and colored text are prose.
                if node.macroname in {'href', 'textcolor', 'colorbox'}:
                    args = args[1:]
                for arg in args:
                    if arg is not None and hasattr(arg, 'nodelist'):
                        visit(arg.nodelist)
        add_run(run)

    try:
        visit(documents[0].nodelist)
    except (RecursionError, ValueError) as exc:
        raise ValueError('LaTeX is too deeply nested or malformed') from exc
    return sorted(slots, key=lambda item: item['start'])


def extract_latex(source):
    return '\n'.join(slot['text'] for slot in latex_slots(source))


def escape_latex(text):
    escapes = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '&': r'\&', '%': r'\%',
               '$': r'\$', '#': r'\#', '_': r'\_', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(escapes.get(char, char) for char in text)


def bind_facts(source):
    from src.cv import source_facts
    facts = source_facts(source)
    slots = latex_slots(source['latex_source'])
    contacts = set(line.strip() for line in source['contacts'].splitlines() if line.strip())
    remaining = list(facts)
    bound = []
    for slot in slots:
        index = next((i for i, f in enumerate(remaining) if f['text'] == slot['text']), None)
        if index is None:
            if slot['text'] not in contacts:
                raise ValueError('CV facts no longer match the LaTeX source. Edit the LaTeX source and extract its text again before generating.')
            continue
        fact = remaining.pop(index)
        bound.append({**slot, 'fact_id': fact['id']})
    if remaining:
        raise ValueError('Some facts are missing from the LaTeX template. Edit its source and extract text again.')
    return bound


def tailor_latex(source, data):
    slots = bind_facts(source)
    items = [item for section in data['sections'] for item in section['items']]
    if len(items) != len(slots) or any(item['fact_ids'] != [slot['fact_id']] for slot, item in zip(slots, items)):
        raise ValueError('LaTeX versions must preserve every text slot and its source reference in order')
    output = source['latex_source']
    for slot, item in reversed(list(zip(slots, items))):
        text = item['text']
        if len(slot['text']) <= 60 and text != slot['text']:
            raise ValueError('Short LaTeX fields such as names, dates and labels must remain unchanged')
        numbers = lambda value: re.findall(r'\d+(?:[.,]\d+)?', value)
        if numbers(text) != numbers(slot['text']):
            raise ValueError('LaTeX rewrites must preserve dates and metrics')
        if text != slot['text']:
            output = output[:slot['start']] + escape_latex(text) + output[slot['end']:]
    return {**data, 'latex_source': output}
