from app.modules.m5_calculate.choose import select_nested
from app.attribution import resolve


def select_reports(reports):
    """Backwards compatible entry point used by tests and callers.

    Batch attribution is resolved on the fly, so a supplemental re-batch still
    yields exactly one verdict per sample and analyte.
    """
    annotated, ledger = resolve(reports)
    chosen, quarantine = select_nested(annotated, ledger)
    bad = {report['id']: code for report, code in quarantine if code != 'SUPERSEDED'}
    return chosen, bad


def apply(state):
    # Attribution is adjudicated before any verdict so batch grades, sample
    # counts and archive evidence all derive from the same decision.
    annotated, ledger = resolve(state['measurements'])
    chosen, quarantine = select_nested(annotated, ledger)

    lines=set()
    for report,code in quarantine:
        if code=='SUPERSEDED':
            # Superseded reports stay as original evidence: not counted, not
            # silently deleted and never re-quarantined as invalid data.
            continue
        lines.add(report['_line'])
        state['quarantine'].append({'line':report['_line'],'id':report['id'],'code':code,
            'raw':report['_raw'],'source':report.get('_source','base'),
            'source_line':report.get('_source_line',report['_line'])})
    state['rows']=[r for r in state['rows'] if r['_line'] not in lines]

    state['attribution']=ledger
    state['measurements']=annotated
    state['superseded']=[{'id':r['id'],'line':r['_line'],'sample_id':r['sample_id'],'analyte':r['analyte'],
        'original_batch':r['_original_batch'],'batch':r['batch']} for r in annotated if r.get('_superseded')]

    calculations=[{'id':r['id'],'line':r['_line'],'sample_id':r['sample_id'],'batch':r['batch'],
        'original_batch':r.get('_original_batch',r['batch']),
        'attribution':r.get('_attribution_status','ORIGINAL'),
        'analyte':r['analyte'],'method':r['method'],'standard':r['standard_id'],
        'lower':r['lower'],'upper':r['upper'],'upper_exclusive':r['upper_exclusive'],
        'limit':r['limit'],'code':r['code'],'replaces':r['relation']} for r in chosen]
    state['calculations']=calculations
    state['business']={'total':len(calculations),'pass':sum(r['code']=='PASS' for r in calculations),
        'fail':sum(r['code']=='FAIL' for r in calculations),
        'uncertain':sum(r['code']=='UNCERTAIN' for r in calculations),'unit':'检测项目'}
    return state
