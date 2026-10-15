export const rub = n => new Intl.NumberFormat('ru-RU', {maximumFractionDigits:0}).format(n) + ' ₽';
export const clone = x => JSON.parse(JSON.stringify(x));
export class ModelHistory {
  constructor(){this.past=[];this.future=[];}
  record(before,after){if(JSON.stringify(before)===JSON.stringify(after))return;this.past.push(clone(before));this.future=[];}
  undo(current){if(!this.past.length)return null;this.future.push(clone(current));return this.past.pop();}
  redo(current){if(!this.future.length)return null;this.past.push(clone(current));return this.future.pop();}
}
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
  const width=900,pad=40,right=width-pad;
  canvas.width=width;
  const measure=canvas.getContext('2d'),ops=[];
  let y=54;
  const font=(size,bold)=>`${bold?'600':'400'} ${size}px Arial`;
  function lines(value,size,bold,maxWidth){
    measure.font=font(size,bold);
    const out=[];let line='';
    for(const word of String(value).split(' ')){
      const next=line?line+' '+word:word;
      if(line&&measure.measureText(next).width>maxWidth){out.push(line);line=word;}else line=next;
    }
    if(line)out.push(line);
    return out;
  }
  function full(value,size=32,bold=false,color='#243238'){
    for(const line of lines(value,size,bold,right-pad)){
      ops.push({type:'text',x:pad,y,value:line,size,bold,color});y+=Math.ceil(size*1.25);
    }
  }
  function pair(label,value,size=32,bold=false){
    measure.font=font(size,bold);
    const valueWidth=measure.measureText(value).width;
    const wrapped=lines(label,size,bold,right-pad-valueWidth-28);
    ops.push({type:'text',x:right-valueWidth,y,value,size,bold,color:'#243238'});
    for(const line of wrapped){ops.push({type:'text',x:pad,y,value:line,size,bold,color:'#243238'});y+=Math.ceil(size*1.25);}
  }
  full('План на зимовку',42,true);
  const first=model.phases[0],last=model.phases.at(-1);
  full(shortDate(first.start)+' — '+shortDate(last.end)+' '+last.end.slice(0,4),34);
  y+=18;
  ops.push({type:'rect',x:0,y:y-33,w:width,h:143,color:'#28666c'});
  full('Весь план на двоих',34,true,'#ffffff');
  full(rub(result.total),50,true,'#ffffff');
  y+=35;
  for(const [index,r] of result.rows.entries()){
    const begin=y-35,bg=ops.length;
    full(r.title+' · '+r.country,36,true);
    full(shortDate(r.start)+' — '+shortDate(r.end)+' · '+r.days+' дн.',32);
    if(r.flight)pair(r.from,rub(r.flight));
    else if(model.phases[index].flight.from.startsWith('Автобус '))full(model.phases[index].flight.from,32);
    pair('На месте',rub(r.local));
    pair(rub(r.local/r.days)+'/день','Всего '+rub(r.total),32,true);
    y+=28;
    ops.splice(bg,0,{type:'rect',x:0,y:begin,w:width,h:y-begin-12,color:index%2===0?'#e7ece9':'#f5f3ef'});
  }
  y+=5;
  full('Обратно в Петербург',36,true);
  pair(shortDate(last.end),rub(model.returnFlight.amount),34,true);
  y+=30;
  full('Отдельные статьи',36,true);
  for(const [label,value] of [['Рестораны',result.restaurants],['Соревнования и велосипед',result.sport],['Связь, страховка, комиссии и прочее',model.settings.common],['Шопинг',model.settings.shopping]])pair(label,rub(value));
  y+=28;
  full('Ставки на двоих',36,true);
  full('Жильё за ночь',32,true);
  const rates=[...new Map(model.phases.map(p=>[p.title,p.nightRate])).entries()].map(([k,v])=>k+' '+rub(v));
  for(let i=0;i<rates.length;i+=2)full(rates.slice(i,i+2).join(' · '));
  y+=12;
  full('Еда и кофе '+rub(model.settings.foodWeek)+'/нед.');
  full('Быт '+rub(model.settings.householdWeek)+' · Транспорт '+rub(model.settings.transportWeek)+'/нед.');
  full('Досуг '+rub(model.settings.leisureWeek)+'/нед.');
  full('Рестораны '+model.settings.restaurantFrequency+' раза/нед. · чек '+rub(model.settings.restaurantPrice));
  canvas.height=y+28;
  const c=canvas.getContext('2d');c.fillStyle='#f5f3ef';c.fillRect(0,0,width,canvas.height);
  for(const op of ops){
    c.fillStyle=op.color;
    if(op.type==='rect')c.fillRect(op.x,op.y,op.w,op.h);
    else{c.font=font(op.size,op.bold);c.fillText(op.value,op.x,op.y);}
  }
}
