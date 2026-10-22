export const VERSION = 'policy-0.4.1';
const copy = value => structuredClone(value);
const known = value => value !== '' && value !== null && value !== undefined && Number.isFinite(Number(value));
const number = value => known(value) ? Number(value) : null;
const effort = row => number(row?.rpe);
const rir = row => Math.min(3, Math.max(0, 10 - effort(row)));
const capacity = row => Number(row.w) * (1 + (Number(row.r) + rir(row)) / 30);
const complete = (row, mode) => row && known(row.r) && row.r > 0 && (mode === 'duration' || Number.isInteger(Number(row.r))) && (mode !== 'external' || known(row.w) && row.w > 0);
const attained = (row, base, mode) => complete(row, mode) && row.role === 'work' && row.w === base.w && row.r >= base.r;
const cost = (row, actual, mode) => mode === 'duration' ? 0 : Math.max(0,
  Math.log((30 + row.r) / (30 + actual.r)) + (mode === 'external' ? Math.log(row.w / actual.w) : 0),
  mode === 'external' ? Math.log(row.w / actual.w) : 0);

// This is a reference policy for synthetic experiments, not a clinically validated predictor.
export function recommend(input) {
  const p = input.profile, base = copy(input.baseline), mode = p.mode || 'external';
  const records = input.history.filter(h => h.date && h.date <= input.targetDate)
    .toSorted((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id)).slice(-5);
  const work = base.flatMap((row, i) => row.role === 'warmup' ? [] : [i]);
  const result = {version: VERSION, code: 'hold', next: base, changed: [], used: records.map(h => h.id),
    reasons: [], formulas: [], budget: 0, granularity: false};
  const hold = (code, reason) => { result.code = code; result.reasons.push(reason); return result; };
  if (!['external', 'bodyweight', 'assisted', 'duration'].includes(mode)) return hold('unsupported', 'Нужна настройка типа упражнения.');
  if (!work.length) return hold('no-work', 'Нет отмеченных рабочих подходов.');
  const [lo, hi] = mode === 'duration' ? p.timeRange || [] : p.range || [];
  if (!(lo > 0 && hi >= lo) || mode !== 'duration' && (!Number.isInteger(lo) || !Number.isInteger(hi)) || base.some(row => !['warmup', 'work'].includes(row.role)) || work.some(i => !known(base[i].r) || base[i].r <= 0 || mode !== 'duration' && !Number.isInteger(Number(base[i].r)) || !known(base[i].w) || base[i].w < 0)) {
    return hold('configuration', 'Нужны корректные диапазон, обычный базовый план и роли подходов.');
  }
  if (mode === 'external' && (!Array.isArray(p.loads) || !p.loads.length || p.loads.some((w, i) => !(w > 0) || i && w <= p.loads[i - 1]))) {
    return hold('configuration', 'Нужна возрастающая лестница доступных весов.');
  }
  if (mode === 'duration' && !(Number.isFinite(p.timeStep) && p.timeStep > 0)) return hold('configuration', 'Для времени нужен явно настроенный положительный шаг.');
  if (!records.length) return hold('no-history', 'Нет предшествующих фактических записей.');
  const latest = records.at(-1);
  if (latest.hold || latest.pain || latest.techniqueIssue) return hold('coach', 'Есть явное ограничение: решение тренера.');
  if (latest.reduced) return hold('reduced', 'Облегчённый день сохранён; обычная база повторяется без новой прибавки.');
  if (latest.changedConditions) return hold('conditions', 'Условия изменены: сначала подтвердить сопоставимость.');
  const ordinary = records.filter(h => !h.reduced && !h.changedConditions && !h.hold && !h.pain && !h.techniqueIssue);
  const a = ordinary.at(-1), b = ordinary.at(-2);
  if (!a || a !== latest) return hold('context', 'Последнюю запись нельзя молча заменить более удобной старой.');
  if (work.some(i => !complete(a.sets[i], mode))) return hold('partial', 'Последний факт неполный; пустые строки не считаются нулём или выполненным планом.');
  if (work.some(i => a.sets[i].role !== 'work' || a.sets[i].w !== base[i].w)) return hold('conditions', 'Изменены роль или принятая базовая пара веса: требуется подтверждение тренера.');
  if (work.some(i => effort(a.sets[i]) !== null && (effort(a.sets[i]) < 5 || effort(a.sets[i]) > 10))) return hold('invalid-rpe', 'RPE должен быть пустым либо от 5 до 10.');

  // Up to five original records provide context; never use a previous prediction as a fact.
  const enoughBase = h => work.every(i => attained(h.sets[i], base[i], mode));
  const stable = (x, y) => work.every(i => {
    const u = x.sets[i], v = y.sets[i];
    if (!complete(u, mode) || !complete(v, mode)) return false;
    if (u.w === v.w) return Math.abs(u.r - v.r) <= Math.max(1, (u.r + v.r) * .05);
    return mode === 'external' && effort(u) !== null && effort(v) !== null && Math.abs(capacity(u) / capacity(v) - 1) <= .05;
  });
  let anchor = null;
  for (let j = ordinary.length - 3; j >= 0; j--) {
    if (enoughBase(ordinary[j]) && enoughBase(ordinary[j + 1]) && stable(ordinary[j], ordinary[j + 1])) {
      anchor = base.map((row, i) => ({...row, r: (ordinary[j].sets[i].r + ordinary[j + 1].sets[i].r) / 2})); break;
    }
  }
  const severe = h => h && work.filter(i => complete(h.sets[i], mode) && h.sets[i].role === 'work' && h.sets[i].w === (anchor || base)[i].w && h.sets[i].r <= (anchor || base)[i].r * .8).length >= Math.min(2, work.length);
  if (severe(a)) return hold(b && severe(b) ? 'repeated-drop' : anchor ? 'possible-outlier' : 'large-miss', b && severe(b)
    ? 'Повторяющийся сильный спад: сохранить базу и показать тренеру, без автоматической разгрузки.'
    : anchor ? 'Сильный спад относительно устойчивого участка: повторить базу без прибавки; причина не диагностируется.'
    : 'Большое недовыполнение базовой цели, но устойчивого прошлого участка не хватает. Повтор без дополнительного роста.');

  work.forEach(i => { if (a.sets[i].w === base[i].w) base[i].r = Math.max(base[i].r, a.sets[i].r); });
  if (work.every(i => effort(a.sets[i]) !== null && effort(a.sets[i]) >= 9)) return hold('all-high-rpe', 'Все рабочие подходы RPE9–10: повторить план. Разминка не открывает прибавку.');
  const knownReady = work.filter(i => effort(a.sets[i]) !== null && effort(a.sets[i]) <= 8);
  const wave = work.length === 1 ? [...work] : [work.at(-2), work.at(-1), ...work.slice(0, -2).reverse()];
  if (!knownReady.length) {
    if (!b || !enoughBase(a) || !enoughBase(b)) return hold('no-rpe-history', 'Без рабочего запаса нужны две выполненные сопоставимые записи для осторожного роста повторов.');
    const i = wave.find(i => effort(a.sets[i]) === null && base[i].r < hi);
    if (i === undefined) return hold('no-reserve', 'Нет готовой позиции с неизвестным RPE и местом до верхней границы.');
    const delta = mode === 'duration' ? p.timeStep : 1;
    base[i].r = Math.min(hi, base[i].r + delta);
    result.code = 'conservative-reps'; result.changed = [i];
    result.reasons.push('Два выполнения без RPE: один небольшой шаг в одной неизвестной строке, вес неизменен.');
    return result;
  }
  const ready = work.filter(i => effort(a.sets[i]) !== null && effort(a.sets[i]) <= 9)
    .sort((i, j) => effort(a.sets[i]) - effort(a.sets[j]) || wave.indexOf(i) - wave.indexOf(j));
  result.queue = ready.map(i => i + 1);
  if (mode === 'duration') {
    const i = ready.find(i => effort(a.sets[i]) <= 8 && attained(a.sets[i], base[i], mode) && base[i].r < hi);
    if (i === undefined) return hold('no-candidate', 'Время повторить: готовой позиции до верхней границы нет.');
    base[i].r = Math.min(hi, base[i].r + p.timeStep); result.changed = [i]; result.code = 'time';
    result.reasons.push('Один настроенный шаг времени; формула Epley не применяется.'); return result;
  }
  const previousInformative = b && work.every(i => complete(b.sets[i], mode) && b.sets[i].role === 'work');
  const budgetLimit = previousInformative ? .03 : .015;
  const totalCost = candidate => work.reduce((sum, i) => sum + cost(candidate[i], a.sets[i], mode), 0) / work.length;
  const initialCost = totalCost(base);
  if (initialCost > budgetLimit + 1e-10) return hold('catch-up', 'Повтор базовой цели уже превышает условный бюджет; дополнительной прибавки нет.');
  let exception = null;
  for (let pass = 0; pass < 2; pass++) for (const i of ready) {
    const fact = a.sets[i], target = base[i];
    if (result.changed.includes(i) && result.formulas.some(f => f.set === i + 1)) continue;
    let candidate;
    if (target.r < hi && target.r + 1 - fact.r <= Math.max(0, rir(fact) - 1) && target.r + 1 >= lo) {
      candidate = {...target, r: target.r + 1};
    } else if (pass === 0 && mode === 'external' && target.r >= hi && fact.r >= hi) {
      const w = p.loads.find(w => w > target.w);
      if (w === undefined) continue;
      const r = Math.min(hi, fact.r, Math.floor(30 * (capacity(fact) / w - 1) - 1 + 1e-10));
      if (r < lo) { result.reasons.push('Следующая ступень в подходе ' + (i + 1) + ' выводит прогноз ниже диапазона.'); continue; }
      candidate = {...target, w, r};
    }
    if (!candidate) continue;
    const trial = copy(base); trial[i] = candidate;
    if (totalCost(trial) <= budgetLimit + 1e-10) {
      base[i] = candidate; if (!result.changed.includes(i)) result.changed.push(i);
      if (candidate.w !== fact.w) result.formulas.push({set: i + 1, capacity: capacity(fact), weight: candidate.w, reps: candidate.r});
    } else if (!result.changed.length && effort(fact) <= 8 && candidate.w !== fact.w && previousInformative && enoughBase(a) && enoughBase(b) && !exception) exception = {i, candidate};
  }
  if (!result.changed.length && exception) {
    base[exception.i] = exception.candidate; result.changed = [exception.i]; result.granularity = true;
    result.formulas.push({set: exception.i + 1, capacity: capacity(a.sets[exception.i]), weight: exception.candidate.w, reps: exception.candidate.r});
  }
  result.budget = totalCost(base);
  result.code = result.changed.length ? result.granularity ? 'one-real-step' : 'progress' : 'no-candidate';
  result.reasons.push(result.changed.length ? result.granularity ? 'Одна реальная ступень выше условного бюджета; без остальных новых прибавок.'
    : 'Рост в готовых рабочих позициях; готовность важнее очереди, при равенстве — предпоследний, последний, остальные.'
    : 'Допустимой новой прибавки сейчас нет: повтор базовой цели.');
  return result;
}

const filled = value => value !== '' && value !== null && value !== undefined;
const uiNumber = value => filled(value) ? Number(String(value).replace(',', '.')) : '';
const byExercise = (session, id) => session.exercises.find(exercise => String(exercise.id) === String(id));

// The target card is the destination, never evidence for its own prescription.
export function cardRequest(sessions, targetIndex, exerciseId, profile) {
  const target = sessions[targetIndex], exercise = target && byExercise(target, exerciseId);
  if (!exercise) throw new Error('В этой тренировке нет сохранённой записи упражнения.');
  const prior = sessions.slice(0, targetIndex).flatMap((session, order) => {
    const item = byExercise(session, exerciseId);
    return item && item.sets.some(row => filled(row.factWeight) || filled(row.factReps)) ? [{session, exercise:item, order}] : [];
  });
  if (!prior.length) throw new Error('Нужна хотя бы одна предыдущая запись с фактом этого упражнения.');
  if (prior.some(item => !/^\d{4}-\d{2}-\d{2}$/.test(item.session.date || ''))) throw new Error('Укажите дату в предыдущих тренировках с фактом этого упражнения.');
  const targetDate = target.date || prior.reduce((date,item)=>item.session.date > date ? item.session.date : date,'');
  const comparable = prior.filter(item=>item.session.date<=targetDate).toSorted((a,b)=>a.session.date.localeCompare(b.session.date)||a.order-b.order);
  if (!comparable.length) throw new Error('Нет факта этого упражнения до даты выбранной тренировки.');
  const latest = comparable.at(-1).exercise, hasPlan = exercise.sets.some(row => filled(row.planWeight) || filled(row.planReps));
  if (profile.last_reduced && !hasPlan) throw new Error('После облегчённой тренировки сначала задайте обычный базовый план в этой карточке.');
  const baseline = exercise.sets.map((row, i) => {
    const source = hasPlan ? row : latest.sets[i] || {};
    let w = uiNumber(source.planWeight), r = uiNumber(source.planReps);
    if (!hasPlan) {
      if (!filled(w)) w = uiNumber(source.factWeight);
      if (!filled(r)) r = uiNumber(source.factReps);
    }
    if (!filled(w) && ['bodyweight','duration'].includes(profile.mode)) w = 0;
    return {w,r,role:row.role === 'warmup' ? 'warmup' : 'work'};
  });
  // The policy sorts ties by id. Supply journal order rather than random UUID order.
  const history = comparable.map(({session,exercise:item,order}) => ({id:String(order).padStart(12,'0'),date:session.date,
    sets:item.sets.map(row => ({w:!filled(row.factWeight) && ['bodyweight','duration'].includes(profile.mode) ? 0 : uiNumber(row.factWeight),
      r:uiNumber(row.factReps),rpe:uiNumber(row.rpe),role:row.role === 'warmup' ? 'warmup' : 'work'}))}));
  Object.assign(history.at(-1),{reduced:!!profile.last_reduced,changedConditions:!!profile.changed_conditions,hold:!!profile.hold});
  const [lo,hi] = profile.rep_range || [];
  if (lo > 0 && hi >= lo) {
    const work = baseline.flatMap((row,i)=>row.role==='work'?[i]:[]), latestFact=history.at(-1);
    if (work.some(i=>filled(baseline[i].r) && (baseline[i].r < lo || baseline[i].r > hi)) ||
        work.some(i=>latestFact.sets[i]?.role==='work' && filled(latestFact.sets[i].r) && latestFact.sets[i].r > hi)) {
      throw new Error('Базовый план или последний рабочий факт выходит за выбранный диапазон. Уточните диапазон или базовый план перед расчётом.');
    }
  }
  const p = {mode:profile.mode,range:profile.rep_range,timeRange:profile.rep_range,timeStep:profile.time_step};
  if (p.mode === 'external') {
    const step = Number(profile.load_step), weights = baseline.filter(row => row.role === 'work').map(row => row.w);
    if (!(step > 0 && Number.isFinite(step))) throw new Error('Укажите фактический положительный шаг прибавки веса вашего оборудования.');
    if (weights.some(w => !filled(w) || !Number.isFinite(w) || w <= 0)) throw new Error('Нужен заполненный базовый план рабочих подходов.');
    const min = Math.min(...weights);
    if (weights.some(w => Math.abs((w-min)/step-Math.round((w-min)/step)) > 1e-7)) throw new Error('Рабочие веса не совпадают с указанной ступенью. Проверьте шаг оборудования и базовый план.');
    p.loads = [...new Set(weights.flatMap(w => [w,Number((w+step).toFixed(6))]))].sort((a,b)=>a-b);
  }
  const input = {profile:p,baseline,history,targetDate};
  return {input,sourceIds:comparable.slice(-2).map(item=>({number:item.session.number,date:item.session.date})),
    fingerprint:JSON.stringify({targetId:target.session_id,targetDate:target.date,sets:exercise.sets,input})};
}
