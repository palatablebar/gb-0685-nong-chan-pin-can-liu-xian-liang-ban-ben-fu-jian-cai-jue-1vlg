import csv, io
import pytest

from app import store
from app.errors import DomainError
from app.modules.m7_archive.export_out import attribution_bundle, bundle
from app.workflow import load, run

HEADER = ('id,sample_id,batch,product,analyte,method,version,sampled,reported,'
          'result,unit,lod,relation,note\n')

# S003 is re-filed from B001 to B002 by a supplemental report: its P01 result is
# re-stated and its P02 result follows the sample.  Old batch rows stay evidence.
MOVE = HEADER + (
    '00037,S003,B002,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-04,0.004,mg/kg,0.001,00008,补录改批\n'
    '00038,S003,B002,苹果,P02,GC-MS,1,2026-08-01,2026-08-04,30,ug/kg,1,,补录另一项目\n')


def sample_state(supplements):
    return run(load('clean.csv'), {'supplements': supplements})


def entry(state, sample_id):
    return next(e for e in state['attribution']['samples'] if e['sample_id'] == sample_id)


def grade(state, batch):
    return next(g for g in state['reconcile']['grades'] if g['batch'] == batch)


def test_rebatch_counts_sample_once():
    base = run(load('clean.csv'), {})
    state = sample_state([MOVE])
    assert len(state['calculations']) == len(base['calculations']) == 24
    assert grade(state, 'B001')['samples'] == 2 and grade(state, 'B001')['projects'] == 4
    assert grade(state, 'B002')['samples'] == 4 and grade(state, 'B002')['projects'] == 8
    # No sample is counted in two batches.
    batches = {}
    for row in state['calculations']:
        batches.setdefault(row['sample_id'], set()).add(row['batch'])
    assert all(len(value) == 1 for value in batches.values())
    assert entry(state, 'S003')['batch'] == 'B002'


def test_rebatch_keeps_original_evidence():
    state = sample_state([MOVE])
    moved = entry(state, 'S003')
    assert moved['status'] == 'SUPPLEMENT'
    assert moved['original'] == {'id': '00007', 'line': 11, 'source': 'base',
                                 'batch': 'B001', 'reported': '2026-08-02', 'version': '1'}
    assert moved['applied']['id'] == '00037' and moved['applied']['line'] == 100002
    assert {item['id'] for item in moved['evidence']} >= {'00007', '00008', '00009', '00037', '00038'}
    superseded = {item['id'] for item in moved['evidence'] if item['role'] == 'superseded'}
    assert superseded == {'00007', '00008', '00009'}
    # Original attribution evidence stays downloadable.
    exported = attribution_bundle(state)
    assert 'S003' in exported and 'B001' in exported and '补录改批' in exported


def test_batch_grades_and_counts_share_one_attribution():
    state = sample_state([MOVE])
    reconcile = state['reconcile']
    assert reconcile['balanced'] is True
    assert reconcile['consistent'] is True
    assert sum(g['samples'] for g in reconcile['grades']) == len(state['attribution']['samples']) == 12
    assert sum(g['projects'] for g in reconcile['grades']) == state['business']['total'] == 24
    assert grade(state, 'B002')['code'] == 'FAIL'
    assert state['superseded'] and all(row['batch'] == row['original_batch'] for row in state['superseded'])


def test_conflicting_rebatch_keeps_original():
    supplement = HEADER + (
        '00037,S003,B002,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-04,0.004,mg/kg,0.001,00008,改B002\n'
        '00038,S003,B004,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-04,0.004,mg/kg,0.001,00008,改B004\n')
    state = sample_state([supplement])
    moved = entry(state, 'S003')
    assert moved['status'] == 'CONFLICT' and moved['batch'] == 'B001'
    assert grade(state, 'B001')['samples'] == 3
    assert grade(state, 'B004')['samples'] == 3
    assert {q['id'] for q in state['quarantine']} == {'00037', '00038'}
    assert all(q['code'] == 'CONFLICT' for q in state['quarantine'])
    assert state['reconcile']['balanced'] is True


@pytest.mark.parametrize('row,code', [
    ('00037,S003,B002,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-04,0.004,mg/kg,0.001,00001,错引样本', 'REFERENCE'),
    ('00037,S003,B002,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-04,0.004,mg/kg,0.001,99999,悬空', 'REFERENCE'),
    ('00037,S003,B002,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-01,0.004,mg/kg,0.001,00008,日期倒退', 'STALE'),
])
def test_unusable_rebatch_claim_is_quarantined(row, code):
    state = sample_state([HEADER + row + '\n'])
    moved = entry(state, 'S003')
    assert moved['status'] == 'ORIGINAL' and moved['batch'] == 'B001'
    assert len(state['calculations']) == 24
    assert any(q['id'] == '00037' and q['code'] == code for q in state['quarantine'])
    assert state['reconcile']['balanced'] is True


def test_supplement_resend_is_duplicate_not_new_sample():
    resend = HEADER + '00009,S003,B001,苹果,P02,GC-MS,1,2026-08-01,2026-08-02,30,ug/kg,1,,另一残留项目\n'
    state = sample_state([resend])
    assert len(state['calculations']) == 24
    assert state['reconcile']['duplicates'] == 1
    assert state['reconcile']['balanced'] is True
    assert run(load('clean.csv'), {'supplements': [resend]})['run_id'] == state['run_id']


def test_conflicting_restatement_is_rejected():
    restate = HEADER + '00009,S003,B001,苹果,P02,GC-MS,1,2026-08-01,2026-08-02,31,ug/kg,1,,另一残留项目\n'
    with pytest.raises(DomainError) as error:
        sample_state([restate])
    assert error.value.code == 'REVISION' and error.value.status == 409


def test_revision_keeps_previous_result_and_is_idempotent(client):
    base = load('clean.csv').decode('utf-8-sig')
    original = client.post('/api/runs', json={'csv': base}).get_json()
    payload = {'csv': base, 'parameters': {'supplements': [MOVE], 'revision_of': original['run_id']}}
    revision = client.post('/api/runs', json=payload).get_json()
    assert revision['run_id'] != original['run_id']
    assert revision['revision'] == {'parent': original['run_id'], 'kind': 'REVISION'}

    # Rerunning the same supplement neither adds nor drops samples or records.
    before = len(client.get('/api/runs').get_json())
    again = client.post('/api/runs', json=payload).get_json()
    assert again['run_id'] == revision['run_id']
    assert len(again['calculations']) == len(revision['calculations'])
    assert len(client.get('/api/runs').get_json()) == before

    # The old batch is untouched and still reviewable while the revision exists.
    kept = client.get('/api/runs/' + original['run_id']).get_json()
    assert kept['attribution']['summary']['moved'] == 0
    assert len(kept['calculations']) == 24
    assert client.post('/api/runs/' + original['run_id'] + '/review',
                       json={'version': 1, 'decision': '通过'}).status_code == 200


def test_interrupted_revision_keeps_old_version(client):
    base = load('clean.csv').decode('utf-8-sig')
    original = client.post('/api/runs', json={'csv': base}).get_json()
    bad = HEADER + '00037,S003,B002,苹果,P01,LC-MS/MS,3,2026-08-01,2026-08-01,0.004,mg/kg,0.001,00008,日期倒退\n'
    # A rejected claim does not fail the run, but an irreconcilable restatement
    # aborts before anything is stored.
    conflict = HEADER + '00009,S003,B001,苹果,P02,GC-MS,1,2026-08-01,2026-08-02,31,ug/kg,1,,另一残留项目\n'
    response = client.post('/api/runs', json={'csv': base, 'parameters': {
        'supplements': [conflict], 'revision_of': original['run_id']}})
    before = len(client.get('/api/runs').get_json())
    assert response.status_code == 409
    assert len(client.get('/api/runs').get_json()) == before
    assert client.get('/api/runs/' + original['run_id']).get_json()['calculations'] == original['calculations']

    # A stale claim alone keeps the original attribution and stays auditable.
    accepted = client.post('/api/runs', json={'csv': base, 'parameters': {
        'supplements': [bad], 'revision_of': original['run_id']}}).get_json()
    assert accepted['attribution']['summary']['moved'] == 0
    assert any(q['code'] == 'STALE' for q in accepted['quarantine'])


def test_revision_requires_archived_parent(client):
    base = load('clean.csv').decode('utf-8-sig')
    original = client.post('/api/runs', json={'csv': base}).get_json()
    response = client.post('/api/runs', json={'csv': base, 'parameters': {
        'supplements': [MOVE], 'revision_of': 'missing'}})
    before = len(client.get('/api/runs').get_json())
    assert response.status_code == 409
    assert response.get_json()['code'] == 'REVISION'
    assert len(client.get('/api/runs').get_json()) == before


def test_archive_contains_attribution_evidence():
    state = sample_state([MOVE])
    rows = list(csv.reader(io.StringIO(bundle(state).lstrip('﻿'))))
    attribution_rows = [row for row in rows if row[0] == '归属']
    assert len(attribution_rows) == sum(len(e['evidence']) for e in state['attribution']['samples'])
    assert state['archive']['attribution_evidence'] == len(attribution_rows)
    assert state['archive']['ready'] is True
    assert '补录改批' in attribution_bundle(state)
