"""Loopback-only preview; all records in this database are synthetic."""
import os,sys,base64,tomllib,uuid
from datetime import datetime,timezone
from pathlib import Path

import argparse
parser=argparse.ArgumentParser(description='Loopback finance demo with synthetic records')
parser.add_argument('--data-dir',type=Path,default=Path('D:/Codex/temp/finance-fact-preview') if os.name=='nt' else Path('/tmp/edabalans-finance-demo'))
parser.add_argument('--port',type=int,default=8768)
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]
args.data_dir.mkdir(parents=True,exist_ok=True)
DB=args.data_dir/'demo.sqlite3'
os.environ['DATABASE_URL']='sqlite:///'+str(DB)
os.environ['ADMIN_USERNAME']='demo@example.com'
os.environ['ADMIN_PASSWORD']='local-demo-only'
sys.path.insert(0,str(ROOT/'backend'))
from fastapi import FastAPI
from fastapi.responses import FileResponse,HTMLResponse,JSONResponse
from sqlalchemy import select
from app.app_routes import router as app_router
from app.crm_routes import router as crm_router
from app.access_routes import router as access_router
from app.database import Base,engine,SessionLocal
from app.models import User,Product,Payment,MessengerAccount,TelegramTrackingEvent,ManagedDocumentVersion
from app.managed_documents import document_hash

Base.metadata.create_all(engine)
def dt(value):return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
with SessionLocal() as db:
 if not db.scalar(select(User.id).limit(1)):
  first_dates=['2026-09-05','2026-09-10','2026-08-01','2026-10-05','2026-10-10','2026-10-12']
  people=[User(display_name='Пример · клиент '+str(i+1),first_seen_at=dt(value+'T12:00:00')) for i,value in enumerate(first_dates)]
  db.add_all(people);db.flush()
  names={'MASTERCLASS_BASIC':'Минимальный','MASTERCLASS_RECIPES':'Стандартный','MASTERCLASS_CONSULT':'С консультацией','RECIPES_ADDON':'Система рецептов','COACHING':'Сопровождение','CONSULTATION':'Разовый разбор'}
  products={code:Product(code=code,name=name) for code,name in names.items()};db.add_all(products.values());db.flush()
  for i,person in enumerate(people):
   bot_date='2026-10-03' if i==2 else first_dates[i]
   db.add(MessengerAccount(user_id=person.id,platform='telegram',platform_user_id=str(100+i),source='demo',
       first_seen_at=person.first_seen_at,main_scenario_seen_at=None if i==0 else dt(bot_date+'T12:00:00')))
  db.add(MessengerAccount(user_id=people[0].id,platform='max',platform_user_id='500',source='demo',
       first_seen_at=dt('2026-10-01T12:00:00'),main_scenario_seen_at=dt('2026-10-01T12:00:00')))
  def event(who,date,medium='organic',platform='telegram',kind='start_first',external=None,**details):
   db.add(TelegramTrackingEvent(user_id=who.id if who else None,telegram_user_id=external,event_type=kind,
    occurred_at=dt(date),metadata_json={'messenger':platform,'max_delivery_status':'sent',
       'raw_query':{'utm_source':'pikabu','utm_medium':medium},**details}))
  event(people[0],'2026-09-05T12:00:00','cpc',kind='channel_membership',joined=True,subscribed=True)
  event(people[0],'2026-10-01T12:00:00','cpc',platform='max')
  event(people[1],'2026-09-10T12:00:00','organic')
  event(None,'2026-09-20T12:00:00',external='700',kind='channel_join')
  event(people[2],'2026-10-03T12:00:00','cpc')
  event(people[3],'2026-10-05T12:00:00','organic')
  event(people[4],'2026-10-10T12:00:00','cpc')
  event(people[5],'2026-10-12T12:00:00','unknown')
  def pay(who,date,amount,code=None,price=None,**extra):
   db.add(Payment(user_id=who.id if who else None,product_id=products[code].id if code else None,
       source='demo',paid_at=dt(date),amount=amount,currency='RUB',product_name_raw=names.get(code,'Свободная оплата'),
       payment_status='paid',price_entry_code=price,**extra))
  pay(people[0],'2026-09-20T12:00:00',7800,'MASTERCLASS_BASIC')
  pay(people[0],'2026-09-25T12:00:00',14000,price='subscription.coaching.monthly')
  pay(people[0],'2026-10-20T12:00:00',14000,price='subscription.coaching.monthly')
  pay(people[1],'2026-10-17T12:00:00',3400,'RECIPES_ADDON')
  pay(people[1],'2026-10-19T12:00:00',14000,'COACHING',price='manual.payment')
  pay(people[2],'2026-08-01T12:00:00',7800,'MASTERCLASS_BASIC')
  pay(people[2],'2026-10-05T12:00:00',7500,'CONSULTATION')
  pay(people[3],'2026-10-15T12:00:00',9800,'MASTERCLASS_RECIPES')
  pay(people[3],'2026-10-18T12:00:00',5400,'RECIPES_ADDON')
  pay(people[4],'2026-10-14T12:00:00',19800,'MASTERCLASS_CONSULT')
  pay(None,'2026-10-21T12:00:00',4300,price='manual.payment')
  pay(people[5],'2026-10-16T12:00:00',1000,paid_at_is_estimated=True)
  for month,ads,opex in [('2026-09',6000,2000),('2026-10',8000,3000)]:
   payload={'month':month,'ads':ads,'opex':opex}
   db.add(ManagedDocumentVersion(document_type='finance-month-expenses',document_key=str(uuid.uuid4()),schema_version=1,
     version_no=1,payload=payload,content_hash=document_hash(payload),created_by='demo',is_active=True))
  db.commit()

app=FastAPI()
app.include_router(app_router);app.include_router(crm_router);app.include_router(access_router)
@app.middleware('http')
async def local_auth(request,call_next):
 if request.method not in ('GET','HEAD') and not (request.url.path=='/admin/api/finance/expenses' or request.url.path.startswith('/admin/api/finance/plans')):
  return JSONResponse({'detail':'В демонстрационной CRM доступен только просмотр'},status_code=403)
 headers=list(request.scope['headers']);headers.append((b'authorization',b'Basic '+base64.b64encode(b'demo@example.com:local-demo-only')))
 request.scope['headers']=headers
 response=await call_next(request)
 if request.url.path=='/finance' and request.query_params.get('preview_mode') in ('month','all'):
  content=b''.join([chunk async for chunk in response.body_iterator]).decode()
  mode=request.query_params['preview_mode']
  content=content.replace('</body>',f'''<script>document.querySelector('[data-finance-mode="{mode}"]').click();</script></body>''')
  response=HTMLResponse(content,headers={'Cache-Control':'no-store'})
 response.headers['X-Finance-Demo']='1'
 return response
@app.get('/admin/api/navigation')
def navigation():
 return {'modules':tomllib.loads((ROOT/'docs/modules.toml').read_text(encoding='utf8'))['modules']}
@app.get('/favicon.png')
def favicon():return FileResponse(ROOT/'backend/app/static/brand/favicon.png')
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
