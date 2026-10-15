import {nights,shift,rub} from './calc.mjs';

const labels={hotel:'Отели',food:'Еда и кафе',restaurant:'Рестораны',interest:'Места интереса',walk:'Прогулки',boat:'Лодки',metro:'Метро и поезд'};
const colors={hotel:'#8948a5',food:'#d37d20',restaurant:'#b84c52',interest:'#287c65',walk:'#347fbd',boat:'#187ea4',metro:'#bd3232'};
let loader;
function leaflet(){
  if(window.L)return Promise.resolve(window.L);
  if(!loader)loader=new Promise((resolve,reject)=>{
    const css=document.createElement('link');css.rel='stylesheet';css.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';css.integrity='sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';css.crossOrigin='anonymous';document.head.append(css);
    const script=document.createElement('script');script.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';script.integrity='sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';script.crossOrigin='anonymous';script.onload=()=>resolve(window.L);script.onerror=()=>reject(new Error('Карта не загрузилась. Ссылки на места ниже работают отдельно.'));document.head.append(script);
  });
  return loader;
}
function element(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function link(text,url){const a=element('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function mapsURL(p){return `https://www.google.com/maps/search/?api=1&query=${p.latitude},${p.longitude}`;}
function popup(p){const box=element('div');box.append(element('strong',p.name),element('p',labels[p.category]||''),link('Открыть в Google Maps',mapsURL(p)));return box;}

function mapBlock(parent,guide,filter,title){
  const places=guide.places.filter(filter),routes=guide.routes.filter(filter);
  if(!places.length&&!routes.length)return;
  const wrap=element('section',undefined,'map-block');wrap.append(element('h3',title));
  const controls=element('div',undefined,'map-filters'),mapEl=element('div',undefined,'travel-map');mapEl.setAttribute('aria-label',title);
  wrap.append(controls,mapEl);parent.append(wrap);
  const buttons=[];
  const list=element('div',undefined,'map-links');
  for(const p of places){const a=link((p.number?`${p.number}. `:'')+p.name,mapsURL(p));list.append(a);buttons.push([p,a]);}
  wrap.append(list);
  let instance;
  async function start(){
    if(instance){instance.invalidateSize();return;}
    try{
      const L=await leaflet();if(!mapEl.isConnected)return;
      if(instance){instance.invalidateSize();return;}
      instance=L.map(mapEl,{scrollWheelZoom:false}).setView([13.75,100.54],11);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(instance);
      const groups=new Map(),bounds=[];
      const group=kind=>{if(!groups.has(kind))groups.set(kind,L.layerGroup().addTo(instance));return groups.get(kind);};
      for(const p of places){const pos=[p.latitude,p.longitude];bounds.push(pos);const marker=p.category==='hotel'?L.marker(pos,{icon:L.divIcon({className:'hotel-pin',html:String(p.number||'H'),iconSize:[30,30]})}):L.circleMarker(pos,{radius:7,color:colors[p.category],fillOpacity:.9,weight:2});marker.bindPopup(popup(p)).addTo(group(p.category));}
      for(const r of routes){bounds.push(...r.points);L.polyline(r.points,{color:colors[r.category],weight:r.category==='metro'?4:3,dashArray:r.approximate?'7 6':null}).bindTooltip(element('span',r.name+(r.approximate?' · схема':'' ))).addTo(group(r.category));}
      if(bounds.length)instance.fitBounds(bounds,{padding:[25,25],maxZoom:15});
      for(const [kind,g] of groups){const label=element('label'),input=element('input');input.type='checkbox';input.checked=true;input.dataset.layer=kind;input.onchange=()=>{input.checked?g.addTo(instance):instance.removeLayer(g);};label.append(input,document.createTextNode(labels[kind]));controls.append(label);}
    }catch(e){mapEl.replaceChildren(element('p',e.message,'muted'));}
  }
  const details=parent.closest('details');
  if(details){details.addEventListener('toggle',()=>{if(details.open)start();});if(details.open)start();}else start();
  return {wrap,show:async p=>{await start();const toggle=controls.querySelector(`[data-layer="${p.category}"]`);if(toggle&&!toggle.checked)toggle.click();if(instance)instance.setView([p.latitude,p.longitude],15);}};
}

function hotelCards(parent,phase){
  const guide=phase.guide,half=Math.ceil(nights(phase.start,phase.end)/2);
  for(const h of guide.hotels){
    const p=guide.places.find(x=>x.id===h.placeId),first=h.half==='first';
    const start=first?phase.start:shift(phase.start,half),end=first?shift(phase.start,half):phase.end,n=nights(start,end);
    const card=element('article',undefined,'hotel-card');
    if(h.photoURL){const img=element('img');img.src=h.photoURL;img.alt=p.name;img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>img.remove();card.append(img);}
    const content=element('div');content.append(element('small',h.role),element('h4',`${p.number}. ${p.name}`),element('p',`${start} → ${end} · ${n} ночей`));
    const params=new URL(h.bookingURL);params.searchParams.set('checkin',start);params.searchParams.set('checkout',end);params.searchParams.set('group_adults','2');params.searchParams.set('no_rooms','1');
    content.append(element('p',h.breakfast==='included'?'Завтрак включён в сохранённое предложение':'Нужен тариф с завтраком; включение уточнить'));
    if(h.quotedTotal!=null){const quotedNights=nights(h.quotedStart,h.quotedEnd);content.append(element('p',`Ориентир на ${n} ночей: ${rub(h.quotedTotal/quotedNights*n)}`,'hotel-price'),element('small',`По цене ${rub(h.quotedTotal)} за ${h.quotedStart} → ${h.quotedEnd}, источник: ${h.quoteSource}. Это пересчёт, не новая котировка.`));}
    else content.append(element('p','Цена на выбранные даты ещё не проверена','muted'));
    content.append(element('p',h.note||''),link('Booking на эти даты',params.href),document.createTextNode(' · '),link('Карта',mapsURL(p)));
    if(p.url)content.append(document.createTextNode(' · '),link('Официальный сайт',p.url));
    card.append(content);parent.append(card);
  }
}

export function mountGuide(root,phase){
  const guide=phase.guide;if(!guide)return;
  const header=element('section',undefined,'city-guide');
  header.append(element('h2','Карта и места'));
  header.append(element('p','Переключайте слои. Пунктирные линии — схема прогулки или поездки, а не пошаговая навигация.','muted'));
  const list=root.querySelector('.phase-list');list.before(header);
  const main=mapBlock(header,guide,()=>true,'Все места этапа');
  for(const details of list.querySelectorAll('details')){
    const id=details.id.replace('item-',''),body=details.querySelector('.detail-body');
    if(id==='housing'&&guide.hotels.length){const cards=element('div',undefined,'hotel-cards');body.append(cards);hotelCards(cards,phase);mapBlock(body,guide,x=>x.category==='hotel'||x.category==='metro','Отели и аэропортовая линия');}
    const selected=guide.places.filter(p=>p.section===id);
    if(selected.length&&id!=='housing'){
      const button=element('button','Показать на общей карте');button.onclick=()=>{main?.show(selected[0]);header.scrollIntoView({behavior:'smooth',block:'start'});};body.append(button);
      mapBlock(body,guide,x=>x.section===id,'Места этого пункта');
    }
  }
}
