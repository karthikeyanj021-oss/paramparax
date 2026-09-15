"""Lightweight document ingestion + keyword search for the project concept document.

Usage (from Flask app):
    from doc_kb import doc_search, doc_section, doc_sections
"""

import os
import re
import math
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_DOC_PATH = os.path.join(
    _HERE,
    'AI_Heritage_Resource_Innovation_Discovery_Project_Document.txt',
)

_STOP = frozenset(
    'a an the and or but in on at to for of is it its '
    'this that with by from as are was were be been being '
    'have has had do does did will would shall should can '
    'could may might must not no yes also so very just '
    'what which who whom whose when where why how '
    'about about into over after before than then else '
    'please tell explain give me'.split()
)


def _stem(w):
    """Tiny morphology-aware stemmer for matching variants."""
    if len(w) <= 4:
        return w
    if w.endswith('ies'):
        return w[:-3] + 'y'
    if w.endswith('ing'):
        b = w[:-3]
        if len(b) >= 3 and b[-1] == b[-2]:
            b = b[:-1]
        return b
    if w.endswith('ed'):
        b = w[:-2]
        if len(b) >= 3 and b[-1] == b[-2]:
            b = b[:-1]
        return b
    if w.endswith('es'):
        return w[:-2]
    if w.endswith('s') and not w.endswith('ss'):
        return w[:-1]
    return w

# ── parse sections ──────────────────────────────────────────────────────────

_heading_re = re.compile(r'^(\d{1,2})\.\s+(.+)$')


def _parse_sections():
    raw = open(_DOC_PATH, encoding='utf-8', errors='replace').read()
    lines = raw.splitlines()
    sections: list[dict] = []
    cur: dict | None = None
    prev_blank = True  # treat file start as preceding blank

    for line in lines:
        m = _heading_re.match(line)
        # real section headings are short and never contain a colon
        is_heading = bool(
            m and prev_blank and ':' not in m.group(2)
        )
        if is_heading:
            if cur is not None:
                sections.append(cur)
            cur = {
                'id': int(m.group(1)),
                'heading': m.group(2).strip(),
                'lines': [],
            }
        elif cur is not None:
            cur['lines'].append(line)
        prev_blank = (line.strip() == '')

    if cur is not None:
        sections.append(cur)

    # finalise
    for s in sections:
        s['body'] = '\n'.join(s['lines']).strip()
        del s['lines']
        text = (s['heading'] + ' ' + s['body']).lower()
        words = [w for w in re.split(r'[^a-z0-9]+', text) if len(w) > 2 and w not in _STOP]
        s['tokens'] = words
        s['stem_set'] = frozenset(_stem(w) for w in words)
        s['heading_words'] = frozenset(
            w for w in re.split(r'[^a-z0-9]+', s['heading'].lower())
            if len(w) > 2 and w not in _STOP
        )
        s['heading_stems'] = frozenset(_stem(w) for w in s['heading_words'])
    return sections


_SECTIONS = _parse_sections()
_ID_MAP = {s['id']: s for s in _SECTIONS}


def doc_sections():
    """Return list of {id, heading} dicts."""
    return [{'id': s['id'], 'heading': s['heading']} for s in _SECTIONS]


def doc_section(sid: int) -> dict | None:
    """Return full section by id, or None."""
    s = _ID_MAP.get(sid)
    return dict(s) if s else None


def doc_search(query: str, top_n: int = 3) -> list[dict]:
    """Token-overlap search; returns list of {section, score} dicts."""
    q_words = [
        w
        for w in re.split(r'[^a-z0-9]+', query.lower())
        if len(w) > 2 and w not in _STOP
    ]
    if not q_words:
        return []
    q_stems = frozenset(_stem(w) for w in q_words)
    results = []
    for s in _SECTIONS:
        overlap = q_stems & s['stem_set']
        if not overlap:
            continue
        score = 0.0
        for w in q_words:
            st = _stem(w)
            if st in s['heading_stems']:
                score += 3.0
            elif st in s['stem_set']:
                score += 1.0
        if query.lower() in (s['heading'] + ' ' + s['body']).lower():
            score += 6.0
        if score > 0:
            s_out = dict(s)
            s_out.pop('tokens', None)
            results.append({'section': s_out, 'score': round(score, 2)})
    results.sort(key=lambda r: r['score'], reverse=True)
    return results[:top_n]


if __name__ == '__main__':
    for s in _SECTIONS:
        print(f"§{s['id']:2d}  {s['heading']}  ({len(s['body'])} chars)")
