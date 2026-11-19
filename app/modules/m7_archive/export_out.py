import io,csv,json,hashlib

HEADER=['记录类型','批次','来源行','业务ID','原因码','内容']

def _evidence(state):
    """Every attribution row, including superseded and excluded evidence."""
    for entry in state.get('attribution',{}).get('samples',[]):
        for item in entry.get('evidence',[]):
            yield entry,item

def bundle(state):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(HEADER)
    rid=state.get('run_id','preview')
    writer.writerow(['运行清单',rid,'','','',json.dumps(state.get('manifest',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['修订',rid,'','','',json.dumps(state.get('revision',{}),ensure_ascii=False,sort_keys=True)])
    writer.writerow(['对账',rid,'','','',json.dumps(state.get('reconcile',{}),ensure_ascii=False,sort_keys=True)])
    for entry,item in _evidence(state):
        writer.writerow(['归属',item.get('original_batch',''),item.get('line',''),item.get('id',''),
                         item.get('reason',''),json.dumps(dict(item,sample_id=entry['sample_id']),ensure_ascii=False,sort_keys=True)])
    for row in state.get('calculations',[]):
        writer.writerow(['计算',row.get('batch',''),row.get('line',''),row.get('id',''),row.get('code',''),json.dumps(row,ensure_ascii=False,sort_keys=True)])
    for row in state['quarantine']:
        writer.writerow(['隔离',row.get('batch',''),row['line'],row.get('id',''),row['code'],json.dumps(row.get('raw',{}),ensure_ascii=False,sort_keys=True)])
    return '﻿'+out.getvalue()

def attribution_bundle(state):
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['样本','产品','采样日','原归属批次','裁定批次','归属状态','原报告ID','原来源行','补录报告ID','补录来源行','证据数','被替代数','隔离数'])
    for entry in state.get('attribution',{}).get('samples',[]):
        original=entry.get('original') or {};applied=entry.get('applied') or {}
        writer.writerow([entry['sample_id'],entry['product'],entry['sampled'],entry['original_batch'],entry['batch'],
            entry['status_label'],original.get('id',''),original.get('line',''),applied.get('id',''),applied.get('line',''),
            len(entry.get('evidence',[])),entry.get('superseded',0),entry.get('invalid',0)])
    return '﻿'+out.getvalue()

def checksum(state):
    return hashlib.sha256(bundle(state).encode('utf-8')).hexdigest()
