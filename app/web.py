import base64
from flask import request,render_template,jsonify
from app.errors import DomainError
from app.config import TITLE,MODULES,SHORT
from app.workflow import run,load
from app import store

def payload():
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):raise DomainError('PAYLOAD','请求必须是对象')
    if 'csv' in data and not isinstance(data['csv'],str):raise DomainError('CSV','CSV内容必须是文本')
    sample=data.get('sample',request.args.get('sample','dirty.csv'))
    content=data.get('csv')
    return (content.encode() if isinstance(content,str) else load(sample)),data.get('parameters',{})

def api(stage):
    content,parameters=payload();return jsonify(run(content,parameters,stage))

def page(stage,template):
    latest=store.history();state=store.get(latest[0]['id']) if latest else run(load('dirty.csv'),{})
    # Selecting another sample previews that sample alone; the archived batch's
    # supplements and revision link only apply to its own base document.
    if 'sample' in request.args:
        source=load(request.args['sample']);parameters={}
    else:
        source=base64.b64decode(state['source_b64']) if state.get('source_b64') else load('dirty.csv')
        parameters=dict(state.get('manifest',{}).get('parameters',{}))
        supplements=[base64.b64decode(item).decode('utf-8') for item in state.get('supplement_b64',[])]
        if supplements:parameters['supplements']=supplements
    data=run(source,parameters,stage)
    return render_template(template,title=TITLE,short=SHORT,modules=MODULES,current=stage,data=data,run=state,history=latest)
