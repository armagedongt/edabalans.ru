import {calculate,clone,rub,itemCost,changeStart,changeEnd,shift,drawPNG,ModelHistory} from './calc.mjs';
import {mountGuide} from './maps.mjs';
const root=document.querySelector('#app');
let model,revision,dirty=false,article=null,saving=false,canEdit=false;
const history=new ModelHistory();
let savedModel='';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL=u=>{try{const x=new URL(u);return x.protocol==='https:'||x.protocol==='http:'?x.href:'';}catch{return '';}};
const api='/api/travel';
const phaseId=location.pathname.includes('/phases/')?location.pathname.split('/').at(-1):null;
function msg(message,error=false){const n=document.querySelector('#message');if(n){n.textContent=message;n.className=error?'error':'success';}}
async function request(path,options={}){
  const r=await fetch((options.method&&options.method!=='GET'?'/admin/api/travel':api)+path,{credentials:'same-origin',...options});
  if(r.status===401){location.href='/admin?next='+encodeURIComponent(location.pathname);throw new Error('Нужен вход');}
  const data=await r.json();
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос');
  return data;
}
function current(){return calculate(model);}
function edit(fn){if(!canEdit||phaseId)return;const previous=clone(model);try{fn();current();history.record(previous,model);dirty=JSON.stringify(model)!==savedModel;render();msg(dirty?'Есть несохранённые изменения':'Все изменения сохранены');}catch(e){model=previous;render();msg(e.message,true);}}
function restore(direction){if(!canEdit||phaseId)return;const next=history[direction](model);if(!next)return;model=next;dirty=JSON.stringify(model)!==savedModel;render();msg(direction==='undo'?'Изменение отменено':'Изменение повторено');}
const categories={fixed:'Отдельная программа',leisure:'Из городского бюджета',sport:'Соревнования и велосипед',restaurant:'Ресторанный план',included:'Уже включено в пакет'};

function render(){
  const result=current();
  if(phaseId){renderPhase(result);return;}
  root.innerHTML=`<div class="toolbar"><a class="button" href="/admin">← Админка</a><button class="primary" id="save">Сохранить</button><button id="undo" ${history.past.length?'':'disabled'} title="Ctrl+Z">↶ Отменить</button><button id="redo" ${history.future.length?'':'disabled'} title="Ctrl+Y">↷ Повторить</button><button id="png">Картинка для Сони</button><button id="json">Скачать JSON</button><button id="import">Открыть JSON</button></div>
  <h1>План на зимовку</h1><div class="toolbar"><label>Начало <input id="start" type="date" value="${esc(model.phases[0].start)}"></label><label>Окончание <input id="end" type="date" value="${esc(model.phases.at(-1).end)}"></label><span>${result.days} дней / ${result.nights} ночей · двое</span></div>
  <div class="total">Весь план: <span id="total">${rub(result.total)}</span> на двоих</div><div id="message" role="status"></div>
  <div class="table-wrap route-wrap"><table class="route-table"><thead><tr><th>Этап / перелёт сюда</th><th>Заезд → выезд</th><th>Дней</th><th>Билеты, ₽</th><th>Ночь, ₽</th><th>На месте / в день</th><th>Итого этап</th><th>Подробно</th></tr></thead><tbody>
  ${model.phases.map((p,i)=>{const r=result.rows[i];return `<tr><td class="stage"><strong>${esc(p.title)}, ${esc(p.country)}</strong><small>${esc(p.flight.from)}</small><button class="remove" data-remove="${i}">Убрать фазу</button></td><td class="dates" data-label="Заезд → выезд"><input aria-label="Заезд ${esc(p.title)}" type="date" value="${p.start}" data-start="${i}"><span class="date-arrow">↓</span><input aria-label="Выезд ${esc(p.title)}" type="date" value="${p.end}" data-end="${i}"></td><td data-label="Дней">${r.days}</td><td data-label="Перелёт сюда"><input aria-label="Перелёт ${esc(p.title)}" type="number" min="0" value="${p.flight.amount}" data-flight="${i}"></td><td data-label="Жильё / ночь"><input aria-label="Ночь ${esc(p.title)}" type="number" min="0" value="${p.nightRate}" data-night="${i}"></td><td class="number" data-label="На месте"><b>${rub(r.local)}</b><small>${rub(r.local/r.days)} / день</small></td><td class="number" data-label="Итого этап"><b>${rub(r.total)}</b></td><td class="plan-cell"><button data-open="${esc(p.id)}">План →</button></td></tr>`;}).join('')}
  <tr class="return-row"><td colspan="3"><b>Обратные билеты в Петербург</b><small class="muted"> · ${esc(model.returnFlight.from)}</small></td><td data-label="Обратные билеты"><input id="return" aria-label="Обратные билеты" type="number" min="0" value="${model.returnFlight.amount}"></td><td colspan="2"></td><td class="number"><b>${rub(model.returnFlight.amount)}</b></td><td></td></tr></tbody></table></div>
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
  root.querySelectorAll('[data-open]').forEach(n=>n.onclick=async()=>{if(dirty){await save();if(dirty)return;}location.href='/travel/phases/'+n.dataset.open;});
  root.querySelector('#png').onclick=()=>{const canvas=document.querySelector('#export-canvas');drawPNG(canvas,model,current());canvas.toBlob(b=>download(b,'План зимовки.png'));};
  if(!canEdit){
    root.querySelectorAll('#save,#undo,#redo,#json,#import,#add,[data-remove]').forEach(n=>n.remove());
    root.querySelectorAll('input').forEach(n=>{if(n.type==='range'){n.remove();return;}const value=document.createElement('span');value.textContent=n.value;n.replaceWith(value);});
    const login=root.querySelector('a[href="/admin"]');login.href='/admin?next=/travel';login.textContent='Войти для редактирования';
    return;
  }
  bindCommon();
  root.querySelector('#undo').onclick=()=>restore('undo');
  root.querySelector('#redo').onclick=()=>restore('redo');
  root.querySelector('#start').onchange=e=>edit(()=>changeStart(model,0,e.target.value));
  root.querySelector('#end').onchange=e=>edit(()=>changeEnd(model,model.phases.length-1,e.target.value));
  root.querySelectorAll('[data-start]').forEach(n=>n.onchange=()=>edit(()=>changeStart(model,+n.dataset.start,n.value)));
  root.querySelectorAll('[data-end]').forEach(n=>n.onchange=()=>edit(()=>changeEnd(model,+n.dataset.end,n.value)));
  root.querySelectorAll('[data-flight]').forEach(n=>n.onchange=()=>edit(()=>model.phases[+n.dataset.flight].flight.amount=+n.value));
  root.querySelectorAll('[data-night]').forEach(n=>n.onchange=()=>edit(()=>model.phases[+n.dataset.night].nightRate=+n.value));
  root.querySelector('#return').onchange=e=>edit(()=>model.returnFlight.amount=+e.target.value);
  root.querySelectorAll('[data-setting],[data-slider]').forEach(n=>n.onchange=()=>edit(()=>model.settings[n.dataset.setting||n.dataset.slider]=+n.value));
  root.querySelectorAll('[data-remove]').forEach(n=>n.onclick=()=>edit(()=>{const i=+n.dataset.remove;if(model.phases.length===1)throw new Error('Нужна хотя бы одна фаза');const removed=model.phases[i];model.phases.splice(i,1);if(i>0&&i<model.phases.length)model.phases[i].start=removed.start;else if(i===0)model.phases[0].start=removed.start;}));
  root.querySelector('#add').onclick=()=>{
    const title=prompt('Город новой фазы');if(!title)return;const country=prompt('Страна');if(!country)return;
    edit(()=>{const start=model.phases.at(-1).end;model.phases.push({id:'phase-'+Date.now().toString(36),title,country,start,end:shift(start,3),base:false,nightRate:3000,flight:{from:'Из предыдущей фазы',amount:0,unknown:true},items:[]});});
  };
  root.querySelector('#import').onclick=()=>{const input=document.createElement('input');input.type='file';input.accept='.json';input.onchange=async()=>{try{const value=JSON.parse(await input.files[0].text());edit(()=>model=value.model||value);}catch(e){msg('Некорректный JSON: '+e.message,true);}};input.click();};
}

async function save(){
  if(!canEdit||phaseId||saving)return;
  const submitted=JSON.stringify(model);saving=true;
  try{current();msg('Сохраняем…');const answer=await request('/plan',{method:'PUT',headers:{'Content-Type':'application/json','X-Travel-Write':'1'},body:JSON.stringify({model,revision})});revision=answer.revision;savedModel=submitted;dirty=JSON.stringify(model)!==submitted;msg(dirty?'Сохранена предыдущая версия; новые изменения ещё не сохранены':'Сохранено на сервере');}
  catch(e){msg(e.message+' Изменения остались в форме; можно скачать JSON.',true);}
  finally{saving=false;}
}
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function bindCommon(){document.querySelector('#save').onclick=save;document.querySelector('#json').onclick=()=>download(new Blob([JSON.stringify({model,revision},null,2)],{type:'application/json'}),'travel-plan.json');}

function renderPhase(result){
  const index=model.phases.findIndex(p=>p.id===phaseId);
  if(index<0)throw new Error('Фаза не найдена');
  const p=model.phases[index],r=result.rows[index];
  const all=[...article.sections];
  p.items.filter(i=>!all.some(s=>s.id===i.id)).forEach(i=>all.push({id:i.id,title:i.title,html:'<p>Подробности ещё не заполнены.</p>'}));
  root.innerHTML=`<div class="toolbar"><a class="button" href="/travel">← Калькулятор</a></div><h1>${esc(p.title)}, ${esc(p.country)}</h1><p class="lead">${esc(p.start)} — ${esc(p.end)} · ${r.nights} ночей · ${rub(r.local)} на месте</p><div class="phase-list">${all.map(section=>{
    if(section.id.startsWith('group-')&&!section.html.trim()&&!p.items.some(i=>i.id===section.id))return `<h2 id="item-${esc(section.id)}" class="phase-group">${esc(section.title)}</h2>`;
    const item=p.items.find(i=>i.id===section.id);
    const price=section.id==='housing'?r.housing:section.id==='flight'?p.flight.amount:item?itemCost(item):null;
    const breakdown=item?.parts?.length?`<ul class="breakdown">${item.parts.map(x=>`<li>${esc(x.label)} — ${rub(x.amount)}</li>`).join('')}</ul>`:'';
    const photo=item?.image&&safeURL(item.image.url)?`<figure><img class="place-photo" src="${esc(safeURL(item.image.url))}" alt="${esc(item.image.alt)}" loading="lazy" referrerpolicy="no-referrer"><figcaption><a href="${esc(safeURL(item.image.source))}" target="_blank" rel="noopener">${esc(item.image.credit||'Источник фотографии')}</a></figcaption></figure>`:'';
    const source=item?.source?`<p class="source muted">Источник: <a href="${esc(safeURL(item.source))}" target="_blank" rel="noopener">${esc(item.source)}</a></p>`:'';
    return `<details id="item-${esc(section.id)}"><summary><span class="title">${esc(section.title)}${item?`<small>${categories[item.bucket]}</small>`:''}</span><b>${price===null?'':rub(price)}</b>${item?.unknown?'<span class="badge warn">Оценка</span>':''}</summary><div class="detail-body">${breakdown}${section.html}${photo}${source}</div></details>`;
  }).join('')}</div>`;
  mountGuide(root,p);
}

window.addEventListener('keydown',e=>{
  if(!canEdit||phaseId||!(e.ctrlKey||e.metaKey)||e.altKey)return;
  const key=e.code==='KeyZ'?'z':e.code==='KeyY'?'y':e.key.toLowerCase(),direction=key==='z'?(e.shiftKey?'redo':'undo'):key==='y'?'redo':null;
  if(!direction)return;
  e.preventDefault();
  const active=document.activeElement;
  if(active?.matches('input')&&active.value!==active.defaultValue)active.dispatchEvent(new Event('change',{bubbles:true}));
  restore(direction);
});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
try{const data=await request('/plan');model=data.model;savedModel=JSON.stringify(model);revision=data.revision;canEdit=data.canEdit===true;if(phaseId)article=await request('/phases/'+phaseId);render();}
catch(e){root.innerHTML='<h1>План путешествия</h1><p class="error">'+esc(e.message)+'</p><a href="/travel">Открыть калькулятор</a>';}
