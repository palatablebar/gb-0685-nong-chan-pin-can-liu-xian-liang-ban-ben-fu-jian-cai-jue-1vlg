from app.modules.m7_archive.export_out import checksum

def execute(state):
    attribution=state.get('attribution',{'samples':[],'summary':{}})
    evidence=sum(len(entry.get('evidence',[])) for entry in attribution.get('samples',[]))
    state['archive']={'sha256':checksum(state),
        'evidence_count':len(state.get('calculations',[]))+len(state['quarantine'])+evidence,
        'attribution_evidence':evidence,
        'superseded':len(state.get('superseded',[])),
        'ready':state.get('reconcile',{}).get('balanced',False) and state.get('reconcile',{}).get('consistent',True)}
    return state
