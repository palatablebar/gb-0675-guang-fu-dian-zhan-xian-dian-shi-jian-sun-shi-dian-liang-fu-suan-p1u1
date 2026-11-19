"""响应确认裁定：调度指令不等于可结算，须量到现场响应并完成恢复。"""
import pytest
from app.engine import evaluate
from app.modules.loss.rules import adjudicate, integrate, recovery_verdict
from app.modules.reconcile.rules import reconcile
from copy import deepcopy


@pytest.fixture
def resp():
    return evaluate({'dataset': 'response'})


def test_confirmed_segments_only_settled(resp):
    confirmed = [r for r in resp['energy_rows'] if r['settlement'] == 'CONFIRMED']
    assert {r['device'] for r in confirmed} == {'INV-A'}
    assert len(confirmed) == 3
    assert resp['balance']['settled_loss_kwh'] == '20.0000'
    assert all(r['recovery_id'] == 'INV-A-40' for r in confirmed)


def test_no_dispatch_response_is_pending_not_settled(resp):
    # INV-B 出力仅 48/50，下挫 4% 未达 10% 门槛：指令下达但现场未响应。
    rows = [r for r in resp['energy_rows'] if r['device'] == 'INV-B']
    assert len(rows) == 2
    assert all(r['settlement'] == 'PENDING_RESPONSE' for r in rows)
    assert all(r['response_code'] == 'NO_DROP' for r in rows)
    assert all(r['recovery_id'] == '' for r in rows)
    assert resp['balance']['pending_response_segments'] == 2


def test_recovery_gap_is_pending_recovery(resp):
    # INV-C 出力 40/80 已确认响应，但事件结束后恢复窗口内无目标遥测。
    rows = [r for r in resp['energy_rows'] if r['device'] == 'INV-C']
    assert all(r['settlement'] == 'PENDING_RECOVERY' for r in rows)
    assert all(r['response_code'] == 'RECOVERY_UNPROVEN' for r in rows)
    assert resp['balance']['pending_recovery_segments'] == 2


def test_pending_loss_excluded_from_settled_total(resp):
    b = resp['balance']
    assert b['settled_loss_kwh'] == '20.0000'
    assert b['pending_loss_kwh'] == '14.0000'
    assert b['loss_kwh'] == '34.0000'
    # 可结算 + 待查必须等于全部已确定损失，待查不得混入正式损失也不得丢失。
    assert b['settlement_balanced'] is True


def test_evidence_gap_remains_unconfirmed_null(resp):
    # 证据不足（缺测/故障/无对照）保持 null 损失，不填0、不进可结算也不进待查。
    rows = [r for r in resp['energy_rows'] if r['settlement'] == 'UNCONFIRMED']
    assert all(r['loss_kwh'] is None for r in rows)
    assert all(r['response_code'] == 'EVIDENCE_GAP' for r in rows)


def test_dirty_evidence_gap_never_settled(sample):
    b = sample['balance']
    assert b['settled_loss_kwh'] == '0.0000'
    assert b['unknown_segments'] == 2
    assert all(r['settlement'] != 'CONFIRMED' for r in sample['energy_rows'])


def test_clean_all_confirmed_and_archivable(clean):
    assert all(r['settlement'] == 'CONFIRMED' for r in clean['energy_rows'])
    assert clean['balance']['settled_loss_kwh'] == '26.6667'
    assert clean['balance']['pending_segments'] == 0
    assert clean['archive']['status'] == '可归档'


def test_response_sample_blocks_archive(resp):
    assert resp['archive']['status'] == '待复核'
    assert resp['archive']['pending'] == 4


def test_drop_threshold_boundary(clean):
    # 下挫比例恰好等于门槛视为已响应；再低一档即未响应。
    row = next(r for r in clean['energy_rows'] if r['device'] == 'INV-A')
    at_limit = dict(row, baseline_kw='100', actual_kw='90')
    below = dict(row, baseline_kw='100', actual_kw='91')
    adjudicate([at_limit], clean['records'], clean['context'], clean['event_unions'])
    adjudicate([below], clean['records'], clean['context'], clean['event_unions'])
    assert at_limit['settlement'] != 'PENDING_RESPONSE'
    assert below['settlement'] == 'PENDING_RESPONSE'


def test_recovery_outside_window_not_evidence(resp):
    # 恢复样本落在事件结束窗口之外（>600s）不能作为恢复证据。
    union = next(u for u in resp['event_unions'] if u['device'] == 'INV-C')
    ok, evidence_id = recovery_verdict(union, resp['records'], resp['context'])
    assert ok is False and evidence_id == ''


def test_recovery_within_tolerance_confirms(clean):
    # clean 批 INV-A 事件 10:30 结束，10:40 样本 98kW 对基线 100kW 偏差 2%，在 5% 容差内。
    union = next(u for u in clean['event_unions'] if u['device'] == 'INV-A')
    ok, evidence_id = recovery_verdict(union, clean['records'], clean['context'])
    assert ok is True and evidence_id == 'INV-A-40'


def test_integrate_null_when_no_baseline(clean):
    r = integrate(dict(clean['estimates'][0], baseline_kw=None))
    assert r['loss_kwh'] is None and r['actual_kwh'] is None and r['baseline_kwh'] is None


def test_tamper_breaks_settlement_balance(resp):
    s = deepcopy(resp)
    s['energy_rows'][0]['loss_kwh'] = '999'
    b = reconcile(s)
    assert b['settlement_balanced'] is False


def test_overrides_threshold(clean):
    # 门槛可经 overrides 复核：提高到 50% 后，INV-A 下挫 40% 不再满足响应。
    s = evaluate({'dataset': 'clean', 'overrides': {'response_drop_ratio': '0.50'}})
    rows = [r for r in s['energy_rows'] if r['device'] == 'INV-A']
    assert all(r['settlement'] == 'PENDING_RESPONSE' for r in rows)
    assert s['balance']['settled_loss_kwh'] == '0.0000'
