from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.masterclass_offer_catalog import OFFER_CARD_COPY, OFFER_PRODUCTS  # noqa: E402
from app.masterclass_offer_rules import (  # noqa: E402
    OFFER_STAGE_DURATIONS,
    STAGE_BY_PLACEMENT,
    WINDOW_START_EVENTS,
)


COURSE_PATH = REPOSITORY_ROOT / "content" / "masterclass" / "course" / "course.json"


SIMULATOR_CSS = """
#offer-simulator{font:15px/1.45 Inter,Arial,sans-serif;color:#252525}
#offer-simulator *{box-sizing:border-box}.sim-shell{display:grid;gap:16px}.sim-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;padding:16px;border:1px solid #dfd6ca;border-radius:20px;background:#fffdf9}.sim-field{display:grid;gap:6px}.sim-field label,.sim-owned-title{font-weight:600}.sim-field select{width:100%;padding:10px 12px;border:1px solid #dfd6ca;border-radius:10px;background:#f5f0e8;color:#252525;font:inherit}.sim-owned{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px 16px}.sim-owned-title{width:100%}.sim-owned label{display:inline-flex;align-items:center;gap:6px}.sim-facts{grid-column:1/-1;padding:12px 14px;border-radius:12px;background:#f5f0e8;color:#706d68}.sim-facts strong{color:#252525}.sim-preview{overflow:hidden;border:1px solid #dfd6ca;border-radius:20px;background:#f5f0e8;box-shadow:0 16px 46px #50351b12}.sim-price-map{grid-column:1/-1;overflow-x:auto;border-top:1px solid #dfd6ca;padding-top:12px}.sim-price-map summary{cursor:pointer;font-weight:600}.sim-grid{display:grid;grid-template-columns:1.2fr repeat(5,.75fr);gap:1px;min-width:620px;margin-top:10px;overflow:hidden;border:1px solid #dfd6ca;border-radius:10px;background:#dfd6ca}.sim-grid span{padding:8px;background:#fffdf9;text-align:center}.sim-grid span:nth-child(6n+1){text-align:left;font-weight:600}
@media(max-width:620px){.sim-controls{grid-template-columns:1fr}.sim-owned,.sim-facts,.sim-price-map{grid-column:1}.sim-grid{font-size:11px}.sim-grid span{padding:6px 3px}}
"""


PAGE_CSS = """
*{box-sizing:border-box}body{margin:0;background:#f5f0e8;color:#252525;font:15px/1.45 Inter,Arial,sans-serif}
.preview-shell{width:min(1180px,100%);margin:0 auto;padding:20px}.preview-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:16px}.preview-head h1{margin:0 0 4px;font-size:24px;line-height:1.18}.preview-head p{max-width:720px;margin:0;color:#706d68}.preview-back{flex:none;color:#252525;text-decoration:none;border-bottom:1px solid #252525}.preview-source{margin:0 0 16px;padding:11px 14px;border-radius:12px;background:#fffdf9;color:#706d68}.preview-source strong{color:#252525}
.preview-modes{display:flex;gap:8px;margin:0 0 14px}.preview-modes a{border:1px solid #cfc3b4;border-radius:999px;padding:8px 13px;background:#fffdf9;color:#252525;font:600 14px/1 Inter,Arial,sans-serif;text-decoration:none}.preview-modes a[aria-selected=true]{background:#b94d2f;border-color:#b94d2f;color:#fff}.client-mode{display:none}.client-mode.is-active{display:block}.client-search{display:grid;gap:8px;max-width:620px;padding:16px;border:1px solid #dfd6ca;border-radius:20px;background:#fffdf9}.client-search input{padding:10px 12px;border:1px solid #cfc3b4;border-radius:10px;font:inherit}.client-search-submit{justify-self:start;padding:8px 13px;border:0;border-radius:9px;background:#1d66d8;color:#fff;font:600 14px/1 Inter,Arial,sans-serif;cursor:pointer}.client-search-submit:disabled{opacity:.6}.client-results{display:grid;gap:5px}.client-results button{padding:8px;border:0;background:transparent;text-align:left;cursor:pointer}.client-results button:hover{background:#f5f0e8}.client-context{margin-top:16px}.client-facts{padding:14px;border-radius:14px;background:#fffdf9;color:#706d68}.client-facts strong{color:#252525}.client-preview{margin-top:16px;overflow:hidden;border:1px solid #dfd6ca;border-radius:20px;background:#f5f0e8}
@media(max-width:620px){.preview-shell{padding:14px}.preview-head{display:grid}.preview-head h1{font-size:21px}.preview-back{width:max-content}}
"""


HTML_TEMPLATE = r"""<div id="offer-simulator">
<style>__COURSE_CSS__</style><style>__SIMULATOR_CSS__</style>
<div class="sim-shell">
  <section class="sim-controls" aria-label="Конструктор сценария">
    <div class="sim-field"><label for="sim-tariff">Тариф мастер-класса</label><select id="sim-tariff"><option value="minimal">Базовый</option><option value="standard">С рецептами</option><option value="consult">С консультацией</option></select></div>
    <div class="sim-field"><label for="sim-placement">Место показа</label><select id="sim-placement"></select></div>
    <div class="sim-owned"><div class="sim-owned-title">Что уже куплено к этому моменту</div><label><input type="checkbox" data-owned="recipes"> Рецепты</label><label><input type="checkbox" data-owned="calories"> Калорийный</label><label><input type="checkbox" data-owned="training"> Тренировки</label><label><input type="checkbox" data-owned="recordings"> Записи консультаций</label><label><input type="checkbox" data-owned="consultation"> Консультация</label></div>
    <div class="sim-facts" id="sim-facts"></div>
    <details class="sim-price-map"><summary>Карта цен всех ступеней</summary><div class="sim-grid" id="sim-price-grid"></div></details>
  </section>
  <section class="sim-preview" aria-live="polite"><div id="sim-screen"></div></section>
</div>
<script>__COURSE_JS__</script>
<script>(()=>{
const root=document.getElementById('offer-simulator'),tariff=root.querySelector('#sim-tariff'),placement=root.querySelector('#sim-placement'),screen=root.querySelector('#sim-screen'),facts=root.querySelector('#sim-facts'),priceGrid=root.querySelector('#sim-price-grid'),checks=[...root.querySelectorAll('[data-owned]')];let timerId=null;
const products=__PRODUCTS_JSON__;
const tariffs={minimal:{name:'Базовый',owned:[]},standard:{name:'С рецептами',owned:['recipes']},consult:{name:'С консультацией',owned:['recipes','consultation']}};
const stages=__SCENARIOS_JSON__;placement.innerHTML=Object.entries(stages).map(([key,cfg])=>`<option value="${key}">${cfg.label}</option>`).join('');
const money=n=>`${new Intl.NumberFormat('ru-RU').format(n)} ₽`;let renderToken=0;
function owned(){const set=new Set(tariffs[tariff.value].owned);checks.forEach(c=>{if(c.checked)set.add(c.dataset.owned)});return [...set]}
function startTimer(expiresAt){if(timerId)clearInterval(timerId);const node=screen.querySelector('#mc-timer');if(!node||!expiresAt)return;const end=new Date(expiresAt),exact=end.toLocaleString('ru-RU',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}),update=()=>{const m=Math.max(0,Math.floor((end-Date.now())/60000)),d=Math.floor(m/1440),h=Math.floor(m%1440/60);node.innerHTML=`<span>Цена действует до ${exact} по вашему времени</span><strong>Осталось: ${d?`${d} дн. `:''}${h} ч ${m%60} мин</strong>`};update();timerId=setInterval(update,60000)}
function bindPreview(data){screen.querySelectorAll('[data-offer],[data-product-buy]').forEach(button=>button.onclick=()=>{const card=data.offers.find(item=>item.code===(button.dataset.offer||button.dataset.productBuy));(card?.items||[]).forEach(code=>{const check=checks.find(item=>item.dataset.owned===code);if(check)check.checked=true});render()});screen.querySelectorAll('[data-product-info]').forEach(button=>button.onclick=()=>{screen.innerHTML=`<main class="mc mc-offer-page mc-product-page">${window.EdabalansMasterclassOfferView.productPresentationMarkup(data,button.dataset.productInfo)}</main>`;screen.querySelector('[data-product-back]').onclick=()=>showOffers(data);startTimer(data.expires_at);bindPreview(data)})}
function showOffers(data){screen.innerHTML=`<main class="mc mc-offer-page">${window.EdabalansMasterclassOfferView.headerMarkup()}${window.EdabalansMasterclassOfferView.markup(data)}</main>`;bindPreview(data);startTimer(data.expires_at)}
async function render(){const token=++renderToken,cfg=stages[placement.value],remaining=cfg.hours==null?null:Math.max(0,cfg.hours-(cfg.elapsedHours||0)),duration=cfg.hours?`${cfg.hours} ч`:'без таймера',windowAction=cfg.hours?(cfg.starts?'запускается при первом открытии':`продолжается без перезапуска${cfg.elapsedHours?`; в превью показано, что прошло ${cfg.elapsedHours} ч`:''}`):'не запускается';facts.innerHTML=`<strong>Системная точка:</strong> ${cfg.placement} · <strong>событие:</strong> ${cfg.event} · <strong>ступень:</strong> ${cfg.stage} · <strong>окно:</strong> ${duration}, ${windowAction}. Карточки рассчитывает тот же backend, что и для клиента.`;const response=await fetch('/api/masterclass/admin/offer-preview',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage_code:cfg.stage,placement:cfg.placement,owned_product_codes:owned(),tariff_name:tariffs[tariff.value].name,remaining_hours:remaining})});if(!response.ok)throw new Error('preview unavailable');const data=await response.json();if(token!==renderToken)return;showOffers(data)}
function renderPriceMap(rows){const order=['early','second','review','last_week','standard'],labels={early:'Ранняя',second:'Вторая',review:'Разбор',last_week:'Неделя',standard:'Обычная'},byCode=Object.fromEntries(rows.map(row=>[row.code,row]));const cells=['Цена',...order.map(code=>labels[code])];[['1 продукт',code=>byCode[code]?.pricing?.single],['2 продукта',code=>byCode[code]?.pricing?.bundle?.['2']],['3 продукта',code=>byCode[code]?.pricing?.bundle?.['3']],['4 продукта',code=>byCode[code]?.pricing?.bundle?.['4']],['Консультация',code=>byCode[code]?.pricing?.consultation]].forEach(([label,get])=>cells.push(label,...order.map(code=>get(code)==null?'—':new Intl.NumberFormat('ru-RU').format(get(code)))));priceGrid.innerHTML=cells.map(value=>`<span>${value}</span>`).join('')}
async function loadCanonicalData(){try{const stageResponse=await fetch('/api/masterclass/admin/offer-stages',{credentials:'same-origin'});if(!stageResponse.ok)throw new Error('offer stage catalog unavailable');const stagePayload=await stageResponse.json(),byCode=Object.fromEntries(stagePayload.stages.map(item=>[item.code,item]));Object.values(stages).forEach(cfg=>{const row=byCode[cfg.stage];if(!row)throw new Error(`missing stage ${cfg.stage}`);if(cfg.hours!=null&&row.duration_hours!=null)cfg.hours=Number(row.duration_hours)});renderPriceMap(stagePayload.stages);const pricingResponse=await fetch('/admin/api/pricing',{credentials:'same-origin'});if(pricingResponse.ok){const pricingPayload=await pricingResponse.json(),version=pricingPayload.versions.find(item=>item.status==='active')||pricingPayload.versions[0];if(version){const tariffMap={'site.masterclass.basic':'minimal','site.masterclass.recipes':'standard','site.masterclass.consult':'consult'},resourceMap={ACCESS_RECIPES:'recipes',ACCESS_CONSULTATION:'consultation'};version.entries.filter(entry=>tariffMap[entry.code]&&entry.enabled).forEach(entry=>{const key=tariffMap[entry.code],item=tariffs[key];item.name=entry.name;item.owned=(entry.resource_codes||[]).map(code=>resourceMap[code]).filter(Boolean);tariff.querySelector(`option[value="${key}"]`).textContent=`${entry.name} · ${money(entry.sale_amount)}`})}}await render()}catch(error){facts.textContent='Не удалось загрузить действующий каталог предложений. Предпросмотр цен отключён, чтобы не показывать устаревшие данные.';screen.innerHTML='<main class="mc mc-offer-page"><section class="mc-card mc-offer-empty"><h2>Предпросмотр временно недоступен</h2><p>Обновите страницу или проверьте серверный каталог предложений.</p></section></main>';priceGrid.innerHTML=''}}
tariff.addEventListener('change',()=>{checks.forEach(c=>c.checked=false);render().catch(()=>{})});placement.addEventListener('change',()=>render().catch(()=>{}));checks.forEach(c=>c.addEventListener('change',()=>render().catch(()=>{})));loadCanonicalData();
})();</script></div>"""


def course_offer_scenarios() -> dict[str, dict]:
    course = json.loads(COURSE_PATH.read_text(encoding="utf-8"))
    scenarios: dict[str, dict] = {}
    first_day_by_stage: dict[str, int] = {}
    for day in course["days"]:
        day_number = int(day["number"])
        for step in day.get("steps", []):
            if step.get("kind") != "offer":
                continue
            placement = step["placement"]
            stage = STAGE_BY_PLACEMENT[placement]
            event = step["event"]
            starts = event == WINDOW_START_EVENTS.get(stage)
            if starts:
                first_day_by_stage.setdefault(stage, day_number)
            if day_number == 1:
                label = "День 1 · первый показ без таймера"
            elif starts:
                label = (
                    f"День {day_number} · запуск окна на "
                    f"{OFFER_STAGE_DURATIONS[stage]} часа"
                )
            else:
                label = f"День {day_number} · повтор окна без продления"
            scenario = {
                "label": label,
                "stage": stage,
                "event": event,
                "placement": placement,
                "hours": None
                if day_number == 1
                else OFFER_STAGE_DURATIONS.get(stage),
                "timerKey": stage,
                "starts": starts,
            }
            if not starts and stage in first_day_by_stage:
                scenario["elapsedHours"] = (
                    day_number - first_day_by_stage[stage]
                ) * 24
            if day_number == 21:
                review_start = first_day_by_stage.get("review", 19)
                scenarios["day21Review"] = {
                    **scenario,
                    "label": "День 21 · review ещё действует · показать остаток",
                    "stage": "review",
                    "hours": OFFER_STAGE_DURATIONS["review"],
                    "timerKey": "review",
                    "elapsedHours": (day_number - review_start) * 24,
                }
                scenarios["day21LastWeek"] = {
                    **scenario,
                    "label": "День 21 · last_week уже идёт · показать остаток",
                    "stage": "last_week",
                    "hours": OFFER_STAGE_DURATIONS["last_week"],
                    "timerKey": "last_week",
                    "elapsedHours": 24,
                }
            else:
                scenarios[f"day{day_number}"] = scenario
    scenarios["standard"] = {
        "label": "После last_week · обычные цены",
        "stage": "standard",
        "event": "нет нового события",
        "placement": "offers-hub",
        "hours": None,
        "starts": False,
    }
    return scenarios


def render_simulator() -> str:
    course_css = (BACKEND_ROOT / "app" / "static" / "masterclass.css").read_text(
        encoding="utf-8"
    )
    course_js = (BACKEND_ROOT / "app" / "static" / "masterclass.js").read_text(
        encoding="utf-8"
    )
    products_json = json.dumps(OFFER_PRODUCTS, ensure_ascii=False, separators=(",", ":"))
    offer_copy_json = json.dumps(
        OFFER_CARD_COPY, ensure_ascii=False, separators=(",", ":")
    )
    scenarios_json = json.dumps(
        course_offer_scenarios(), ensure_ascii=False, separators=(",", ":")
    )
    return (
        "<!-- GENERATED: run backend/scripts/generate_masterclass_offer_simulator.py; do not edit -->\n"
        + HTML_TEMPLATE.replace("__COURSE_CSS__", course_css)
        .replace("__COURSE_JS__", course_js)
        .replace("__SIMULATOR_CSS__", SIMULATOR_CSS)
        .replace("__PRODUCTS_JSON__", products_json)
        .replace("__OFFER_COPY_JSON__", offer_copy_json)
        .replace("__SCENARIOS_JSON__", scenarios_json)
    )


def render_simulator_page(mode: str = "scenario") -> str:
    client_mode = mode == "client"
    scenario_selected = "false" if client_mode else "true"
    client_selected = "true" if client_mode else "false"
    scenario_hidden = " hidden" if client_mode else ""
    client_class = "client-mode is-active" if client_mode else "client-mode"
    client_search_script = """<script>(function(){
var input=document.getElementById('client-email'),submit=document.getElementById('client-search-submit'),results=document.getElementById('client-results'),context=document.getElementById('client-context');
if(!input||!submit||!results)return;
function esc(value){return String(value||'').replace(/[&<>\"']/g,function(char){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[char];});}
function showClient(id){context.textContent='Загружаю данные клиента…';fetch('/api/masterclass/admin/offer-preview/clients/'+encodeURIComponent(id),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error();return response.json();}).then(function(data){var facts='<section class="client-facts"><strong>'+esc(data.client.name||data.client.email)+'</strong><br>'+esc(data.client.email)+'<br>День: '+esc(data.progress.current_day)+' · доступы: '+esc((data.accesses||[]).join(', ')||'нет')+'<p>'+esc(data.reason)+'</p></section>';var offer=data.offer&&window.EdabalansMasterclassOfferView?'<section class="client-preview"><main class="mc mc-offer-page">'+window.EdabalansMasterclassOfferView.headerMarkup()+window.EdabalansMasterclassOfferView.markup(data.offer)+'</main></section>':'';context.innerHTML=facts+offer;}).catch(function(){context.textContent='Не удалось получить контекст клиента. Обновите страницу и попробуйте ещё раз.';});}
function search(){var query=input.value.trim();context.innerHTML='';if(query.length<3){results.textContent='Введите не меньше трёх символов email.';return;}submit.disabled=true;results.textContent='Ищу…';fetch('/api/masterclass/admin/offer-preview/clients?q='+encodeURIComponent(query),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error();return response.json();}).then(function(data){var clients=Array.isArray(data.clients)?data.clients:[];if(!clients.length){results.textContent='Клиент с таким email не найден.';return;}results.innerHTML='';clients.forEach(function(client){var button=document.createElement('button');button.type='button';button.textContent=(client.name||client.email)+' · '+client.email;button.onclick=function(){showClient(client.user_id);};results.appendChild(button);});}).catch(function(){results.textContent='Поиск временно недоступен. Обновите страницу и попробуйте ещё раз.';}).finally(function(){submit.disabled=false;});}
submit.onclick=search;input.onkeydown=function(event){if(event.key==='Enter'){event.preventDefault();search();}};
})();</script>"""
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Предпросмотр дополнительных предложений · edabalans</title><style>{PAGE_CSS}</style></head>
<body><main class="preview-shell"><header class="preview-head"><div><h1>Дополнительные предложения Мастер-класса</h1><p>Сценарный предпросмотр или проверка текущей ситуации конкретного участника.</p></div><a class="preview-back" href="/control">Все инструменты</a></header><p class="preview-source"><strong>Источники:</strong> программа курса определяет места показа; серверный каталог — действующие цены; каталог продуктов — названия и описания; визуальная система курса — оформление карточек.</p><nav class="preview-modes"><button type="button" data-mode="scenario" aria-selected="true">Сценарий</button><button type="button" data-mode="client" aria-selected="false">Клиент</button></nav><section id="scenario-mode">{render_simulator()}</section><section id="client-mode" class="client-mode"><div class="client-search"><strong>Найти клиента</strong><input id="client-email" type="search" placeholder="email клиента" autocomplete="off"><div id="client-results" class="client-results"></div></div><div id="client-context" class="client-context"></div></section><script>(()=>{{const modes=document.querySelectorAll('[data-mode]'),scenario=document.getElementById('scenario-mode'),client=document.getElementById('client-mode'),input=document.getElementById('client-email'),results=document.getElementById('client-results'),context=document.getElementById('client-context');modes.forEach(b=>b.onclick=()=>{{let isClient=b.dataset.mode==='client';modes.forEach(x=>x.setAttribute('aria-selected',String(x===b)));scenario.hidden=isClient;client.classList.toggle('is-active',isClient)}});function esc(s){{const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}}async function show(id){{const r=await fetch('/api/masterclass/admin/offer-preview/clients/'+encodeURIComponent(id),{{credentials:'same-origin'}}),d=await r.json();const h='<section class="client-facts"><strong>'+esc(d.client.name||d.client.email)+'</strong><br>'+esc(d.client.email)+'<br>День: '+d.progress.current_day+' · доступы: '+(d.accesses.join(', ')||'нет')+'<p>'+esc(d.reason)+'</p></section>';context.innerHTML=h+(d.offer?'<section class="client-preview"><main class="mc mc-offer-page"><h1>То, что увидит клиент</h1>'+window.EdabalansMasterclassOfferView.markup(d.offer)+'</main></section>':'')}}let t;input.oninput=()=>{{clearTimeout(t);t=setTimeout(async()=>{{if(input.value.trim().length<3){{results.innerHTML='';return}}const r=await fetch('/api/masterclass/admin/offer-preview/clients?q='+encodeURIComponent(input.value),{{credentials:'same-origin'}}),d=await r.json();results.innerHTML=d.clients.map(x=>'<button type="button" data-id="'+x.user_id+'">'+esc(x.name||x.email)+' · '+esc(x.email)+'</button>').join('')||'Никого не найдено';results.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>show(b.dataset.id))}},250)}})();</script></main></body></html>"""
    return (
        page.replace(
            '<nav class="preview-modes"><button type="button" data-mode="scenario" aria-selected="true">Сценарий</button><button type="button" data-mode="client" aria-selected="false">Клиент</button></nav>',
            f'<nav class="preview-modes"><a href="/admin/masterclass-offers-preview" aria-selected="{scenario_selected}">Сценарий</a><a href="/admin/masterclass-offers-preview?mode=client" aria-selected="{client_selected}">Клиент</a></nav>',
        )
        .replace('<section id="scenario-mode">', f'<section id="scenario-mode"{scenario_hidden}>')
        .replace('<section id="client-mode" class="client-mode">', f'<section id="client-mode" class="{client_class}">')
        .replace('autocomplete="off"><div id="client-results"', 'autocomplete="off"><button type="button" class="client-search-submit" id="client-search-submit">Найти</button><div id="client-results"')
        .replace('</section><script>(()=>', f'</section>{client_search_script}<script>(()=>')
        .replace('</script></main></body>', '</script><script>var clientInput=document.getElementById("client-email");if(clientInput)clientInput.oninput=null;</script></main></body>')
        .replace('<h1>То, что увидит клиент</h1>', '')
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_simulator_page(), encoding="utf-8")


if __name__ == "__main__":
    main()
