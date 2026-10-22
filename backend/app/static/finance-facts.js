(() => {
  const byId=id=>document.getElementById(id);
  const money=value=>value===null||value===undefined?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(value)+' ₽';
  const num=value=>value===null||value===undefined?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value);
  const pct=value=>value===null||value===undefined?'—':num(value)+'%';
  const model=window.financeModel;
  const state={mode:'plan',data:null,sequence:0};
  const monthParts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit'}).formatToParts(new Date());
  const currentMonth=monthParts.find(x=>x.type==='year').value+'-'+monthParts.find(x=>x.type==='month').value;
  byId('fact-month').value=currentMonth;byId('fact-month').max=currentMonth;
  const labels={MASTERCLASS_BASIC:'Минимальный',MASTERCLASS_RECIPES:'Стандартный',MASTERCLASS_CONSULT:'С консультацией',
    COACHING:'Сопровождение',CONSULTATION:'Разовый разбор',RECIPES_ADDON:'Доп · рецепты',
    CALORIES_COURSE:'Доп · калорийный курс',TRAINING_COURSE:'Доп · тренировки',UNASSIGNED:'Назначение не определено'};
  function set(id,value){byId(id).textContent=value;}
  function rows(id,items){
    const root=byId(id);root.replaceChildren();
    for(const [label,value] of items){const row=document.createElement('div');row.className='row';
      const name=document.createElement('span');name.textContent=label;
      const val=document.createElement('b');val.textContent=value;row.append(name,val);root.append(row);}
  }
  function table(id,items){
    const root=byId(id);root.replaceChildren();
    if(!items.length){const row=root.insertRow();const cell=row.insertCell();cell.colSpan=5;cell.textContent='Нет наблюдаемых записей за выбранный период.';return;}
    for(const values of items){const row=root.insertRow();for(const value of values){const cell=row.insertCell();if(value instanceof Node)cell.append(value);else cell.textContent=value;}}
  }
  function clearCards(){document.querySelectorAll('.finance-summary b').forEach(el=>el.textContent='—');}
  function render(data){
    if(state.mode==='plan')return;
    byId('fact-view').querySelector('.fact-grid').hidden=false;
    const p=model.values(), r=data.receipts, c=data.cohort, expenses=data.expenses;
    const fees=r.revenue*p.feeRate/100;
    const income=expenses.ads===null||expenses.opex===null?null:r.revenue-fees-expenses.ads-expenses.opex;
    const consultUnits=data.categories.filter(x=>['CONSULTATION','MASTERCLASS_CONSULT'].includes(x.code)).reduce((n,x)=>n+x.payments,0);
    const labor=data.support.other_payments?null:(consultUnits+data.support.monthly_payments*2)*p.timeUnit;
    const margin=income===null||labor===null?null:income-labor;
    set('personal',money(income));set('turnover',money(r.revenue));set('consult-income',money(labor));set('business-margin',money(margin));
    set('club-card','нет данных');set('ads-card',money(expenses.ads));set('opex-card',money(expenses.opex));
    set('paid-card',num(r.buyer_sources.paid));set('organic-card',num(r.buyer_sources.organic));
    byId('personal').className=income<0?'bad':'';byId('business-margin').className=margin<0?'bad':'';
    const date=new Date(data.period.as_of).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'});
    set('fact-title',state.mode==='all'?'Факт с 1 сентября 2026':new Date(data.period.start).toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow',month:'long',year:'numeric'}));
    set('fact-status',`По состоянию на ${date} МСК. Доход, маржа, комиссии и стоимость времени — расчёт по ставкам плана.`);
    document.querySelector('.finance-summary').setAttribute('aria-label','Фактический результат выбранного периода');
    const meanLtv=data.people.length?data.people.reduce((sum,x)=>sum+x.observed_ltv,0)/data.people.length:null;
    const addons=data.categories.filter(x=>['RECIPES_ADDON','CALORIES_COURSE','TRAINING_COURSE'].includes(x.code));
    const addonCount=addons.reduce((n,x)=>n+x.payments,0);
    rows('fact-money',[
      ['Поступления · подтверждённые RUB',money(r.revenue)],['Оплат / известных покупателей',num(r.payment_count)+' / '+num(r.buyers)],
      [`Налоги + эквайринг · расчёт ${num(p.feeRate)}%`,money(fees)],['Доход · расчёт после внесённых расходов',money(income)],
      ['Стоимость времени · расчёт',money(labor)],['Маржа · расчёт',money(margin)],
      ['Покупатели · источник не определён',num(r.buyer_sources.unknown)],['Оплаты без связи с человеком',num(r.unlinked_payments)],
      ['Неподтверждённая сумма или другая валюта',num(r.uncertain_amounts)],
      ['Средняя накопленная выручка этих покупателей с 01.09',money(meanLtv)],
      ['Средний чек распознанной покупки допа',money(addonCount?addons.reduce((n,x)=>n+x.amount,0)/addonCount:null)]
    ]);
    rows('fact-cohort',[
      ['Наблюдаемых новых входов',num(c.observed_entries)],['Лидов в базе расчёта конверсии',num(c.leads)],
      ['Первая покупка · за 30 дней',`${num(c.early_buyers)} · ${pct(c.early_rate)}`],
      ['Первая покупка · позже',`${num(c.late_buyers)} · ${pct(c.late_rate)}`],['Конверсия всего на дату отчёта',pct(c.total_rate)],
      ['Ещё не прошло 30 дней',num(c.under_30_days)],['Покупали до наблюдаемого входа',num(c.already_buyers)],
      ['Неизвестна дата первой оплаты',num(c.unknown_first_purchase)]
    ]);
    table('fact-conversions',Object.entries(data.cohort.groups).map(([key,x])=>[
      ({paid:'Платные',organic:'Органические',unknown:'Тип источника не определён'})[key],num(x.leads),
      `${num(x.early_buyers)} · ${pct(x.early_rate)}`,`${num(x.late_buyers)} · ${pct(x.late_rate)}`,pct(x.total_rate)]));
    rows('fact-products',data.categories.length?data.categories.map(x=>[labels[x.code]||x.label||x.code,`${num(x.payments)} оплат · ${money(x.amount)}`]):[['Платежи с известной суммой','нет записей']]);
    rows('fact-support',[
      ['Оплат сопровождения за период',num(data.support.payment_count)],['Из них по месячной подписке',num(data.support.monthly_payments)],
      ['Другие оплаты сопровождения',num(data.support.other_payments)],['Поступления сопровождения',money(data.support.amount_rub)],
      ['Фактически проведённые консультации','нет журнала'],['Длительность разовых оплат','требуется назначение периода'],['Клуб','источник не подключён']
    ]);
    table('fact-people',data.people.map(x=>{const link=document.createElement('a');link.href='/crm?user='+encodeURIComponent(x.user_id);link.textContent=x.name;return[link,money(x.period_revenue),money(x.observed_ltv),num(x.support.payment_count)];}));
    const coverage=byId('fact-coverage');coverage.replaceChildren();
    const notes=[`Подтверждённые оплаты CRM в рублях, с точной датой и известной суммой. Оплат с неизвестной или оценочной датой в истории: ${data.coverage.undated_payments}.`,
      `Неразобранных назначений за период: ${data.coverage.unclassified_payments}. Расходы внесены за ${expenses.months_recorded} из ${expenses.months_total} месяцев.`,
      `Расчётные ставки плана: комиссии ${num(p.feeRate)}%, консультационная единица ${money(p.timeUnit)}. Стоимость времени для подписки — две единицы на оплаченный месяц; неизвестные периоды разовых оплат не подменяются месяцами.`,
      'Конверсия допов и фактическая длительность работы пока не рассчитываются.',...data.coverage.notes];
    for(const note of notes){const el=document.createElement('p');el.textContent=note;coverage.append(el);}
    const edit=state.mode==='month';byId('fact-expenses').hidden=!edit;
    set('expense-help',edit?'Пусто — сумма неизвестна. Ноль — подтверждено, что расходов не было. Здесь ручной учёт; Direct автоматически не добавляется.':'Расходы редактируются помесячно. Для ввода или исправления выбери «Факт · месяц». Итог за всё время показан в верхних плашках.');
    if(edit){byId('expense-ads').value=expenses.ads??'';byId('expense-opex').value=expenses.opex??'';}
  }
  async function loadFacts(){
    const seq=++state.sequence;
    const month=state.mode==='all'?'':byId('fact-month').value;
    if(state.mode!=='plan'){clearCards();set('fact-status','Загрузка фактических показателей…');byId('fact-retry').hidden=true;byId('fact-expenses').hidden=true;byId('fact-view').querySelector('.fact-grid').hidden=true;byId('fact-view').setAttribute('aria-busy','true');}
    try{
      const response=await fetch('/admin/api/finance/facts'+(month?'?month='+encodeURIComponent(month):''),{credentials:'same-origin'});
      if(!response.ok)throw new Error(response.status===401?'Нужно войти в админку.':'Не удалось получить данные за период.');
      const data=await response.json();if(seq!==state.sequence)return;
      byId('preview-banner').hidden=response.headers.get('X-Finance-Demo')!=='1';
      state.data=data;render(data);
    }catch(error){if(seq!==state.sequence)return;state.data=null;if(state.mode!=='plan'){set('fact-status',error.message);byId('fact-retry').hidden=false;document.querySelectorAll('#fact-view .row').forEach(el=>el.remove());for(const id of ['fact-conversions','fact-people'])table(id,[]);}}
    finally{if(seq===state.sequence)byId('fact-view').removeAttribute('aria-busy');}
  }
  function switchMode(mode){
    state.mode=mode;state.sequence++;
    document.querySelectorAll('[data-finance-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.financeMode===mode)));
    byId('plan-view').hidden=mode!=='plan';byId('finance-plan-controls').hidden=mode!=='plan';byId('fact-view').hidden=mode==='plan';byId('fact-month-control').hidden=mode!=='month';
    if(mode==='plan'){model.calculate();document.querySelector('.finance-summary').setAttribute('aria-label','Результат в устойчивый месяц');}
    else loadFacts();
  }
  document.querySelectorAll('[data-finance-mode]').forEach(button=>button.addEventListener('click',()=>switchMode(button.dataset.financeMode)));
  byId('fact-month').addEventListener('change',loadFacts);byId('fact-retry').addEventListener('click',loadFacts);
  document.addEventListener('finance-plan-ready',()=>{if(state.mode!=='plan'&&state.data)render(state.data);});
  byId('fact-expenses').addEventListener('submit',async event=>{
    event.preventDefault();if(state.mode!=='month'||!state.data)return;
    const button=event.target.querySelector('button');button.disabled=true;
    const value=id=>byId(id).value.trim()===''?null:Number(byId(id).value);
    try{const response=await fetch('/admin/api/finance/expenses',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Finance-Write':'1'},
      body:JSON.stringify({month:byId('fact-month').value,ads:value('expense-ads'),opex:value('expense-opex')})});
      if(!response.ok)throw new Error('Не удалось сохранить расходы.');set('expense-status','Расходы сохранены.');await loadFacts();
    }catch(error){set('expense-status',error.message);}finally{button.disabled=false;}
  });
  loadFacts();
})();
