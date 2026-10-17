from pathlib import Path
import hashlib
import pandas as pd
import streamlit as st
import pydeck as pdk
from core import assess, capability_state

st.set_page_config(page_title='Harbor Resilience | Long Beach Harbor', page_icon='⚓', layout='wide', initial_sidebar_state='expanded')
ROOT = Path(__file__).resolve().parent
st.markdown('''<style>
.stApp{background:#071422;color:#e9f3fc}.block-container{padding-top:1.3rem;max-width:1600px}
[data-testid="stSidebar"]{background:#0c2034;border-right:1px solid #204263}
h1,h2,h3{color:#eaf6ff!important}h1{font-size:2.05rem!important;letter-spacing:-.03em}
[data-testid="stMetric"]{background:#10263b;border:1px solid #21445f;border-radius:13px;padding:13px}
[data-testid="stMetricValue"]{font-size:1.6rem}.stButton button{border-radius:9px}
div[data-testid="stDataFrame"]{border-radius:12px;overflow:hidden}
</style>''',unsafe_allow_html=True)

@st.cache_data
def load():
    return {p.stem: pd.read_csv(p) for p in sorted((ROOT/'data').glob('*.csv'))}
d=load()

st.sidebar.title('⚓ Simulation controls')
st.sidebar.caption('LONG BEACH HARBOR · EDUCATIONAL DIGITAL TWIN')
scenario=st.sidebar.selectbox('Incident scenario',['Normal operations','Unverified underwater report','Conflicting reports','Sensor outage','Port operations disruption'])
zone=st.sidebar.selectbox('Fictional simulation sector',['A','B','C','D'])
playback=st.sidebar.slider('Playback position (%)',0,100,100,5)
st.sidebar.markdown('#### Fault injection')
offline=st.sidebar.toggle('Disconnect internet',False)
ai_down=st.sidebar.toggle('AI service unavailable',False)
sensor_down=st.sidebar.toggle('Sensor coverage lost',False)
policy_down=st.sidebar.toggle('Policy snapshot unavailable',False)
replay=st.sidebar.toggle('Replay old/duplicate observations',False)
st.sidebar.info('CPU assessments work without AI or internet. This app does not control vessels or make clearance decisions.')

st.title('⚓ Harbor Resilience Simulator')
st.caption('LONG BEACH HARBOR  |  Maritime continuity and human decision support  |  DEMONSTRATION / SYNTHETIC EVENTS')
if scenario != 'Normal operations':
    st.warning(f'EXERCISE SCENARIO: {scenario} — simulated observations only; no real incident is implied.')

statuses=capability_state(offline,ai_down,sensor_down or scenario=='Sensor outage',policy_down)
metrics=st.columns(5)
for col,(name,value) in zip(metrics,statuses.items()):
    col.metric(name,value)

# Publicly named civilian facilities; locations are approximate visual anchors, not operational coordinates.
terminals=pd.DataFrame([
    {'name':'Pier T Container Terminal','kind':'Cargo','lat':33.752,'lon':-118.223},
    {'name':'Pier J Container Terminal','kind':'Cargo','lat':33.744,'lon':-118.194},
    {'name':'Pier G Container Terminal','kind':'Cargo','lat':33.757,'lon':-118.205},
    {'name':'Pier B Rail Support Area','kind':'Logistics','lat':33.774,'lon':-118.218},
])
terminals['color']=terminals.kind.map({'Cargo':[255,171,65,230],'Logistics':[52,210,224,230]})
terminals['radius']=360

# Deterministic fictional visual markers, not reconstructed vessel positions.
vessels=[]
for i in range(22):
    a=int(hashlib.sha256(f'vessel-{i}'.encode()).hexdigest()[:8],16)
    lat=33.735+(a%3600)/100000
    lon=-118.248+((a//3600)%6500)/100000
    vessels.append({'name':f'SIM-V{i+1:02d}','lat':lat,'lon':lon,'radius':125,'color':[58,157,255,185]})
vessel_df=pd.DataFrame(vessels)
incidents=pd.DataFrame([{'name':'SIMULATED CONTACT — UNVERIFIED','lat':33.740,'lon':-118.217,'radius':550,'color':[255,95,102,200]}])

st.subheader('Long Beach Harbor | Interactive harbour overview')
map_col,side_col=st.columns([3.3,1.2],gap='medium')
with map_col:
    layers=[pdk.Layer('ScatterplotLayer',terminals,get_position='[lon, lat]',get_fill_color='color',get_radius='radius',pickable=True),
            pdk.Layer('ScatterplotLayer',vessel_df,get_position='[lon, lat]',get_fill_color='color',get_radius='radius',pickable=True)]
    if scenario!='Normal operations':
        layers.append(pdk.Layer('ScatterplotLayer',incidents,get_position='[lon, lat]',get_fill_color='color',get_radius='radius',pickable=True))
    st.pydeck_chart(pdk.Deck(map_style='https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
        initial_view_state=pdk.ViewState(latitude=33.754,longitude=-118.218,zoom=12.3,pitch=0),layers=layers,
        tooltip={'html':'<b>{name}</b><br/>{kind}','style':{'backgroundColor':'#0c2237','color':'white'}}),height=490)
    st.caption('● Cyan: illustrative logistics marker  ·  ● Amber: public cargo facilities  ·  ● Blue: fictional vessel markers  ·  ● Red: fictional incident. Map positions are illustrative; not for navigation or security operations.')
with side_col:
    st.markdown('#### Harbour status')
    st.success('SIMULATED NORMAL' if scenario=='Normal operations' else 'HUMAN REVIEW REQUIRED')
    st.metric('Fictional vessels',len(vessel_df))
    st.metric('Illustrative facilities',len(terminals))
    st.metric('Exercise incidents',0 if scenario=='Normal operations' else 1)
    st.markdown('**Four public-facing facility references**')
    st.dataframe(terminals[['name','kind']],hide_index=True,use_container_width=True,height=190)

obs=d['synthetic_observations']
sub=obs[obs.fictional_zone==zone].copy().sort_values('observed_at')
sub=sub.iloc[:max(1,round(len(sub)*playback/100))].tail(12)
if replay and len(sub): sub=pd.concat([sub,sub.tail(3)],ignore_index=True)
before=len(sub)
sub=sub.drop_duplicates(subset=['event_id'],keep='first')
result=assess([] if sensor_down or scenario=='Sensor outage' else sub.to_dict('records'),not(sensor_down or scenario=='Sensor outage'),not policy_down)

st.subheader('Operations & incident intelligence')
t1,t2,t3,t4=st.tabs(['📊 Traffic & trends','🛡️ Incident assessment','📋 Evidence & data','🧪 Continuity stress test'])
with t1:
    vessel_data=d['synthetic_surface_vessels'].copy()
    date_col=next((c for c in vessel_data.columns if 'time' in c or 'date' in c),None)
    if date_col:
        vessel_data['day']=pd.to_datetime(vessel_data[date_col],errors='coerce').dt.date
        counts=vessel_data.groupby('day').size().rename('Synthetic vessel records')
        st.line_chart(counts.tail(90),height=270)
    else:
        st.bar_chart(vessel_data.select_dtypes(include='number').head(50))
    st.caption('Synthetic vessel record counts. These are not real AIS traffic measurements.')
with t2:
    a,b=st.columns([1,2])
    with a:
        st.markdown('**Deterministic CPU decision core**')
        st.warning(result.state)
        for reason in result.reasons: st.write('•',reason)
        st.metric('Duplicates filtered',before-len(sub))
    with b:
        st.markdown('**AI-assisted explanation (optional)**')
        if ai_down:
            st.info('AI offline. Deterministic explanation remains available.')
        else:
            st.info('Demo explanation (template, not a connected LLM): Observation identity remains unverified. Check evidence provenance and obtain authorized human review.')
        st.markdown('**Operator acknowledgment**')
        if 'ack' not in st.session_state: st.session_state.ack=False
        if st.button('Acknowledge for human review'):st.session_state.ack=True
        st.write('Acknowledged for review' if st.session_state.ack else 'Awaiting operator acknowledgment')
with t3:
    st.markdown('**Recent synthetic observations**')
    st.dataframe(sub[['event_id','observed_at','source_type','quality','delivery_status','provenance']],hide_index=True,use_container_width=True)
    st.markdown('**Dataset inventory**')
    st.dataframe(pd.DataFrame([{'file':k+'.csv','rows':len(v),'provenance':'SYNTHETIC'} for k,v in d.items()]),hide_index=True,use_container_width=True)
with t4:
    a,b=st.columns(2)
    with a:
        n=st.slider('Fictional vessels scheduled',5,60,20)
        affected=st.slider('Vessels affected in illustrative restricted-operations scenario',0,n,6)
    with b:
        delay=st.slider('Assumed delay per affected vessel (hours)',1,24,6)
        st.metric('Full suspension: vessel-delay hours',n*delay)
        st.metric('Illustrative partial restriction: vessel-delay hours',affected*delay,delta=f'{(affected-n)*delay:+d} vs full suspension')
    st.caption('Scenario arithmetic only, not a recommendation that partial restrictions are safe. All operating restrictions require independent authorized assessment.')

st.divider()
st.caption('Hackathon MVP • Public-facing terminal names; illustrative approximate display markers • All vessel positions, incidents, missions and sensor observations are synthetic • No actual naval surveillance, tracking or interdiction.')
