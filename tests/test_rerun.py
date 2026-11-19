"""复核重算：失败恢复旧版，重试不新增结果、不丢数据，复核版本与状态不被清零。"""
from fastapi.testclient import TestClient
from app import main, store
from app.errors import BusinessError
from unittest.mock import patch


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'rerun.sqlite'))
    return TestClient(main.app, raise_server_exceptions=False)


def test_rerun_keeps_review_revision_and_single_batch(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    c.post(f'/api/runs/{rid}/review', json={'revision': 1})
    rerun = c.post(f'/api/runs/{rid}/rerun').json()
    assert rerun['manifest']['run_id'] == rid
    got = store.get(main.DB_PATH, rid)
    assert got['revision'] == 2 and got['status'] == '已复核'
    assert len(c.get('/api/runs').json()) == 1


def test_rerun_failure_restores_previous_result(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    c.post(f'/api/runs/{rid}/review', json={'revision': 1})
    before = store.get(main.DB_PATH, rid)
    with patch('app.main.evaluate', side_effect=RuntimeError('重算崩溃')):
        resp = c.post(f'/api/runs/{rid}/rerun')
    assert resp.status_code == 500
    after = store.get(main.DB_PATH, rid)
    assert after['manifest']['sha256'] == before['manifest']['sha256']
    assert after['revision'] == 2 and after['status'] == '已复核'
    assert len(c.get('/api/runs').json()) == 1


def test_business_failure_also_keeps_old_version(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    before = store.get(main.DB_PATH, rid)
    with patch('app.main.evaluate', side_effect=BusinessError('BAD_ENCODING', '编码无法识别')):
        resp = c.post(f'/api/runs/{rid}/rerun')
    assert resp.status_code == 422 and resp.json()['code'] == 'BAD_ENCODING'
    assert store.get(main.DB_PATH, rid)['manifest']['sha256'] == before['manifest']['sha256']


def test_retry_after_failure_does_not_duplicate(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    with patch('app.main.evaluate', side_effect=RuntimeError('重算崩溃')):
        assert c.post(f'/api/runs/{rid}/rerun').status_code == 500
    ok = c.post(f'/api/runs/{rid}/rerun')
    assert ok.status_code == 200 and ok.json()['manifest']['run_id'] == rid
    assert len(c.get('/api/runs').json()) == 1


def test_replace_rejects_foreign_run_id(tmp_path):
    p = str(tmp_path / 'replace.sqlite')
    run = store.save(p, __import__('app.engine', fromlist=['evaluate']).evaluate({'dataset': 'clean'}))
    foreign = dict(run)
    foreign['manifest'] = dict(run['manifest'], run_id='another-batch-id')
    try:
        store.replace(p, run['manifest']['run_id'], foreign)
        raised = False
    except BusinessError as e:
        raised = e.code == 'RUN_ID_MISMATCH'
    assert raised
    # 原批结果未被触碰。
    assert store.get(p, run['manifest']['run_id'])['manifest']['sha256'] == run['manifest']['sha256']


def test_response_dataset_pages_and_api(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'response'}).json()
    rid = run['manifest']['run_id']
    assert run['balance']['settled_loss_kwh'] == '20.0000'
    for k in main.MODULES:
        page = c.get(f'/{k}?run_id={rid}')
        assert page.status_code == 200 and rid in page.text
    loss_page = c.get(f'/loss?run_id={rid}').text
    assert '可结算时段' in loss_page and '待查响应时段' in loss_page
