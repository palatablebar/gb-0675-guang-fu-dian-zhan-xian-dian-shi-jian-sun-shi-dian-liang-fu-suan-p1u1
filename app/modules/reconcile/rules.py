from decimal import Decimal
from app.coerce import number

def reconcile(state):
    known=[r for r in state['energy_rows'] if r['loss_kwh'] is not None];unknown=[r for r in state['energy_rows'] if r['loss_kwh'] is None]
    sums={k:sum((number(r[k]) for r in known),Decimal(0)) for k in ['loss_kwh','actual_kwh','baseline_kwh']}
    confirmed=[r for r in known if r['settlement']=='CONFIRMED']
    pending=[r for r in known if r['settlement'] in ('PENDING_RESPONSE','PENDING_RECOVERY')]
    confirmed_loss=sum((number(r['loss_kwh']) for r in confirmed),Decimal(0))
    pending_loss=sum((number(r['loss_kwh']) for r in pending),Decimal(0))
    union_seconds=sum(r['seconds'] for r in state['event_unions']);slice_seconds=sum(r['seconds'] for r in state['energy_rows']);c=state['counts'];explained=len(state['records'])+len(state['quarantine'])+c['blank']+c['duplicate']+c['repeated_header']
    # Decimal周期小数允许最后一位精度误差，展示前统一量化到0.0001kWh再检查。
    quant=lambda v:v.quantize(Decimal('.0001'))
    return {'input':c['input'],'accepted':len(state['records']),'quarantined':len(state['quarantine']),'row_balanced':explained==c['input'],'union_seconds':union_seconds,'slice_seconds':slice_seconds,'time_balanced':union_seconds==slice_seconds,
            'loss_kwh':str(quant(sums['loss_kwh'])),'actual_kwh':str(quant(sums['actual_kwh'])),'baseline_kwh':str(quant(sums['baseline_kwh'])),'energy_balanced':quant(sums['baseline_kwh'])==quant(sums['actual_kwh']+sums['loss_kwh']),
            'unknown_segments':len(unknown),'unknown_seconds':sum(r['seconds'] for r in unknown),
            # 正式损失只认可量到响应并完成恢复的时段；待查与未定单列，不混入可结算口径。
            'settled_segments':len(confirmed),'settled_seconds':sum(r['seconds'] for r in confirmed),'settled_loss_kwh':str(quant(confirmed_loss)),
            'pending_segments':len(pending),'pending_seconds':sum(r['seconds'] for r in pending),'pending_loss_kwh':str(quant(pending_loss)),
            'pending_response_segments':sum(r['settlement']=='PENDING_RESPONSE' for r in pending),'pending_recovery_segments':sum(r['settlement']=='PENDING_RECOVERY' for r in pending),
            # 可结算 + 待查必须等于全部已确定损失，并与能量账交叉一致；任一被篡改即守恒失败。
            'settlement_balanced':quant(confirmed_loss+pending_loss)==quant(sums['loss_kwh']) and quant(sums['baseline_kwh'])==quant(sums['actual_kwh']+confirmed_loss+pending_loss)}
def apply(state):
    state['balance']=reconcile(state);state['views']['reconcile']={'title':'可结算与待查响应四账','rows':[state['balance']],
        'metrics':{'可结算损失_kWh':state['balance']['settled_loss_kwh'],'待查损失_kWh':state['balance']['pending_loss_kwh'],
                   '可结算分钟':state['balance']['settled_seconds']//60,'待查分钟':state['balance']['pending_seconds']//60,
                   '未定分钟':state['balance']['unknown_seconds']//60,'并集分钟':state['balance']['union_seconds']//60}}
