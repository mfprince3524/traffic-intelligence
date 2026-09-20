from fastapi import FastAPI
app=FastAPI(title='Evidence Explanation Service')
@app.post('/explain')
def explain(b:dict):
 r=b.get('route',{}); bits=[]
 if 'avg_congestion_pct' in r:bits.append(f"average congestion {r['avg_congestion_pct']}%")
 if 'travel_time_min' in r:bits.append(f"estimated travel time {r['travel_time_min']} minutes")
 return {'explanation':'Recommendation is based on '+(' and '.join(bits) if bits else 'available traffic/network evidence')+'.','evidence_based':True,'llm_used':False}
