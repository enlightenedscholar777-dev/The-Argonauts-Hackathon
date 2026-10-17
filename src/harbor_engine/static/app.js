"use strict";
let viewerToken = "", busy = false;
const byId = id => document.getElementById(id);
const node = (tag, text, cls) => {const el=document.createElement(tag); if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
const svgNode = (tag, attrs, text) => {const el=document.createElementNS("http://www.w3.org/2000/svg",tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text)el.textContent=text;return el;};
async function get(path){const response=await fetch(path,{headers:{Authorization:`Bearer ${viewerToken}`}});const value=await response.json();if(!response.ok)throw Error(value.error?.message||"Request failed");return value;}
function draw(data){
  const map=byId("map");map.replaceChildren();
  const [x0,y0,x1,y1]=data.bounds;map.setAttribute("viewBox",`${x0} ${y0} ${x1-x0} ${y1-y0}`);
  const flip=y=>y1-y+y0;
  Object.entries(data.zones).forEach(([id,z])=>{map.append(svgNode("polygon",{points:z.vertices.map(([x,y])=>`${x},${flip(y)}`).join(" "),class:z.kind}));map.append(svgNode("text",{x:z.vertices[0][0],y:flip(z.vertices[0][1])+25},id));});
  const cards=byId("tracks");cards.replaceChildren();
  if(!data.tracks.length)cards.append(node("p","No observations received. Coverage is unknown."));
  data.tracks.forEach(a=>{
    map.append(svgNode("polyline",{points:a.forecast.points.map(p=>`${p.x_m},${flip(p.y_m)}`).join(" "),class:"forecast"}));
    map.append(svgNode("circle",{cx:a.estimate.x_m,cy:flip(a.estimate.y_m),r:7,class:"track"}));
    map.append(svgNode("text",{x:a.estimate.x_m+12,y:flip(a.estimate.y_m)-10},a.track_id));
    const card=node("article",undefined,`card ${a.risk.current_band}`);
    card.append(node("h2",`${a.track_id} · ${a.risk.current_band}`));
    card.append(node("p",a.recommendation.primary_action));
    card.append(node("p",`Authorization ${a.authorization.status} · ${a.capability.data_quality} · Source ${a.capability.source_health} · Observation age ${a.source.observation_age_seconds.toFixed(1)}s`,"facts"));
    card.append(node("p",`Position (${a.estimate.x_m.toFixed(1)}, ${a.estimate.y_m.toFixed(1)}) m · Last observed ${a.last_observed_at} · Revision ${a.core_revision}`,"facts"));
    card.append(node("p",a.recommendation.deterministic_explanation));
    a.evidence.filter(e=>e.type==="operator_note").forEach(e=>card.append(node("p",`Untrusted note from ${e.actor}: ${e.text}`,"facts")));
    card.append(node("p",`Incident: ${a.incident?.state||"none"}${a.incident?.handoff_required?" · Outstanding human handoff":""}`,"facts"));
    card.append(node("p",`Next evidence (${a.recommendation.ranking_method}): ${a.recommendation.eligible_next_evidence.join(", ")||"none available within horizon"}`,"facts"));
    if(a.ai_enrichment){const e=a.ai_enrichment;card.append(node("p",`AI explanation — review against evidence · ${e.model} · basis age ${e.basis_age_seconds.toFixed(1)}s: ${e.response.summary}`,"ai"));}
    cards.append(card);
  });
}
async function poll(){if(!viewerToken||busy)return;busy=true;try{const status=await get("/v1/status");byId("error").textContent="";byId("status").textContent=`Core ${status.core} · Storage ${status.storage} · AI ${status.ai.status}${status.ai.mock?" / MOCK":""}`;
  if(status.active_session_id){const data=await get(`/v1/sessions/${status.active_session_id}/snapshot`);byId("status").textContent+=`\n${data.session.name} · ${data.session.clock_mode} · ${data.session.current_time}\n${data.policy_assumptions}${data.simulated_faults.length?"\nSIMULATED FAULT: "+data.simulated_faults.join(", "):""}`;draw(data);}
  else{byId("status").textContent+="\nNo active session. Start the HTTP simulator.";byId("tracks").replaceChildren(node("p","No active session. Coverage is unknown."));byId("map").replaceChildren();}
}catch(error){byId("error").textContent=`Connection unavailable: ${error.message}. Displayed data may be stale.`;}finally{busy=false;}}
byId("connect").addEventListener("submit",event=>{event.preventDefault();viewerToken=byId("token").value;byId("token").value="";poll();});
setInterval(poll,1000);
