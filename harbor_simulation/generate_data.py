import csv, random
from pathlib import Path
from datetime import datetime, timedelta
R=random.Random(2026)
OUT=Path(__file__).resolve().parent/'data'; OUT.mkdir(exist_ok=True)
start=datetime(2026,1,1); end=datetime(2026,10,17)
def write(name,header,rows):
 with (OUT/name).open('w',newline='',encoding='utf8') as f:
  w=csv.writer(f);w.writerow(header);w.writerows(rows)
rows=[]; env=[]; vessel=[]; mission=[]; incidents=[]; ground=[]
for i in range(3000):
 t=start+timedelta(seconds=R.randrange(int((end-start).total_seconds())))
 kind=R.choices(['background','environmental_noise','cooperative_robot','unverified_observation','sensor_fault'],[65,15,9,7,4])[0]
 quality=round(R.uniform(.2,.99),2); status=R.choice(['received','received','received','delayed'])
 rows.append([f'EV{i:05d}',t.isoformat(),f'SENSOR-{R.randrange(1,7)}',R.choice(['sonar_summary','hydrophone_event','radar_report','camera_report']),R.choice(['A','B','C','D']),quality,status,'synthetic'])
 ground.append([f'EV{i:05d}',kind,'synthetic_ground_truth_do_not_feed_engine'])
for i in range(800):
 t=start+timedelta(hours=R.randrange(int((end-start).total_seconds()//3600)))
 env.append([t.isoformat(),round(R.uniform(0,2.4),2),round(R.uniform(0,16),2),'synthetic'])
for i in range(1400):
 t=start+timedelta(hours=R.randrange(int((end-start).total_seconds()//3600)))
 vessel.append([f'VES-{R.randrange(1,101):03d}',t.isoformat(),R.choice(['cargo','tug','passenger','service']),R.choice(['A','B','C','D']),R.choice(['scheduled','arrived','delayed']),'synthetic_not_AIS'])
for i in range(180):
 t=start+timedelta(days=R.randrange((end-start).days))
 mission.append([f'M-{i:04d}',t.isoformat(),R.choice(['inspection','maintenance','resupply']),R.choice(['approved','pending','expired']),'synthetic'])
for i in range(100):
 t=start+timedelta(days=R.randrange((end-start).days))
 incidents.append([f'INC-{i:04d}',t.isoformat(),R.choice(['unverified','under_review','resolved']),R.choice(['A','B','C','D']),'synthetic'])
write('synthetic_observations.csv',['event_id','observed_at','source_id','source_type','fictional_zone','quality','delivery_status','provenance'],rows)
write('synthetic_ground_truth.csv',['event_id','simulated_cause','provenance'],ground)
write('synthetic_environment.csv',['timestamp','water_level_m','wind_speed_mps','provenance'],env)
write('synthetic_surface_vessels.csv',['vessel_id','timestamp','vessel_type','fictional_zone','status','provenance'],vessel)
write('synthetic_missions.csv',['mission_id','scheduled_at','mission_type','authorization','provenance'],mission)
write('synthetic_incidents.csv',['incident_id','created_at','status','fictional_zone','provenance'],incidents)
print('Generated 6 synthetic CSV files in',OUT)
