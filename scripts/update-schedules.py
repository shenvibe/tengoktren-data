import csv,zipfile,io,json,math,datetime
from collections import defaultdict
from pathlib import Path
import urllib.request, tempfile, os
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[1]
out=root/'dist'
feeds=tempfile.TemporaryDirectory()
for name,url in [('rapid','https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl'),('ktmb','https://api.data.gov.my/gtfs-static/ktmb')]:
 with urllib.request.urlopen(url,timeout=45) as response:
  blob=response.read(50_000_001)
 if len(blob)>50_000_000:raise ValueError('Feed exceeded size limit')
 target=Path(feeds.name)/(name+'.zip');target.write_bytes(blob)
 with zipfile.ZipFile(target) as z:
  for required in ['routes.txt','stops.txt','trips.txt','stop_times.txt']:
   if required not in z.namelist():raise ValueError('Missing '+required)

def read(z,f):return list(csv.DictReader(io.StringIO(z.read(f).decode('utf-8-sig')))) if f in z.namelist() else []
def secs(s):return sum(int(v)*m for v,m in zip(s.split(':'),[3600,60,1]))
def dist(a,b):return math.hypot((a[0]-b[0])*math.cos(math.radians(a[1])),a[1]-b[1])*111320
D={'routes':[],'stops':{},'trips':[],'calendar':[],'exceptions':[],'downloaded':datetime.datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat(),'sources':['https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl','https://api.data.gov.my/gtfs-static/ktmb']}
for agency in ['rapid','ktmb']:
 z=zipfile.ZipFile(Path(feeds.name)/(agency+'.zip')); pre=agency+'-';routes=read(z,'routes.txt'); allowed={r['route_id'] for r in routes if r['route_id']!='BRT'} if agency=='rapid' else {'KC05_KB18','KA15_KD19'}
 stops={r['stop_id']:r for r in read(z,'stops.txt')};times=defaultdict(list);shapes=defaultdict(list);freq=defaultdict(list)
 for r in read(z,'stop_times.txt'):times[r['trip_id']].append(r)
 for r in read(z,'shapes.txt'):shapes[r['shape_id']].append(r)
 for r in read(z,'frequencies.txt'):freq[r['trip_id']].append([secs(r['start_time']),secs(r['end_time']),int(r['headway_secs'])])
 for r in read(z,'calendar.txt'):r['service_id']=pre+r['service_id'];D['calendar'].append(r)
 for r in read(z,'calendar_dates.txt'):r['service_id']=pre+r['service_id'];D['exceptions'].append(r)
 for r in routes:
  if r['route_id'] in allowed:D['routes'].append({'id':pre+r['route_id'],'name':r['route_long_name'],'short':r['route_short_name'],'color':'#'+r['route_color'],'agency':agency,'geometry':'official' if agency=='rapid' else 'station links'})
 for t in read(z,'trips.txt'):
  if t['route_id'] not in allowed:continue
  st=sorted(times[t['trip_id']],key=lambda r:int(r['stop_sequence']))
  if len(st)<2:continue
  pts=[[float(r['shape_pt_lon']),float(r['shape_pt_lat'])] for r in sorted(shapes[t.get('shape_id','')],key=lambda r:int(r['shape_pt_sequence']))] if agency=='rapid' else []
  if not pts:pts=[[float(stops[r['stop_id']]['stop_lon']),float(stops[r['stop_id']]['stop_lat'])] for r in st]
  cum=[0]
  for a,b in zip(pts,pts[1:]):cum.append(cum[-1]+dist(a,b))
  ss=[];last=0
  for r in st:
   s=stops[r['stop_id']];p=[float(s['stop_lon']),float(s['stop_lat'])];i=min(range(last,len(pts)),key=lambda i:dist(pts[i],p));last=i
   sid=pre+r['stop_id'];D['stops'][sid]={'id':sid,'name':s['stop_name'],'coord':p,'routes':list(set(D['stops'].get(sid,{}).get('routes',[])+[pre+t['route_id']]))}
   ss.append([sid,secs(r['arrival_time']),secs(r['departure_time']),round(cum[i],1)])
  D['trips'].append({'id':pre+t['trip_id'],'route':pre+t['route_id'],'service':pre+t['service_id'],'headsign':t.get('trip_headsign') or D['stops'][ss[-1][0]]['name'],'points':pts,'distances':[round(v,1) for v in cum],'stops':ss,'frequencies':freq[t['trip_id']]})

# Compare actual timetable content, not ZIP timestamps or download date.
def canonical(d):
 d=json.loads(json.dumps(d));d.pop('downloaded',None)
 for stop in d['stops'].values():stop['routes']=sorted(stop['routes'])
 for name,key in [('routes','id'),('trips','id'),('calendar','service_id')]:d[name].sort(key=lambda r:r[key])
 d['exceptions'].sort(key=lambda r:(r['service_id'],r['date'],r['exception_type']))
 return d
if not D['routes'] or not D['trips'] or not D['calendar']:raise ValueError('Incomplete schedules; existing file preserved')
for t in D['trips']:
 if t['route'] not in {r['id'] for r in D['routes']}:raise ValueError('Unknown route')
 if len(t['points'])!=len(t['distances']) or any(b<a for a,b in zip(t['distances'],t['distances'][1:])):raise ValueError('Invalid route geometry')
 if any(s[2]<s[1] for s in t['stops']) or any(b[1]<a[2] for a,b in zip(t['stops'],t['stops'][1:])):raise ValueError('Invalid station times')
previous=json.loads((out/'data.json').read_text())
if canonical(previous)==canonical(D):print(json.dumps({'changed':False,'checked':D['downloaded']}))
else:
 temp=out/'data.json.next';temp.write_text(json.dumps(D,separators=(',',':')));os.replace(temp,out/'data.json')
 page=out/'index.html';text=page.read_text();import re
 date=datetime.date.fromisoformat(D['downloaded']).strftime('%-d %B %Y')
 text=re.sub(r'Train schedules: .*?; not updated automatically\.', 'Train schedules: '+date+'. Checked daily.',text)
 text=re.sub(r'Train schedules: .*?\. Checked daily\.', 'Train schedules: '+date+'. Checked daily.',text)
 page.write_text(text)
 print(json.dumps({'changed':True,'downloaded':D['downloaded'],'routes':len(D['routes']),'trips':len(D['trips'])}))
feeds.cleanup()
