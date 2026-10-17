from datetime import datetime, timezone
from dataclasses import dataclass
@dataclass
class Assessment:
    state:str
    reasons:list
    can_clear:bool=False

def assess(events, sensor_online=True, policy_available=True):
    reasons=[]
    if not sensor_online or not events:
        return Assessment('INSUFFICIENT CURRENT EVIDENCE',['Sensor coverage unavailable; no all-clear can be inferred.'])
    if not policy_available:
        return Assessment('HUMAN REVIEW REQUIRED',['Approved policy snapshot unavailable.'])
    valid=[e for e in events if e.get('delivery_status')=='received']
    if len(valid)<len(events): reasons.append('Delayed observations excluded from current assessment.')
    if not valid: return Assessment('INSUFFICIENT CURRENT EVIDENCE',reasons+['No current accepted observations.'])
    low=[e for e in valid if float(e.get('quality',0))<.5]
    if low: reasons.append(f'{len(low)} low-quality observations require review.')
    reasons.append('Observation identity is unverified; no automated clearance or interdiction.')
    return Assessment('HUMAN REVIEW REQUIRED',reasons)

def capability_state(offline=False,ai_down=False,sensor_down=False,policy_down=False):
    return {'Internet':'OFFLINE' if offline else 'ONLINE','AI':'UNAVAILABLE' if ai_down else 'OPTIONAL / SIMULATED','Sensor coverage':'UNAVAILABLE' if sensor_down else 'AVAILABLE','Policy snapshot':'UNAVAILABLE' if policy_down else 'AVAILABLE','CPU decision core':'RUNNING'}
