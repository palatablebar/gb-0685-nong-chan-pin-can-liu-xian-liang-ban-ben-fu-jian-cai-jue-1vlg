"""Verdict selection over measurements grouped by the *resolved* batch.

M5 originally grouped by ``(sample, batch, analyte)``.  After a supplemental
re-batch the same sample can carry reports under two batches, so grouping must
use the adjudicated batch from :mod:`app.attribution` to keep exactly one
verdict per sample and analyte.  The documented relation, root, latest-version,
tie and cycle rules are unchanged.
"""
from collections import defaultdict
from decimal import Decimal

# Batch is deliberately excluded: attribution already decided the batch.  A
# supplemental report legitimately points at its old-batch original.
RELATION_FIELDS = ('sample_id', 'product', 'analyte', 'method', 'sampled')


def _version(report):
    try:
        return Decimal(str(report.get('version', '1')))
    except Exception:
        return Decimal(0)


def _rank(report):
    return (str(report.get('reported', '')), _version(report))


def _latest_versions(rows):
    versions = {}
    for row in rows:
        if row['id'] not in versions or _version(row) > _version(versions[row['id']]):
            versions[row['id']] = row
    return versions


def _relation_valid(report, lookup):
    """Follow ``relation`` through the evidence chain (superseded rows included)."""
    seen = []
    current = report
    while str(current.get('relation') or '').strip():
        if current['id'] in seen:
            return False
        seen.append(current['id'])
        parent = lookup.get(str(current['relation']).strip())
        if parent is None:
            return False
        if any(str(current.get(field, '')) != str(parent.get(field, '')) for field in RELATION_FIELDS):
            return False
        if _rank(current) <= _rank(parent):
            return False
        current = parent
    return True


def _root(report, lookup):
    """Return the root report id of the relation chain, or None when broken."""
    seen = set()
    current = report
    while True:
        if current['id'] in seen:
            return None
        seen.add(current['id'])
        relation = str(current.get('relation') or '').strip()
        if not relation:
            return current['id']
        parent = lookup.get(relation)
        if parent is None:
            return None
        current = parent


def select_nested(measurements, ledger):
    """Return ``(chosen, quarantine)`` using the attribution ledger.

    ``quarantine`` is a list of ``(report, code)`` pairs.  Reports excluded by
    attribution are quarantined before any verdict is built, so a supplemental
    re-batch can never contribute a second counted result.
    """
    samples = {entry['sample_id']: entry for entry in ledger.get('samples', [])}
    by_sample = defaultdict(list)
    for row in measurements:
        by_sample[row['sample_id']].append(row)

    result, quarantine = [], []

    for sample_id in sorted(by_sample):
        rows = by_sample[sample_id]
        entry = samples.get(sample_id)
        if entry is None:
            for row in rows:
                quarantine.append((row, 'CONFLICT'))
            continue

        # Full evidence lookup resolves relation chains that cross the old/new
        # batch boundary; superseded rows remain reachable.
        evidence = _latest_versions(rows)
        batch = entry['batch']

        usable = []
        for row in rows:
            reason = row.get('_attribution_reason')
            if row.get('_attribution_invalid'):
                code = reason if reason in ('REFERENCE', 'STALE', 'IDENTITY', 'CONFLICT') else 'CONFLICT'
                quarantine.append((row, code))
                continue
            if row.get('_superseded'):
                quarantine.append((row, 'SUPERSEDED'))
                continue
            row['batch'] = batch
            usable.append(row)

        lookup = _latest_versions(usable)
        reports = list(lookup.values())
        bad = {}
        for report in reports:
            if not _relation_valid(report, evidence):
                bad[report['id']] = 'REFERENCE'

        grouped = defaultdict(list)
        for report in reports:
            if report['id'] not in bad:
                grouped[(batch, report['product'], report['analyte'])].append(report)

        for key in sorted(grouped):
            group = grouped[key]
            roots = {_root(row, evidence) for row in group}
            if len(roots) != 1 or None in roots:
                for row in group:
                    bad[row['id']] = 'CONFLICT'
                continue
            candidates = [row for row in group if row['id'] not in bad]
            if not candidates:
                continue
            top = max(_rank(row) for row in candidates)
            newest = [row for row in candidates if _rank(row) == top]
            if len({(row['lower'], row['upper']) for row in newest}) > 1:
                for row in group:
                    bad[row['id']] = 'CONFLICT'

        for report in reports:
            if report['id'] in bad:
                quarantine.append((report, bad[report['id']]))

        for key in sorted(grouped):
            group = grouped[key]
            if any(row['id'] in bad for row in group):
                continue
            candidates = [row for row in group if row['id'] not in bad]
            if not candidates:
                continue
            top = max(_rank(row) for row in candidates)
            newest = [row for row in candidates if _rank(row) == top]
            winner = sorted(newest, key=lambda row: (str(row['id']), str(row['_line'])))[0]
            # Superseded evidence of the same analyte stays reachable in the
            # ledger and the archive, but never becomes a second verdict.
            result.append(winner)

    return result, quarantine
