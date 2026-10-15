export const rub = n => new Intl.NumberFormat('ru-RU', {maximumFractionDigits:0}).format(n) + ' ₽';
export const clone = x => JSON.parse(JSON.stringify(x));
const day = 86400000;
export function dateValue(s) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s || '')) throw new Error('Укажите дату');
  const n = Date.parse(s+'T00:00:00Z');
  if (!Number.isFinite(n) || new Date(n).toISOString().slice(0,10)!==s) throw new Error('Неверная дата');
  return n;
}
export const nights = (a,b) => (dateValue(b)-dateValue(a))/day;
export const shift = (d,n) => new Date(dateValue(d)+n*day).toISOString().slice(0,10);
export function amount(n) {
  if (!Number.isFinite(n) || n<0 || n>100000000) throw new Error('Нужна неотрицательная цена');
  return n;
}
export const itemCost = i => i.parts?.length ? i.parts.reduce((s,p)=>s+amount(p.amount),0) : amount(i.amount || 0);
export function calculate(model) {
  const s=model.settings, input=model.phases;
  if (!input?.length) throw new Error('Добавьте фазу');
  Object.values(s).forEach(amount);
  let previous=null;
  const warnings=[];
  const rows=input.map((p,i)=>{
    if(!/^[a-z][a-z0-9-]{0,59}$/.test(p.id))throw new Error('Неверный идентификатор фазы');
    if(typeof p.base!=='boolean')throw new Error('Укажите тип остановки');
    for(const x of p.items){
      if(!/^[a-z][a-z0-9-]{0,59}$/.test(x.id))throw new Error('Неверный идентификатор расхода');
      if(!['fixed','leisure','sport','restaurant','included'].includes(x.bucket))throw new Error('Неверная группа расходов');
    }
    const n=nights(p.start,p.end);
    if (n<=0 || (previous && previous!==p.start)) throw new Error('Фазы должны идти подряд; выезд позже заезда');
    previous=p.end;
    const days=n+(i===input.length-1 ? 1:0);
    const chosen=p.items.filter(x=>x.selected);
    chosen.forEach(x=>{if(x.unknown) warnings.push(p.title+': '+x.title+' — цена не подтверждена');});
    if (p.flight.unknown) warnings.push(p.title+': багаж или полная цена рейса требуют проверки');
    for(const x of chosen) if(x.eventDate && (x.eventDate<p.start || x.eventDate>=p.end)) warnings.push(p.title+': старт '+x.eventDate+' не попадает в даты фазы');
    const excluded=chosen.reduce((v,x)=>v+amount(x.excludedDays||0),0);
    const baseDays=p.base ? Math.max(0,days-excluded):0;
    const planned=chosen.filter(x=>x.bucket==='leisure').reduce((v,x)=>v+itemCost(x),0);
    const allowance=s.leisureWeek*baseDays/7;
    const localLeisure=p.base ? Math.max(allowance,planned):planned;
    const fixed=chosen.filter(x=>x.bucket==='fixed').reduce((v,x)=>v+itemCost(x),0);
    const sport=chosen.filter(x=>x.bucket==='sport').reduce((v,x)=>v+itemCost(x),0);
    const food=s.foodWeek*days/7, household=s.householdWeek*days/7;
    const transport=s.transportWeek*baseDays/7;
    const includedNights=amount(p.includedHousingNights||0);
    if(includedNights>n)throw new Error('Включённых ночей больше длительности фазы');
    const housing=amount(p.nightRate)*(n-includedNights);
    const local=housing+food+household+transport+localLeisure+fixed;
    return {id:p.id,title:p.title,country:p.country,start:p.start,end:p.end,days,nights:n,baseDays,
      flight:amount(p.flight.amount),from:p.flight.from,housing,food,household,transport,
      allowance,planned,localLeisure,free:Math.max(0,allowance-planned),overflow:Math.max(0,planned-allowance),
      fixed,sport,local,total:local+p.flight.amount};
  });
  const days=nights(input[0].start,input.at(-1).end)+1;
  if(days>731) throw new Error('Срок не больше двух лет');
  const dinners=input.flatMap(p=>p.items).filter(x=>x.selected&&x.bucket==='restaurant');
  const includedVisits=input.flatMap(p=>p.items).filter(x=>x.selected&&x.bucket==='included').reduce((n,x)=>n+amount(x.includedRestaurantVisits||0),0);
  const target=Math.max(0,Math.round(s.restaurantFrequency*days/7)-includedVisits);
  const restaurantCount=Math.max(target,dinners.length);
  const restaurants=dinners.reduce((v,x)=>v+itemCost(x),0)+Math.max(0,target-dinners.length)*s.restaurantPrice;
  const sport=rows.reduce((v,x)=>v+x.sport,0);
  const other=s.common+s.shopping+restaurants+sport;
  const total=rows.reduce((v,x)=>v+x.total,0)+amount(model.returnFlight.amount)+other;
  return {rows,days,nights:days-1,total,restaurants,restaurantCount,sport,other,warnings,
    flights:rows.reduce((v,x)=>v+x.flight,0)+model.returnFlight.amount,
    leisure:{budget:rows.reduce((v,x)=>v+x.allowance,0),planned:rows.reduce((v,x)=>v+x.planned,0),
      free:rows.reduce((v,x)=>v+x.free,0),overflow:rows.reduce((v,x)=>v+x.overflow,0)}};
}

export function changeStart(model,index,value) {
  dateValue(value);
  if(index===0) {
    const delta=nights(model.phases[0].start,value);
    model.phases.forEach(p=>{p.start=shift(p.start,delta);p.end=shift(p.end,delta);});
  } else {model.phases[index-1].end=value;model.phases[index].start=value;}
}
export function changeEnd(model,index,value) {
  const delta=nights(model.phases[index].end,value);
  model.phases[index].end=value;
  model.phases.slice(index+1).forEach(p=>{p.start=shift(p.start,delta);p.end=shift(p.end,delta);});
}
export function shortDate(s){return new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(dateValue(s)));}

export function drawPNG(canvas,model,result) {
  const width=1840,height=600+(result.rows.length+1)*93+340;
  canvas.width=width;canvas.height=height;
  const c=canvas.getContext('2d');c.fillStyle='#f5f3ef';c.fillRect(0,0,width,height);
  const text=(x,y,s,size=25,bold=false)=>{c.fillStyle='#243238';c.font=`${bold?'600':'400'} ${size}px Arial`;c.fillText(s,x,y);};
  const first=model.phases[0],last=model.phases.at(-1);
  text(60,65,'План на зимовку · '+shortDate(first.start)+' — '+shortDate(last.end)+' '+last.end.slice(0,4),43,true);
  text(60,125,'Весь план: '+rub(result.total)+' на двоих',41,true);
  text(60,200,'Где живём и сколько это стоит',31,true);
  const xs=[60,540,810,915,1135,1350,1580];
  ['Этап','Даты','Дней','Перелёт сюда','На месте','₽/день','Итого'].forEach((v,i)=>text(xs[i],255,v,23,true));
  let y=300;
  for(const [i,r] of result.rows.entries()){
    if(i%2===0){c.fillStyle='#e7ece9';c.fillRect(45,y-30,1750,85);}
    const label=r.title+', '+r.country;
    let size=24;c.font='600 '+size+'px Arial';while(c.measureText(label).width>460&&size>16){size--;c.font='600 '+size+'px Arial';}text(60,y,label,size,true);
    text(60,y+31,r.from.length>48?r.from.slice(0,47)+'…':r.from,17);
    const vals=[shortDate(r.start)+' – '+shortDate(r.end),r.days,r.flight?rub(r.flight):'—',rub(r.local),rub(r.local/r.days),rub(r.total)];
    vals.forEach((v,i)=>text(xs[i+1],y+8,String(v),23,i===5));y+=93;
  }
  text(60,y,'Обратные билеты в Петербург',25,true);text(60,y+31,model.returnFlight.from,17);
  text(540,y+8,shortDate(last.end),24);text(915,y+8,rub(model.returnFlight.amount),24);text(1580,y+8,rub(model.returnFlight.amount),24,true);y+=100;
  text(60,y,'Отдельные статьи — уже входят в общий итог',30,true);y+=55;
  for(const [label,value] of [['Рестораны',result.restaurants],['Соревнования и велосипед',result.sport],['Связь, страховка, обменные комиссии и мелкие непредвиденные',model.settings.common],['Шопинг',model.settings.shopping]]){
    text(70,y,label,25);text(1580,y,rub(value),25,true);y+=46;
  }
  y+=20;c.strokeStyle='#bdc9c6';c.beginPath();c.moveTo(60,y);c.lineTo(1790,y);c.stroke();y+=50;
  text(60,y,'Ставки расчёта · на двоих',28,true);y+=43;
  const rates=[...new Map(model.phases.filter(p=>p.base).map(p=>[p.title,p.nightRate])).entries()].map(([k,v])=>k+' '+rub(v)).join(' · ');
  text(60,y,'Жильё за ночь: '+rates,23);y+=36;
  text(60,y,'Еда и кофе '+rub(model.settings.foodWeek)+'/нед. · Быт '+rub(model.settings.householdWeek)+'/нед.',23);y+=36;
  text(60,y,'Городской транспорт '+rub(model.settings.transportWeek)+'/нед. · Городской досуг '+rub(model.settings.leisureWeek)+'/нед.',23);y+=36;
  text(60,y,'Рестораны: '+model.settings.restaurantFrequency+' раза в неделю · '+rub(model.settings.restaurantPrice)+' за выход.',23);
}
