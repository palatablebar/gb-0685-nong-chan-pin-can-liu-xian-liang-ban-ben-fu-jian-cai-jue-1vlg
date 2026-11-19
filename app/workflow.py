import time,importlib,json,base64,hashlib
from pathlib import Path
from app.config import MODULES
from app.errors import DomainError
from app.manifest import identity,manifest
from app.supplement import merge

def load(sample):
    if sample not in ('dirty.csv','clean.csv','legacy.csv'):raise DomainError('SAMPLE','样例名称无效')
    return (Path(__file__).resolve().parents[1]/'sample_data'/sample).read_bytes()

def split_parameters(parameters):
    """Separate supplemental CSV bodies from the identity-bearing parameters.

    The supplement bytes take part in the run identity by hash, so the same
    supplement always maps to the same batch and a rerun cannot duplicate
    samples.  The raw text is not echoed back in every stored body.
    """
    params=dict(parameters or {})
    supplements=params.pop('supplements',[])
    parent=params.pop('revision_of',None)
    if supplements is None:supplements=[]
    if not isinstance(supplements,list) or not all(isinstance(item,str) for item in supplements):
        raise DomainError('PARAMETERS','补录必须是文本列表')
    if parent is not None and not isinstance(parent,str):
        raise DomainError('PARAMETERS','修订来源必须是批次号')
    params['supplement_sha256']=[hashlib.sha256(item.encode('utf-8')).hexdigest() for item in supplements]
    params['revision_of']=parent
    return params,supplements

def run(content,parameters=None,stage=7):
    if len(content)>2_000_000:raise DomainError('SIZE','文件超过2MB',413)
    params,supplements=split_parameters(parameters)
    start=time.monotonic();state=None
    for n,entry in enumerate(MODULES,1):
        if n>stage:break
        fn=importlib.import_module('app.modules.'+entry[0]+'.service').execute
        state=fn(content,params) if n==1 else fn(state)
        if n==1 and supplements:state=merge(state,supplements)
    # Decimal values are serialized as strings before any storage or response.
    state=json.loads(json.dumps(state,default=str,ensure_ascii=False))
    state['run_id']=identity(content,params);state['manifest']=manifest(content,params,time.monotonic()-start)
    if supplements:state['manifest']['supplements']=len(supplements)
    state['revision']={'parent':params['revision_of'],'kind':'REVISION' if params['revision_of'] else 'ORIGINAL'}
    state['source_b64']=base64.b64encode(content).decode('ascii')
    state['supplement_b64']=[base64.b64encode(item.encode('utf-8')).decode('ascii') for item in supplements]
    if stage>=7:
        from app.modules.m7_archive.export_out import checksum
        state['archive']['sha256']=checksum(state)
    return state
