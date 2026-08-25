from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.masterclass_offer_catalog import OFFER_CARD_COPY, OFFER_PRODUCTS  # noqa: E402


SIMULATOR_CSS = """
#offer-simulator{font:15px/1.45 Inter,Arial,sans-serif;color:#252525}
#offer-simulator *{box-sizing:border-box}.sim-shell{display:grid;gap:16px}.sim-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;padding:16px;border:1px solid #dfd6ca;border-radius:20px;background:#fffdf9}.sim-field{display:grid;gap:6px}.sim-field label,.sim-owned-title{font-weight:600}.sim-field select{width:100%;padding:10px 12px;border:1px solid #dfd6ca;border-radius:10px;background:#f5f0e8;color:#252525;font:inherit}.sim-owned{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px 16px}.sim-owned-title{width:100%}.sim-owned label{display:inline-flex;align-items:center;gap:6px}.sim-facts{grid-column:1/-1;padding:12px 14px;border-radius:12px;background:#f5f0e8;color:#706d68}.sim-facts strong{color:#252525}.sim-preview{overflow:hidden;border:1px solid #dfd6ca;border-radius:20px;background:#f5f0e8;box-shadow:0 16px 46px #50351b12}.sim-price-map{grid-column:1/-1;border-top:1px solid #dfd6ca;padding-top:12px}.sim-price-map summary{cursor:pointer;font-weight:600}.sim-grid{display:grid;grid-template-columns:1.2fr repeat(5,.75fr);gap:1px;margin-top:10px;overflow:hidden;border:1px solid #dfd6ca;border-radius:10px;background:#dfd6ca}.sim-grid span{padding:8px;background:#fffdf9;text-align:center}.sim-grid span:nth-child(6n+1){text-align:left;font-weight:600}
@media(max-width:620px){.sim-controls{grid-template-columns:1fr}.sim-owned,.sim-facts,.sim-price-map{grid-column:1}.sim-grid{font-size:11px}.sim-grid span{padding:6px 3px}}
"""


HTML_TEMPLATE = r"""<div id="offer-simulator">
<style>__COURSE_CSS__</style><style>__SIMULATOR_CSS__</style>
<div class="sim-shell">
  <section class="sim-controls" aria-label="Конструктор сценария">
    <div class="sim-field"><label for="sim-tariff">Тариф мастер-класса</label><select id="sim-tariff"><option value="minimal">Минимальный · 6 900 ₽</option><option value="standard">Стандартный · 8 900 ₽</option><option value="consult">С консультацией · 15 900 ₽</option></select></div>
    <div class="sim-field"><label for="sim-placement">Место показа</label><select id="sim-placement"><option value="day1">День 1 · первый показ ранней цены без таймера</option><option value="firstStart">После DQS · перед первыми рецептами · запуск раннего окна</option><option value="firstRecipes">Первые рецепты · повтор действующей ранней цены</option><option value="secondStart">Перед второй частью рецептов · запуск второй цены</option><option value="secondRecipes">Вторая часть рецептов · повтор действующей второй цены</option><option value="review">После саморевью · цена разбора</option><option value="day21Deferred">День 21 · review ещё действует · неделя после него</option><option value="day21Now">День 21 · review завершён · неделя начинается сразу</option><option value="standard">После последней недели · обычные цены</option></select></div>
    <div class="sim-owned"><div class="sim-owned-title">Что уже куплено к этому моменту</div><label><input type="checkbox" data-owned="recipes"> Рецепты</label><label><input type="checkbox" data-owned="calories"> Калорийный</label><label><input type="checkbox" data-owned="training"> Тренировки</label><label><input type="checkbox" data-owned="recordings"> Записи консультаций</label><label><input type="checkbox" data-owned="consultation"> Консультация</label></div>
    <div class="sim-facts" id="sim-facts"></div>
    <details class="sim-price-map"><summary>Карта цен всех ступеней</summary><div class="sim-grid"><span>Цена</span><span>Ранняя</span><span>Вторая</span><span>Разбор</span><span>Неделя</span><span>Обычная</span><span>1 продукт</span><span>2 900</span><span>3 300</span><span>3 500</span><span>3 800</span><span>3 900</span><span>2 продукта</span><span>3 900</span><span>4 900</span><span>5 700</span><span>7 000</span><span>7 800</span><span>3 продукта</span><span>5 900</span><span>7 400</span><span>8 500</span><span>10 400</span><span>11 700</span><span>4 продукта</span><span>7 900</span><span>9 900</span><span>11 300</span><span>13 800</span><span>15 600</span><span>Консультация</span><span>—</span><span>—</span><span>7 500</span><span>8 400</span><span>8 900</span></div></details>
  </section>
  <section class="sim-preview" aria-live="polite"><div id="sim-screen"></div></section>
</div>
<script>(()=>{
const root=document.getElementById('offer-simulator'),tariff=root.querySelector('#sim-tariff'),placement=root.querySelector('#sim-placement'),screen=root.querySelector('#sim-screen'),facts=root.querySelector('#sim-facts'),checks=[...root.querySelectorAll('[data-owned]')];let timerId=null;
const products=__PRODUCTS_JSON__,offerCopy=__OFFER_COPY_JSON__,digital=['recipes','calories','training','recordings'];
const tariffs={minimal:{name:'Минимальный',owned:[]},standard:{name:'Стандартный',owned:['recipes']},consult:{name:'С консультацией',owned:['recipes','consultation']}};
const stages={day1:{stage:'early',event:'day_1_offer_opened',placement:'day-1-offer',hours:null,starts:false,single:2900,bundle:[0,1900,3900,5900,7900]},firstStart:{stage:'early',event:'day_15_offer_opened',placement:'day-15-offer',hours:96,timerKey:'early',starts:true,single:2900,bundle:[0,1900,3900,5900,7900]},firstRecipes:{stage:'early',event:'recipes_part_1_opened',placement:'recipes-part-1-gate',hours:96,timerKey:'early',starts:false,single:2900,bundle:[0,1900,3900,5900,7900]},secondStart:{stage:'second',event:'day_17_offer_opened',placement:'day-17-offer',hours:72,timerKey:'second',starts:true,single:3300,bundle:[0,2500,4900,7400,9900]},secondRecipes:{stage:'second',event:'recipes_part_2_opened',placement:'recipes-part-2-gate',hours:72,timerKey:'second',starts:false,single:3300,bundle:[0,2500,4900,7400,9900]},review:{stage:'review',event:'day_19_offer_opened',placement:'day-19-offer',hours:72,timerKey:'review',starts:true,single:3500,consult:7500,bundle:[0,2900,5700,8500,11300]},day21Deferred:{stage:'last_week',event:'day_21_offer_opened',placement:'day-21-offer',hours:168,deferred:true,starts:true,single:3800,consult:8400,bundle:[0,3600,7000,10400,13800]},day21Now:{stage:'last_week',event:'day_21_offer_opened',placement:'day-21-offer',hours:168,timerKey:'last_week',starts:true,single:3800,consult:8400,bundle:[0,3600,7000,10400,13800]},standard:{stage:'standard',event:'нет нового события',placement:'offers-hub',hours:null,starts:false,single:3900,consult:8900,bundle:null}};
const deadlines={},money=n=>`${new Intl.NumberFormat('ru-RU').format(n)} ₽`,pct=(a,b)=>a?Math.round((a-b)/a*100):0;
function owned(){const set=new Set(tariffs[tariff.value].owned);checks.forEach(c=>{if(c.checked)set.add(c.dataset.owned)});return set}
function available(set){return digital.filter(k=>k!=='recordings'||!set.has('consultation'))}
function included(keys){return `<div class="mc-offer-includes"><span class="mc-offer-includes-title">В составе</span><ul>${keys.map(k=>`<li><span aria-hidden="true">✓</span><div><strong>${products[k].name}</strong><p>${products[k].description}</p></div></li>`).join('')}</ul></div>`}
function card(title,keys,price,description){const regular=keys.reduce((s,k)=>s+products[k].standard,0),saving=Math.max(0,regular-price),bundle=keys.length>1,body=description||products[keys[0]].description;return `<article class="mc-offer-card"><div class="mc-offer-copy"><span class="mc-offer-kind">Дополнение к программе</span><h2>${title}</h2><p>${body}</p>${bundle?included(keys):''}</div><div class="mc-offer-terms"><div class="mc-offer-prices">${saving?`<span class="offer-old">${money(regular)}</span>`:''}<strong class="offer-price">${money(price)}</strong></div>${saving?`<span class="offer-saving">Выгода ${pct(regular,price)}% · ${money(saving)}</span>`:''}<button type="button" data-offer="${keys.join(',')}">Купить</button></div></article>`}
function timer(cfg){if(cfg.deferred)return `<div class="mc-countdown" role="timer"><span>Последняя неделя начнётся после завершения цены разбора</span><strong>Точный срок берётся из действующего окна review</strong></div>`;if(!cfg.hours)return '';const key=cfg.timerKey||placement.value;if(!deadlines[key])deadlines[key]=Date.now()+cfg.hours*3600000;const exact=new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(deadlines[key]);return `<div class="mc-countdown" role="timer"><span>Цена действует до ${exact} по вашему времени</span><strong id="sim-countdown"></strong></div>`}
function startTimer(cfg){if(timerId)clearInterval(timerId);const node=screen.querySelector('#sim-countdown');if(!node)return;const key=cfg.timerKey||placement.value,update=()=>{const m=Math.max(0,Math.floor((deadlines[key]-Date.now())/60000)),d=Math.floor(m/1440),h=Math.floor(m%1440/60);node.textContent=`Осталось: ${d?`${d} дн. `:''}${h} ч ${m%60} мин`};update();timerId=setInterval(update,60000)}
function render(){const cfg=stages[placement.value],have=owned(),missing=available(have).filter(k=>!have.has(k)),hasConsult=have.has('consultation'),duration=cfg.hours?`${cfg.hours} ч`:'без таймера',windowAction=cfg.deferred?'начнётся после завершения review':cfg.hours?(cfg.starts?'запускается при первом открытии':'продолжается, не перезапускается'):'не запускается';facts.innerHTML=`<strong>Системная точка:</strong> ${cfg.placement} · <strong>событие:</strong> ${cfg.event} · <strong>ступень:</strong> ${cfg.stage} · <strong>окно:</strong> ${duration}, ${windowAction}. Цена и доступ повторно проверяются перед checkout.`;let offers='';if(['early','second'].includes(cfg.stage)){if(missing.length){offers+=card(products[missing[0]].name,[missing[0]],cfg.single);if(missing.length>1)offers+=card(offerCopy.digital_bundle.title,missing,cfg.bundle[missing.length],offerCopy.digital_bundle.description)}}else if(cfg.stage==='review'){if(!hasConsult){offers+=card(products.consultation.name,['consultation'],cfg.consult);if(missing.length)offers+=card(offerCopy.consultation_bundle.title,['consultation',...missing],cfg.consult+cfg.bundle[missing.length],offerCopy.consultation_bundle.description)}if(missing.length)offers+=card(products[missing[0]].name,[missing[0]],cfg.single)}else if(cfg.stage==='last_week'){if(!hasConsult)offers+=card(products.consultation.name,['consultation'],cfg.consult);if(missing.length>1)offers+=card(offerCopy.digital_bundle.title,missing,cfg.bundle[missing.length],offerCopy.digital_bundle.description);missing.slice(0,Math.max(0,3-(hasConsult?1:0)-(missing.length>1?1:0))).forEach(k=>offers+=card(products[k].name,[k],cfg.single))}else{if(!hasConsult)offers+=card(products.consultation.name,['consultation'],cfg.consult);missing.slice(0,3-(hasConsult?1:0)).forEach(k=>offers+=card(products[k].name,[k],products[k].standard))}
const ownedList=[`Мастер-класс по изменению питания и пищевых привычек — тариф «${tariffs[tariff.value].name}»`,...[...have].map(k=>products[k].name)],ownedHtml=`<section class="mc-owned"><span class="mc-owned-title">В вашем тарифе</span><ul>${ownedList.map(name=>`<li><span aria-hidden="true">✓</span>${name}</li>`).join('')}</ul></section>`,timerHtml=timer(cfg);screen.innerHTML=`<main class="mc mc-offer-page"><h1>Можно добавить к мастер-классу</h1><p class="lead">Выберите дополнительные материалы, которые помогут продолжить работу после мастер-класса.</p><section class="mc-offers"><div class="mc-offer-summary${timerHtml?' has-timer':''}">${ownedHtml}${timerHtml}</div><div class="offer-grid">${offers||'<section class="mc-card mc-offer-empty"><h2>У вас уже всё открыто</h2><p>Дополнительных предложений сейчас нет.</p></section>'}</div></section></main>`;screen.querySelectorAll('[data-offer]').forEach(b=>b.addEventListener('click',()=>{b.dataset.offer.split(',').forEach(k=>{const c=checks.find(x=>x.dataset.owned===k);if(c)c.checked=true});render()}));startTimer(cfg)}
tariff.addEventListener('change',()=>{checks.forEach(c=>c.checked=false);render()});placement.addEventListener('change',render);checks.forEach(c=>c.addEventListener('change',render));render();
})();</script></div>"""


def render_simulator() -> str:
    course_css = (BACKEND_ROOT / "app" / "static" / "masterclass.css").read_text(
        encoding="utf-8"
    )
    products_json = json.dumps(OFFER_PRODUCTS, ensure_ascii=False, separators=(",", ":"))
    offer_copy_json = json.dumps(
        OFFER_CARD_COPY, ensure_ascii=False, separators=(",", ":")
    )
    return (
        "<!-- GENERATED: run backend/scripts/generate_masterclass_offer_simulator.py; do not edit -->\n"
        + HTML_TEMPLATE.replace("__COURSE_CSS__", course_css)
        .replace("__SIMULATOR_CSS__", SIMULATOR_CSS)
        .replace("__PRODUCTS_JSON__", products_json)
        .replace("__OFFER_COPY_JSON__", offer_copy_json)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_simulator(), encoding="utf-8")


if __name__ == "__main__":
    main()
