import importlib
from flask import Flask,jsonify,request,redirect,Response
from app.config import MODULES
from app.errors import DomainError
from app.workflow import run,load
from app import store
from app.web import payload
from app.modules.m7_archive.export_out import bundle,attribution_bundle

def create_app():
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=4_000_000
    for entry in MODULES:app.register_blueprint(importlib.import_module('app.modules.'+entry[0]+'.handler').bp)
    @app.errorhandler(DomainError)
    def domain_error(error):return jsonify(code=error.code,message=error.message),error.status
    @app.errorhandler(404)
    def missing(error):return jsonify(code='NOT_FOUND',message='入口不存在'),404
    @app.get('/')
    def index():return redirect('/'+MODULES[0][0])
    @app.get('/healthz')
    def health():return jsonify(status='ok')
    @app.post('/api/runs')
    def submit():
        content,params=payload()
        state=run(content,params)
        parent=state['manifest']['parameters'].get('revision_of')
        if parent:
            # A revision is built from a known, archived batch.  The old result is
            # left untouched, so an interrupted revision keeps the previous
            # version readable and reviewable.
            try:previous=store.get(parent)
            except DomainError:raise DomainError('REVISION','修订来源批次不存在',409)
            if not previous.get('archive',{}).get('ready') or previous.get('reconcile',{}).get('balanced') is False:
                raise DomainError('REVISION','原批次尚未归档或对账未平，不能补录修订',409)
        return jsonify(store.save(state['run_id'],state,parent=parent))
    @app.get('/api/runs')
    def list_runs():return jsonify(store.history())
    @app.get('/api/runs/<run_id>')
    def get_run(run_id):return jsonify(store.get(run_id))
    @app.post('/api/runs/<run_id>/review')
    def review(run_id):
        data=request.get_json(silent=True) or {}
        if not isinstance(data.get('version'),int):raise DomainError('VERSION','请提交复核版本')
        return jsonify(store.review(run_id,data['version'],data.get('decision')))
    @app.get('/api/archive/<run_id>/export.csv')
    def download(run_id):
        state=store.get(run_id)
        if not state.get('archive',{}).get('ready'):raise DomainError('UNBALANCED','对账未平或批次归属未核对')
        return Response(bundle(state),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=evidence.csv'})
    @app.get('/api/archive/<run_id>/attribution.csv')
    def download_attribution(run_id):
        state=store.get(run_id)
        return Response(attribution_bundle(state),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=attribution.csv'})
    with app.app_context():
        if not store.history():
            state=run(load('dirty.csv'),{});store.save(state['run_id'],state)
    return app

app=create_app()
if __name__=='__main__':app.run(host='0.0.0.0',port=8000)
