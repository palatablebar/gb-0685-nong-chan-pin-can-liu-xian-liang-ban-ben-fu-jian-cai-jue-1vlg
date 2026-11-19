"""Sample level batch attribution adjudication.

A sample belongs to exactly one batch.  A supplemental report (补录) may carry a
different batch because it corrects a split/labelling error.  The original
attribution must stay visible as evidence, while only the adjudicated batch may
be used for grading and counting.

Resolution rules
----------------
* The original attribution is the earliest report of the *base* document for the
  sample.  Supplemental rows are correction claims by definition, even when
  their own reported date looks earlier.
* A claim must keep sample identity (product and sampling date), be strictly
  newer than the original, and have a structurally valid relation chain.  The
  newest valid claim wins when the named batch is unique.
* Tied claims naming different batches, or base rows contradicting the original
  batch, are conflicts: the original attribution is kept unchanged (fail safe)
  so a batch that is close to issuance never flips by accident.  The offending
  rows stay as evidence and are quarantined.
* Given a resolved batch, old batch rows of an analyte explicitly re-reported in
  that batch are superseded evidence (visible, not counted); the remaining
  analytes follow the sample into its resolved batch.
* Nothing is deleted or overwritten; every row keeps its original batch, source
  and source line in the ledger.
"""
from collections import defaultdict
from decimal import Decimal

RELATION_FIELDS = ('sample_id', 'product', 'analyte', 'method', 'sampled')
STATUS_LABEL = {'ORIGINAL': '原归属', 'SUPPLEMENT': '补录改批', 'CONFLICT': '归属冲突'}


def _version(report):
    try:
        return Decimal(str(report.get('version', '1')))
    except Exception:
        return Decimal(0)


def _reported(report):
    return str(report.get('reported', ''))


def _rank(report):
    """Recency without the source line, so genuine ties remain visible."""
    return (_reported(report), _version(report))


def _order(report):
    """Total order for deterministic adjudication, independent of input order."""
    return _rank(report) + (int(report.get('_line') or 0), str(report.get('id', '')))


def _newer(left, right):
    return _rank(left) > _rank(right)


def _by_id(reports):
    """Latest version of every report id, following the documented M5 rule."""
    chosen = {}
    for report in reports:
        current = chosen.get(report['id'])
        if current is None or _version(report) > _version(current):
            chosen[report['id']] = report
    return chosen


def _relation_valid(report, lookup):
    """Relation must point at a real, same sample/product/analyte/method/sampled report.

    A batch difference is allowed: that is exactly what a split-batch correction
    records.  Cycles, dangling links, cross-identity links and bad time order are
    rejected.
    """
    seen = set()
    current = report
    while str(current.get('relation') or '').strip():
        if current['id'] in seen:
            return False
        seen.add(current['id'])
        parent = lookup.get(str(current['relation']).strip())
        if parent is None:
            return False
        if any(str(current.get(field, '')) != str(parent.get(field, '')) for field in RELATION_FIELDS):
            return False
        if not _newer(current, parent):
            return False
        current = parent
    return True


def _claim_problem(report, base, lookup):
    """Return None when the claim can be adjudicated, else an exclusion reason."""
    if (str(report.get('product')) != str(base.get('product'))
            or str(report.get('sampled')) != str(base.get('sampled'))):
        return 'IDENTITY'
    if not str(report.get('batch') or '').strip():
        return 'IDENTITY'
    if not _newer(report, base):
        return 'STALE'
    if not _relation_valid(report, lookup):
        return 'REFERENCE'
    return None


def resolve(reports):
    """Annotate reports and build a per-sample attribution ledger.

    Returns ``(annotated, ledger)``.  ``annotated`` holds shallow copies of every
    input report with private ``_attribution_*`` keys.  ``ledger`` is JSON
    serialisable and is the single source of truth for batch grades, sample
    counts and archive evidence.
    """
    annotated = [dict(report) for report in reports]
    for item in annotated:
        item['_original_batch'] = str(item.get('batch'))
        item.setdefault('_source', 'base')
        item.setdefault('_source_line', item.get('_line'))
        item['_attribution_status'] = 'ORIGINAL'
        item['_superseded'] = False
        item['_attribution_invalid'] = False
        item['_attribution_reason'] = ''
    lookup = _by_id(annotated)
    grouped = defaultdict(list)
    for item in annotated:
        grouped[str(item.get('sample_id'))].append(item)

    entries = []
    for sample_id in sorted(grouped):
        rows = grouped[sample_id]
        base_rows = [row for row in rows if row.get('_source') == 'base'] or rows
        base = min(base_rows, key=_order)
        original_batch = str(base.get('batch'))
        status = 'ORIGINAL'
        applied = None
        resolved = original_batch
        invalid = {}

        candidates = []
        for row in rows:
            if row is base:
                continue
            if str(row.get('batch')) == original_batch:
                continue
            if row.get('_source') == 'base':
                # Contradictory batch inside the base document: never silently
                # re-file, keep the original and quarantine the stray row.
                invalid[id(row)] = 'CONFLICT'
                continue
            problem = _claim_problem(row, base, lookup)
            if problem:
                invalid[id(row)] = problem
            else:
                candidates.append(row)

        if candidates:
            newest = max(_rank(row) for row in candidates)
            top = [row for row in candidates if _rank(row) == newest]
            if len({str(row.get('batch')) for row in top}) > 1:
                # Irreconcilable claims: keep the original attribution and
                # quarantine every claim, so the old batch can still be issued.
                status = 'CONFLICT'
                for row in candidates:
                    invalid[id(row)] = 'CONFLICT' if row in top else 'STALE'
            else:
                status = 'SUPPLEMENT'
                resolved = str(top[0].get('batch'))
                applied = min(top, key=lambda row: (str(row.get('id')), int(row.get('_line') or 0)))
                for row in candidates:
                    if row is not applied and str(row.get('batch')) != resolved:
                        invalid[id(row)] = 'STALE'

        # Analytes explicitly re-reported in the resolved batch: old batch rows
        # of those analytes are superseded evidence, not competing results.
        covered = set()
        if status == 'SUPPLEMENT':
            for row in rows:
                if str(row.get('batch')) == resolved:
                    covered.add((str(row.get('product')), str(row.get('analyte'))))

        for row in rows:
            row['_attribution_status'] = status
            if id(row) in invalid:
                row['_attribution_invalid'] = True
                row['_attribution_reason'] = invalid[id(row)]
                continue
            if row is applied:
                row['_attribution_reason'] = 'SUPPLEMENT'
                continue
            if status == 'CONFLICT':
                # Fail safe: the original attribution is unchanged and its rows
                # are still counted; the offending claims were already excluded.
                row['_attribution_reason'] = 'RETAINED'
                continue
            if status == 'SUPPLEMENT' and str(row.get('batch')) == original_batch:
                if (str(row.get('product')), str(row.get('analyte'))) in covered:
                    row['_superseded'] = True
                    row['_attribution_reason'] = 'SUPERSEDED'
                    continue
                # Other analytes follow their sample into the resolved batch.
                row['batch'] = resolved
                row['_attribution_reason'] = 'MOVED'
                continue
            row['_attribution_reason'] = 'RETAINED'

        evidence = []
        for row in sorted(rows, key=_order):
            evidence.append({
                'id': str(row.get('id')),
                'line': row.get('_line'),
                'source': row.get('_source', 'base'),
                'source_line': row.get('_source_line', row.get('_line')),
                'original_batch': str(row.get('_original_batch')),
                'batch': str(row.get('batch')),
                'reported': _reported(row),
                'version': str(row.get('version')),
                'role': ('applied' if row is applied else
                         'invalid' if row.get('_attribution_invalid') else
                         'superseded' if row.get('_superseded') else
                         'original' if row is base else 'retained'),
                'reason': row.get('_attribution_reason', ''),
            })
        entries.append({
            'sample_id': sample_id,
            'product': str(base.get('product')),
            'sampled': str(base.get('sampled')),
            'original_batch': original_batch,
            'batch': resolved,
            'status': status,
            'status_label': STATUS_LABEL[status],
            'original': {
                'id': str(base.get('id')), 'line': base.get('_line'),
                'source': base.get('_source', 'base'),
                'batch': original_batch, 'reported': _reported(base),
                'version': str(base.get('version')),
            },
            'applied': None if applied is None else {
                'id': str(applied.get('id')), 'line': applied.get('_line'),
                'source': applied.get('_source', 'base'),
                'batch': str(applied.get('batch')), 'reported': _reported(applied),
                'version': str(applied.get('version')),
            },
            'evidence': evidence,
            'superseded': sum(1 for row in rows if row.get('_superseded')),
            'invalid': sum(1 for row in rows if row.get('_attribution_invalid')),
        })

    ledger = {
        'samples': entries,
        'summary': {
            'samples': len(entries),
            'moved': sum(1 for entry in entries if entry['status'] == 'SUPPLEMENT'),
            'conflicts': sum(1 for entry in entries if entry['status'] == 'CONFLICT'),
            'superseded_reports': sum(entry['superseded'] for entry in entries),
            'invalid_reports': sum(entry['invalid'] for entry in entries),
        },
    }
    return annotated, ledger


def by_sample(ledger):
    return {entry['sample_id']: entry for entry in ledger.get('samples', [])}
