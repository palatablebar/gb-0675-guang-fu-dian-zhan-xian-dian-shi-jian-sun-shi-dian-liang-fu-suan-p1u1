from decimal import Decimal
from datetime import timedelta
from app.coerce import number,instant
from app.config import RESPONSE_DROP_RATIO,RECOVERY_TOLERANCE,RECOVERY_WINDOW_SECONDS
from app.modules.baseline.rules import estimate

# 响应确认裁定：调度指令只划定限电时段，是否结算以现场遥测的响应与恢复证据为准。
# 可结算(CONFIRMED)：指令时段内出力按门槛下挫，且事件结束后恢复窗口内回到基线容差内。
# 待查响应(PENDING_RESPONSE)：指令已下达但现场出力未达响应门槛，不能混入正式损失。
# 待查恢复(PENDING_RECOVERY)：已确认响应，但恢复窗口内缺恢复证据或未回到基线。
# 未定(UNCONFIRMED)：缺测、故障或无合格对照，证据不足，沿用 null 损失，不填0不结算。

def _thresholds(context):
    return (number(context.get('response_drop_ratio',RESPONSE_DROP_RATIO)),
            number(context.get('recovery_tolerance',RECOVERY_TOLERANCE)),
            int(context.get('recovery_window_seconds',RECOVERY_WINDOW_SECONDS)))

def responded(row):
    # 下挫比例 =（基线-实际）/基线；达到响应门槛才认定现场已执行限电指令。
    actual,baseline=number(row['actual_kw']),number(row['baseline_kw'])
    return (baseline-actual)/baseline

def recovery_verdict(union,records,context):
    """对一条限电并集做恢复确认，返回 (是否已恢复, 恢复证据样本id或空)。"""
    _,tolerance,window=_thresholds(context)
    end=instant(union['end']);deadline=end+timedelta(seconds=window)
    candidates=[]
    for row in records:
        if row['kind']!='TELEMETRY' or row['device']!=union['device']:continue
        at=instant(row['at'])
        # 恢复窗口为结束点之后的半开区间 (end, end+window]，窗口为0时不采信任何样本。
        if end<at<=deadline and row['status']=='健康':candidates.append(row)
    if not candidates:return False,''
    evidence=min(candidates,key=lambda r:instant(r['at']))
    # 恢复时点不在任何限电事件中，复用基线拟合规则取得应有出力，保持同一套对照口径。
    baseline_row=estimate({'device':union['device'],'sample_at':evidence['at'],'irradiance':evidence['irradiance'],
                           'actual_kw':evidence['power_kw'],'status':evidence['status'],'zone':context['devices'][union['device']]['zone']},
                          records,context)
    if baseline_row['baseline_kw'] is None:return False,''
    gap=abs(number(evidence['power_kw'])-number(baseline_row['baseline_kw']))/number(baseline_row['baseline_kw'])
    return (gap<=tolerance,evidence['id'])

def adjudicate(rows,records,context,unions):
    drop_ratio,_,_=_thresholds(context)
    recovery={}
    for union in unions:
        ok,evidence_id=recovery_verdict(union,records,context)
        for event_id in union['event_ids']:recovery[(union['device'],event_id)]=(ok,evidence_id)
    for row in rows:
        if row['baseline_kw'] is None or row['actual_kw'] is None:
            row['settlement']='UNCONFIRMED';row['response_code']='EVIDENCE_GAP';row['recovery_id']='';continue
        if responded(row)<drop_ratio:
            row['settlement']='PENDING_RESPONSE';row['response_code']='NO_DROP';row['recovery_id']='';continue
        # 已响应：同一并集内任一下属事件的恢复证据均覆盖该切片。
        recovered,evidence_id=next((recovery[(row['device'],e)] for e in row['event_ids'] if (row['device'],e) in recovery),(False,''))
        row['recovery_id']=evidence_id
        if recovered:row['settlement']='CONFIRMED';row['response_code']='RESPONSED_RECOVERED'
        else:row['settlement']='PENDING_RECOVERY';row['response_code']='RECOVERY_UNPROVEN'
    return rows

def integrate(estimate_row):
    if estimate_row['baseline_kw'] is None:return {**estimate_row,'loss_kwh':None,'actual_kwh':None,'baseline_kwh':None}
    hours=Decimal(estimate_row['seconds'])/3600;actual=number(estimate_row['actual_kw']);baseline=number(estimate_row['baseline_kw']);loss=max(Decimal(0),baseline-actual)*hours
    # 保留计算精度，汇总后再统一保留四位，避免逐段量化制造尾差。
    return {**estimate_row,'loss_kwh':str(loss),'actual_kwh':str(actual*hours),'baseline_kwh':str((actual+max(Decimal(0),baseline-actual))*hours),'code':'LOSS' if loss else 'NO_LOSS'}

def apply(state):
    rows=[integrate(e) for e in state['estimates']]
    rows=adjudicate(rows,state['records'],state['context'],state['event_unions'])
    state['energy_rows']=rows
    total=sum((number(r['loss_kwh']) for r in rows if r['loss_kwh'] is not None),Decimal(0))
    confirmed=sum((number(r['loss_kwh']) for r in rows if r['settlement']=='CONFIRMED'),Decimal(0))
    pending=[r for r in rows if r['settlement'] in ('PENDING_RESPONSE','PENDING_RECOVERY')]
    pending_loss=sum((number(r['loss_kwh']) for r in pending),Decimal(0))
    state['views']['loss']={'title':'响应确认后限电损失','rows':[{k:v for k,v in r.items() if k not in ['sample_at','zone','irradiance','status']} for r in rows],
        'metrics':{'已确定损失_kWh':str(total.quantize(Decimal('.0001'))),'可结算损失_kWh':str(confirmed.quantize(Decimal('.0001'))),
                   '待查损失_kWh':str(pending_loss.quantize(Decimal('.0001'))),'可结算片段':sum(r['settlement']=='CONFIRMED' for r in rows),
                   '待查响应片段':sum(r['settlement']=='PENDING_RESPONSE' for r in rows),'待查恢复片段':sum(r['settlement']=='PENDING_RECOVERY' for r in rows),
                   '未定片段':sum(r['loss_kwh'] is None for r in rows)}}
