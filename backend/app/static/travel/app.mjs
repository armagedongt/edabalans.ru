import {calculate,clone,rub,itemCost,changeStart,changeEnd,shift,drawPNG} from './calc.mjs';
const root=document.querySelector('#app');
let model,revision,dirty=false,article=null,saving=false;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL=u=>{try{const x=new URL(u);return x.protocol==='https:'||x.protocol==='http:'?x.href:'';}catch{return '';}};
const api='/admin/api/travel';
const phaseId=location.pathname.includes('/phases/')?location.pathname.split('/').at(-1):null;
function msg(message,error=false){const n=document.querySelector('#message');if(n){n.textContent=message;n.className=error?'error':'success';}}
async function request(path,options={}){
  const r=await fetch(api+path,{credentials:'same-origin',...options});
  if(r.status===401){location.href='/admin?next='+encodeURIComponent(location.pathname);throw new Error('Нужен вход');}
  const data=await r.json();
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос');
  return data;
}
function current(){return calculate(model);}
function edit(fn){const previous=clone(model);try{fn();current();dirty=true;render();msg('Есть несохранённые изменения');}catch(e){model=previous;render();msg(e.message,true);}}
const categories={fixed:'Отдельная программа',leisure:'Из городского бюджета',sport:'Соревнования и велосипед',restaurant:'Ресторанный план',included:'Уже включено в пакет'};

function render(){
  const result=current();
  if(phaseId){renderPhase(result);return;}
  root.innerHTML=`<div class="toolbar"><a class="button" href="/admin">← Админка</a><button class="primary" id="save">Сохранить</button><button id="png">Картинка для Сони</button><button id="json">Скачать JSON</button><button id="import">Открыть JSON</button></div>
  <h1>План на зимовку</h1><div class="toolbar"><label>Начало <input id="start" type="date" value="${esc(model.phases[0].start)}"></label><label>Окончание <input id="end" type="date" value="${esc(model.phases.at(-1).end)}"></label><span>${result.days} дней / ${result.nights} ночей · двое</span></div>
  <div class="total">Весь план: <span id="total">${rub(result.total)}</span> на двоих</div><div id="message" role="status"></div>
  <div class="table-wrap"><table><thead><tr><th>Фаза</th><th>Заезд</th><th>Выезд</th><th>Дней</th><th>Перелёт сюда, ₽</th><th>Жильё / ночь, ₽</th><th>На месте</th><th>₽ / день</th><th>Итого</th><th>План</th></tr></thead><tbody>
  ${model.phases.map((p,i)=>{const r=result.rows[i];return `<tr><td class="stage"><strong>${esc(p.title)}, ${esc(p.country)}</strong><small>${esc(p.flight.from)}</small><button class="remove" data-remove="${i}">Убрать фазу</button></td><td><input aria-label="Заезд ${esc(p.title)}" type="date" value="${p.start}" data-start="${i}"></td><td><input aria-label="Выезд ${esc(p.title)}" type="date" value="${p.end}" data-end="${i}"></td><td>${r.days}</td><td><input aria-label="Перелёт ${esc(p.title)}" type="number" min="0" value="${p.flight.amount}" data-flight="${i}"></td><td><input aria-label="Ночь ${esc(p.title)}" type="number" min="0" value="${p.nightRate}" data-night="${i}"></td><td class="number">${rub(r.local)}</td><td class="number">${rub(r.local/r.days)}</td><td class="number"><b>${rub(r.total)}</b></td><td><button data-open="${esc(p.id)}">Посмотреть план →</button></td></tr>`;}).join('')}
  <tr><td colspan="4"><b>Обратные билеты в Петербург</b><small class="muted"> · ${esc(model.returnFlight.from)}</small></td><td><input id="return" aria-label="Обратные билеты" type="number" min="0" value="${model.returnFlight.amount}"></td><td colspan="4"></td><td><b>${rub(model.returnFlight.amount)}</b></td></tr></tbody></table></div>
  <p><button id="add">+ Добавить фазу</button></p>
  <h2>Городской досуг</h2><p class="muted">Только дни жизни в Бангкоке, на Пхукете и в Нячанге. Выбранные spa, лодки и входы расходуют этот же бюджет. Большие поездки посчитаны отдельно.</p>
  <div class="leisure"><div>Бюджет<b>${rub(result.leisure.budget)}</b></div><div>Уже запланировано<b>${rub(result.leisure.planned)}</b></div><div>Пока свободно<b>${rub(result.leisure.free)}</b></div><div class="over">Превышение<b>${rub(result.leisure.overflow)}</b></div></div>
  <div class="table-wrap"><table><thead><tr><th>Остановка</th><th>Городских дней</th><th>Бюджет</th><th>Выбрано</th><th>Свободно</th><th>Превышение</th></tr></thead><tbody>${result.rows.filter(r=>r.baseDays).map(r=>`<tr><td>${esc(r.title)}</td><td>${r.baseDays}</td><td>${rub(r.allowance)}</td><td>${rub(r.planned)}</td><td>${rub(r.free)}</td><td>${rub(r.overflow)}</td></tr>`).join('')}</tbody></table></div>
  <h2>Настройки расходов</h2><div class="settings">${[
    ['foodWeek','Еда и кофе / неделю',30000,500],['householdWeek','Бытовые покупки / неделю',7000,100],['transportWeek','Незапланированный городской транспорт / неделю',15000,100],['leisureWeek','Городской досуг / неделю',30000,500],['restaurantFrequency','Ресторанов / неделю',7,.5],['restaurantPrice','Один ресторан на двоих',15000,500],['common','Связь, страховка, обмен и мелкие непредвиденные',100000,1000],['shopping','Шопинг за весь отпуск',150000,1000]
  ].map(([key,label,max,step])=>`<div class="setting"><label for="n-${key}">${label}</label><div class="line"><input id="n-${key}" data-setting="${key}" type="number" min="0" step="${step}" value="${model.settings[key]}"><span>${key==='restaurantFrequency'?'раза':'₽'}</span></div><input aria-label="${label}" data-slider="${key}" type="range" min="0" max="${Math.max(max,model.settings[key])}" step="${step}" value="${model.settings[key]}"></div>`).join('')}</div>
  <h2>Отдельные статьи — уже внутри общего итога</h2><table class="expenses"><tbody>${[['Рестораны · '+result.restaurantCount+' выходов',result.restaurants],['Соревнования и велосипед',result.sport],['Связь, страховка, обмен и мелкие непредвиденные',model.settings.common],['Шопинг',model.settings.shopping]].map(([a,b])=>`<tr><td>${a}</td><td class="number"><b>${rub(b)}</b></td></tr>`).join('')}</tbody></table>
  <div class="legend"><b>Как разделены расходы</b><br>Еда включает кофе и простую готовую еду на все дни поездки. Ресторанные вечера — отдельный план.<br>Быт — порошок, паста и другие повседневные покупки.<br>Недельный транспорт — только незапланированные городские поездки и доставка как услуга.<br>Все уже известные такси, переезды, входы и экскурсии находятся в пунктах фаз. Если транспорт включён в тур, второй оплаты нет.<br>Суммы с неподтверждёнными ценами — оценки; изменение дат не подтверждает тарифы заново.</div>
  ${result.warnings.length?`<h2>Что ещё проверить</h2><ul class="muted">${result.warnings.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<canvas id="export-canvas"></canvas>`;
  bindCommon();
  root.querySelector('#start').onchange=e=>edit(()=>changeStart(model,0,e.target.value));
  root.querySelector('#end').onchange=e=>edit(()=>changeEnd(model,model.phases.length-1,e.target.value));
  root.querySelectorAll('[data-start]').forEach(n=>n.onchange=()=>edit(()=>changeStart(model,+n.dataset.start,n.value)));
  root.querySelectorAll('[data-end]').forEach(n=>n.onchange=()=>edit(()=>changeEnd(model,+n.dataset.end,n.value)));
  root.querySelectorAll('[data-flight]').forEach(n=>n.onchange=()=>edit(()=>model.phases[+n.dataset.flight].flight.amount=+n.value));
  root.querySelectorAll('[data-night]').forEach(n=>n.onchange=()=>edit(()=>model.phases[+n.dataset.night].nightRate=+n.value));
  root.querySelector('#return').onchange=e=>edit(()=>model.returnFlight.amount=+e.target.value);
  root.querySelectorAll('[data-setting],[data-slider]').forEach(n=>n.onchange=()=>edit(()=>model.settings[n.dataset.setting||n.dataset.slider]=+n.value));
  root.querySelectorAll('[data-open]').forEach(n=>n.onclick=async()=>{if(dirty){await save();if(dirty)return;}location.href='/admin/travel/phases/'+n.dataset.open;});
  root.querySelectorAll('[data-remove]').forEach(n=>n.onclick=()=>edit(()=>{const i=+n.dataset.remove;if(model.phases.length===1)throw new Error('Нужна хотя бы одна фаза');const removed=model.phases[i];model.phases.splice(i,1);if(i>0&&i<model.phases.length)model.phases[i].start=removed.start;else if(i===0)model.phases[0].start=removed.start;}));
  root.querySelector('#add').onclick=()=>{
    const title=prompt('Город новой фазы');if(!title)return;const country=prompt('Страна');if(!country)return;
    edit(()=>{const start=model.phases.at(-1).end;model.phases.push({id:'phase-'+Date.now().toString(36),title,country,start,end:shift(start,3),base:false,nightRate:3000,flight:{from:'Из предыдущей фазы',amount:0,unknown:true},items:[]});});
  };
  root.querySelector('#png').onclick=()=>{const canvas=document.querySelector('#export-canvas');drawPNG(canvas,model,current());canvas.toBlob(b=>download(b,'План зимовки.png'));};
  root.querySelector('#import').onclick=()=>{const input=document.createElement('input');input.type='file';input.accept='.json';input.onchange=async()=>{try{const value=JSON.parse(await input.files[0].text());edit(()=>model=value.model||value);}catch(e){msg('Некорректный JSON: '+e.message,true);}};input.click();};
}

async function save(){
  if(saving)return;
  const submitted=JSON.stringify(model);saving=true;
  try{current();msg('Сохраняем…');const answer=await request('/plan',{method:'PUT',headers:{'Content-Type':'application/json','X-Travel-Write':'1'},body:JSON.stringify({model,revision})});revision=answer.revision;dirty=JSON.stringify(model)!==submitted;msg(dirty?'Сохранена предыдущая версия; новые изменения ещё не сохранены':'Сохранено на сервере');}
  catch(e){msg(e.message+' Изменения остались в форме; можно скачать JSON.',true);}
  finally{saving=false;}
}
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function bindCommon(){document.querySelector('#save').onclick=save;document.querySelector('#json').onclick=()=>download(new Blob([JSON.stringify({model,revision},null,2)],{type:'application/json'}),'travel-plan.json');}

function renderPhase(result){
  const index=model.phases.findIndex(p=>p.id===phaseId);
  if(index<0)throw new Error('Фаза не найдена');
  const p=model.phases[index],r=result.rows[index];
  const sections=article.sections;
  const all=[...sections];
  p.items.filter(i=>!all.some(s=>s.id===i.id)).forEach(i=>all.push({id:i.id,title:i.title,html:'<p>Подробности ещё не заполнены.</p>'}));
  root.innerHTML=`<div class="toolbar"><button id="back">← Калькулятор</button><button class="primary" id="save">Сохранить</button><button id="json">Скачать JSON</button></div><h1>${esc(p.title)}, ${esc(p.country)}</h1><p class="lead">${esc(p.start)} — ${esc(p.end)} · ${r.nights} ночей · ${rub(r.local)} на месте</p><div id="message" role="status"></div><div class="phase-list">${all.map(section=>{
    const item=p.items.find(i=>i.id===section.id);
    const price=section.id==='housing'?r.housing:section.id==='flight'?p.flight.amount:item?itemCost(item):null;
    return `<details id="item-${esc(section.id)}"><summary><span class="title">${esc(section.title)}${item?`<small>${categories[item.bucket]}</small>`:''}</span><b>${price===null?'':rub(price)}</b>${item?.unknown?'<span class="badge warn">Оценка</span>':''}</summary><div class="detail-body">${item?`<div class="cost-edit"><label><input type="checkbox" data-selected="${esc(item.id)}" ${item.selected?'checked':''}> Включить в план</label><label>Группа <select data-bucket="${esc(item.id)}">${Object.entries(categories).map(([k,v])=>`<option value="${k}" ${k===item.bucket?'selected':''}>${v}</option>`).join('')}</select></label><label>Стоимость, ₽ <input type="number" min="0" value="${itemCost(item)}" data-cost="${esc(item.id)}"></label><label>Дней вне городского бюджета <input type="number" min="0" max="${r.days}" value="${item.excludedDays||0}" data-exclude="${esc(item.id)}"></label></div>${item.parts?.length?`<ul class="breakdown">${item.parts.map(x=>`<li>${esc(x.label)} — ${rub(x.amount)}</li>`).join('')}</ul>`:''}`:''}${section.html}${item?.image&&safeURL(item.image.url)?`<figure><img class="place-photo" src="${esc(safeURL(item.image.url))}" alt="${esc(item.image.alt)}" loading="lazy" referrerpolicy="no-referrer"><figcaption><a href="${esc(safeURL(item.image.source))}" target="_blank" rel="noopener">${esc(item.image.credit||'Источник фотографии')}</a></figcaption></figure>`:''}${item?.source?`<p class="source muted">Источник: <a href="${esc(safeURL(item.source))}" target="_blank" rel="noopener">${esc(item.source)}</a></p>`:''}</div></details>`;
  }).join('')}</div><p><button id="add-item">+ Добавить расход</button></p>`;
  bindCommon();document.querySelector('#back').onclick=async()=>{if(dirty){await save();if(dirty)return;}location.href='/admin/travel';};
  const itemFor=n=>p.items.find(i=>i.id===n);
  root.querySelectorAll('[data-selected]').forEach(n=>n.onchange=()=>edit(()=>itemFor(n.dataset.selected).selected=n.checked));
  root.querySelectorAll('[data-bucket]').forEach(n=>n.onchange=()=>edit(()=>itemFor(n.dataset.bucket).bucket=n.value));
  root.querySelectorAll('[data-cost]').forEach(n=>n.onchange=()=>edit(()=>{const i=itemFor(n.dataset.cost);i.amount=+n.value;i.parts=[];}));
  root.querySelectorAll('[data-exclude]').forEach(n=>n.onchange=()=>edit(()=>itemFor(n.dataset.exclude).excludedDays=+n.value));
  document.querySelector('#add-item').onclick=()=>{const title=prompt('Название расхода');if(!title)return;edit(()=>p.items.push({id:'item-'+Date.now().toString(36),title,bucket:p.base?'leisure':'fixed',selected:true,amount:0,parts:[],unknown:true,excludedDays:0}));};
}

window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
try{const data=await request('/plan');model=data.model;revision=data.revision;if(phaseId)article=await request('/phases/'+phaseId);render();}
catch(e){root.innerHTML='<h1>План путешествия</h1><p class="error">'+esc(e.message)+'</p><a href="/admin/travel">Открыть калькулятор</a>';}
