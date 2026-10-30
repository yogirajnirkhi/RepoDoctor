"""Rendered UI integration checks; all metrics come from a real local scan."""
import json
import time
import pytest
from fastapi.testclient import TestClient
from repodoctor.persistence.db import DB
from repodoctor.engine import Engine
from repodoctor.models import ScanConfig
from repodoctor.app.server import create_app

@pytest.fixture(scope='module')
def ui(tmp_path_factory):
    base=tmp_path_factory.mktemp('ui')
    source=base/'repository'; source.mkdir()
    (source/'example.py').write_text('def choose(x):\n    if x:\n        return 1\n    return 0\n')
    db=DB(base/'db.sqlite')
    engine=Engine(db=db,artifacts_root=base/'artifacts')
    sid=engine.submit(ScanConfig(target=str(source)))
    for _ in range(200):
        row=db.get_scan(sid)
        if row['state'] in ('COMPLETED','FAILED'):break
        time.sleep(.05)
    assert row['state']=='COMPLETED',row['error']
    with TestClient(create_app(db=db,engine=engine)) as client:
        yield client,sid,db,source

@pytest.mark.parametrize('pane',['overview','git','code','deps','findings','artifacts'])
def test_real_scan_panes(ui,pane):
    client,sid,_,_=ui
    response=client.get(f'/scans/{sid}/pane/{pane}')
    assert response.status_code==200
    assert response.text.strip()
    assert '<script src="https://' not in response.text

@pytest.mark.parametrize('path',['/','/new','/static/ui.js','/static/css/app.css','/static/vendor/htmx.min.js','/static/vendor/echarts.min.js'])
def test_local_ui_assets(ui,path):
    client,_,_,_=ui
    assert client.get(path).status_code==200

def test_health_score_matches_stored_result(ui):
    client,sid,db,_=ui
    score=json.loads(db.get_scan(sid)['score_json'])['score']
    assert str(score) in client.get(f'/scans/{sid}/pane/overview').text

def test_findings_filters_and_semantic_navigation(ui):
    client,sid,_,_=ui
    page=client.get(f'/scans/{sid}').text
    assert 'aria-label="Analysis sections"' in page
    assert 'data-side-tab="deps"' in page
    pane=client.get(f'/scans/{sid}/pane/findings').text
    assert 'findings-severity' in pane and 'findings-category' in pane

def test_scan_form_uses_htmx_redirect(ui):
    client,_,_,source=ui
    response=client.post('/scans',data={'target':str(source)})
    assert response.status_code==200
    assert response.headers['HX-Redirect'].startswith('/scans/')
    assert '<script>' not in response.text
