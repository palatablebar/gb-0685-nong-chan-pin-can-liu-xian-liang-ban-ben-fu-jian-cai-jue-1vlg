"""Merge supplemental reports (补录) into a base intake state.

The supplemental document is a normal report CSV.  It is parsed and normalised
with the same M1/M2 rules, then merged into the base rows *before* the version
selection, so a supplemental report can re-file a sample under another batch
without ever being counted twice.

Merge rules
-----------
* Rows are tagged with ``_source`` (base/supplement) and a stable source line,
  so every later verdict and quarantine still points at its origin.
* A supplement row with the same ``(id, version)`` and identical content as an
  existing row is a duplicate, not a second result: it is counted once and
  marked as a duplicate.
* A supplement row with the same ``(id, version)`` but different content is an
  irreconcilable re-statement.  The whole revision is rejected (the caller keeps
  the previous result) instead of silently overwriting evidence.
* Input/blank/header/duplicate counters are summed, so M6 row accounting keeps
  covering both documents.
"""
import hashlib
import unicodedata
from decimal import Decimal, InvalidOperation

from app.errors import DomainError
from app.modules.m1_ingest.reader import read
from app.modules.m2_mapping.rules import normalize

LINE_SPAN = 100000
NUMERIC_FIELDS = {'version', 'lod', 'result'}


def _canon(field, value):
    if field in NUMERIC_FIELDS or isinstance(value, Decimal):
        text = unicodedata.normalize('NFKC', str(value)).strip().replace(',', '')
        try:
            return format(Decimal(text).normalize(), 'f')
        except InvalidOperation:
            return text
    return str(value).strip()


def _signature(row):
    return tuple(sorted((key, _canon(key, value)) for key, value in row.items() if not key.startswith('_')))


def _key(row):
    return (str(row.get('id', '')), _canon('version', row.get('version', '1')))


def _tag_quarantine(items, source, offset, index):
    for item in items:
        item.setdefault('source', source)
        item.setdefault('source_line', item.get('line'))
        item['line'] = int(item.get('line') or 0) + offset
        item['revision_index'] = index


def merge(state, supplements):
    """Merge ``supplements`` (list of CSV text) into ``state`` in place."""
    if not supplements:
        return state
    if not isinstance(supplements, list) or not all(isinstance(item, str) for item in supplements):
        raise DomainError('PARAMETERS', '补录必须是文本列表')
    for row in state['rows']:
        row.setdefault('_source', 'base')
        row.setdefault('_source_line', row.get('_line'))
    _tag_quarantine(state['quarantine'], 'base', 0, -1)

    known = {}
    for row in state['rows']:
        known[_key(row)] = _signature(row)

    manifest=state.setdefault('supplement_manifest', [])
    for index, text in enumerate(supplements):
        data = text.encode('utf-8')
        if len(data) > 2_000_000:
            raise DomainError('SIZE', '补录文件超过2MB', 413)
        supplement = read(data)
        supplement = normalize(supplement)
        offset = (index + 1) * LINE_SPAN
        for row in supplement['rows']:
            row['_source'] = 'supplement'
            row['_source_line'] = row['_line']
            row['_revision_index'] = index
            row['_line'] = row['_line'] + offset
            if isinstance(row.get('_raw'), dict):
                row['_raw']['_line'] = row['_line']
        _tag_quarantine(supplement['quarantine'], 'supplement', offset, index)

        cross_duplicates = 0
        accepted = []
        for row in supplement['rows']:
            key = _key(row)
            signature = _signature(row)
            if key in known:
                if known[key] != signature:
                    raise DomainError('REVISION', '补录报告 %s 与既有报告同号同版但内容不一致' % key[0], 409)
                cross_duplicates += 1
                continue
            known[key] = signature
            accepted.append(row)

        state['rows'].extend(accepted)
        state['quarantine'].extend(supplement['quarantine'])
        state['input_count'] += supplement['input_count']
        state['blank_count'] += supplement['blank_count']
        state['header_count'] += supplement['header_count']
        state['duplicate_count'] += supplement['duplicate_count'] + cross_duplicates
        manifest.append({
            'index': index,
            'sha256': hashlib.sha256(data).hexdigest(),
            'encoding': supplement['encoding'],
            'rows': len(supplement['rows']),
            'accepted': len(accepted),
            'cross_duplicates': cross_duplicates,
            'quarantined': len(supplement['quarantine']),
        })
    state['supplemented']=True
    return state
