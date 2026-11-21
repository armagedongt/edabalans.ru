export const VERSION = 'policy-0.5.1';
const copy = value => structuredClone(value);
const known = value => value !== '' && value !== null && value !== undefined && Number.isFinite(Number(value));
const number = value => known(value) ? Number(value) : null;
const effort = row => number(row?.rpe);
const rir = row => Math.min(3, Math.max(0, 10 - effort(row)));
const capacity = row => Number(row.w) * (1 + (Number(row.r) + rir(row)) / 30);
const complete = (row, mode) => row && known(row.r) && row.r > 0 && (mode === 'duration' || Number.isInteger(Number(row.r))) && (mode !== 'external' || known(row.w) && row.w > 0);
const recorded = (row, mode) => row && known(row.w) && row.w >= 0 && known(row.r) && row.r > 0 && (mode === 'duration' || Number.isInteger(Number(row.r)));
const attained = (row, base, mode) => complete(row, mode) && row.role === 'work' && row.w === base.w && row.r >= base.r;
const cost = (row, actual, mode) => mode === 'duration' ? 0 : Math.max(0,
  Math.log((30 + row.r) / (30 + actual.r)) + (mode === 'external' ? Math.log(row.w / actual.w) : 0),
  mode === 'external' ? Math.log(row.w / actual.w) : 0);

// This is a reference policy for synthetic experiments, not a clinically validated predictor.
export function recommend(input) {
  const p = input.profile, base = copy(input.baseline), mode = p.mode || 'external';
  const records = input.history.filter(h => h.date && h.date <= input.targetDate)
    .toSorted((a, b) => input.historyOrder === 'journal' ? a.id.localeCompare(b.id)
      : a.date.localeCompare(b.date) || a.id.localeCompare(b.id)).slice(-5);
  const allWork = base.flatMap((row, i) => row.role === 'warmup' ? [] : [i]);
  const result = {version: VERSION, code: 'hold', next: base, changed: [], used: records.map(h => h.id),
    reasons: [], formulas: [], budget: 0, granularity: false};
  const hold = (code, reason) => {
    result.next = copy(input.baseline);
    result.code = code;
    result.reasons.push(reason);
    return result;
  };
  if (input.alreadyApplied) return hold('already-applied', 'По этим результатам план уже рассчитан. Новую прибавку не добавляем.');
  if (input.limitation) {
    const {code, reason} = input.limitation;
    if (code === 'no-history' && input.offerStarter && ['external','bodyweight','assisted','duration'].includes(mode)) {
      const [min,max] = (mode === 'duration' ? p.timeRange : p.range) || [];
      if (Number.isFinite(min) && Number.isFinite(max) && min > 0 && max >= min &&
          (mode === 'duration' || Number.isInteger(min) && Number.isInteger(max))) {
        for (const i of allWork) base[i].r = min;
        result.code = code;
        result.reasons.push('Черновик с нижней границы диапазона. Подходящую нагрузку выберите на тренировке; план не записан.');
        return result;
      }
    }
    return hold(code, reason);
  }
  if (!['external', 'bodyweight', 'assisted', 'duration'].includes(mode)) return hold('unsupported', 'Нужна настройка типа упражнения.');
  if (!allWork.length) return hold('no-work', 'Нет отмеченных рабочих подходов.');
  const [lo, hi] = mode === 'duration' ? p.timeRange || [] : p.range || [];
  const validRange = Number.isFinite(lo) && Number.isFinite(hi) && lo > 0 && hi >= lo &&
    (mode === 'duration' || Number.isInteger(lo) && Number.isInteger(hi));
  if (!validRange || base.some(row => !['warmup', 'work'].includes(row.role))) {
    return hold('configuration', 'Укажите рабочий диапазон. Текущий план сохранён.');
  }
  const canRaiseWeight = mode === 'external' && Array.isArray(p.loads) && p.loads.length > 0 &&
    p.loads.every((w, i) => Number.isFinite(w) && w > 0 && (!i || w > p.loads[i - 1]));
  if (mode === 'duration' && !(Number.isFinite(p.timeStep) && p.timeStep > 0)) return hold('configuration', 'Для времени нужен явно настроенный положительный шаг.');
  if (!records.length) return hold('no-history', 'Нет предшествующих фактических записей.');
  const latest = records.at(-1);
  if (latest.hold || latest.pain || latest.techniqueIssue) return hold('coach', 'Есть явное ограничение: решение тренера.');
  if (latest.reduced) return hold('reduced', 'Облегчённый день сохранён; обычная база повторяется без новой прибавки.');
  if (latest.changedConditions) return hold('conditions', 'Условия изменены: сначала подтвердить сопоставимость.');
  const ordinary = records.filter(h => !h.reduced && !h.changedConditions && !h.hold && !h.pain && !h.techniqueIssue);
  const a = ordinary.at(-1), b = ordinary.at(-2);
  if (!a || a !== latest) return hold('context', 'Последнюю запись нельзя молча заменить более удобной старой.');
  const comparableWork = allWork.filter(i => {
    const fact = a.sets[i], row = base[i];
    return complete(fact, mode) && complete(row, mode) && known(row.w) && row.w >= 0 &&
      known(fact.w) && fact.role === 'work' && fact.w === row.w &&
      (mode !== 'assisted' || fact.w >= 0);
  });
  const work = comparableWork.filter(i => {
    const fact = a.sets[i], row = base[i], rpe = effort(fact);
    return row.r >= lo && row.r <= hi && fact.r <= hi &&
      (rpe === null || rpe >= 5 && rpe <= 10);
  });
  if (!work.length && comparableWork.some(i => base[i].r < lo || base[i].r > hi || a.sets[i].r > hi)) {
    return hold('range', 'Факт вне выбранного диапазона. Уточните диапазон, если хотите учесть эти повторы.');
  }
  if (!work.length) return hold('partial', 'Нет сопоставимых рабочих подходов для прибавки. Проверьте вес, повторы и диапазон.');
  const partial = work.length !== allWork.length;
  const repetitionsOnly = partial || (mode === 'external' && !canRaiseWeight);
  if (partial) result.reasons.push('Подходы с пропущенными или несопоставимыми данными оставлены без изменений.');
  if (mode === 'external' && !canRaiseWeight) result.reasons.push('Шаг оборудования не задан или не совпадает с рабочими весами. Можно менять только повторы.');

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
      anchor = copy(base);
      for (const i of work) anchor[i].r = (ordinary[j].sets[i].r + ordinary[j + 1].sets[i].r) / 2;
      break;
    }
  }
  const severe = h => h && comparableWork.filter(i => complete(h.sets[i], mode) && h.sets[i].role === 'work' && h.sets[i].w === (anchor || base)[i].w && h.sets[i].r <= (anchor || base)[i].r * .8).length >= Math.min(2, comparableWork.length);
  if (severe(a)) return hold(b && severe(b) ? 'repeated-drop' : anchor ? 'possible-outlier' : 'large-miss', b && severe(b)
    ? 'Повторяющийся сильный спад: сохранить базу и показать тренеру, без автоматической разгрузки.'
    : anchor ? 'Сильный спад относительно устойчивого участка: повторить базу без прибавки; причина не диагностируется.'
    : 'Большое недовыполнение базовой цели, но устойчивого прошлого участка не хватает. Повтор без дополнительного роста.');


  if (repetitionsOnly && work.some(i => base[i].r > a.sets[i].r && effort(a.sets[i]) !== null && base[i].r - a.sets[i].r <= Math.max(0, rir(a.sets[i]) - 1))) {
    return hold('existing-target', 'В плане уже есть прибавка к последнему факту. Оставляем её до следующей тренировки.');
  }
  if (!repetitionsOnly) for (const i of work) base[i].r = Math.max(base[i].r, a.sets[i].r);
  if (work.every(i => effort(a.sets[i]) !== null && effort(a.sets[i]) >= 9)) return hold('all-high-rpe', 'Все рабочие подходы RPE9–10: повторить план. Разминка не открывает прибавку.');
  const knownReady = work.filter(i => effort(a.sets[i]) !== null && effort(a.sets[i]) <= 8);
  const wave = work.length === 1 ? [...work] : [work.at(-2), work.at(-1), ...work.slice(0, -2).reverse()];
  if (!knownReady.length) {
    if (repetitionsOnly) return hold('partial', 'Для осторожной прибавки нужен подход с известным запасом повторов.');
    if (!b || !enoughBase(a) || !enoughBase(b)) return hold('no-rpe-history', 'Без рабочего запаса нужны две выполненные сопоставимые записи для осторожного роста повторов.');
    const i = wave.find(i => effort(a.sets[i]) === null && base[i].r < hi && base[i].r >= a.sets[i].r);
    if (i === undefined) return hold('no-reserve', 'Нет готовой позиции с неизвестным RPE и местом до верхней границы.');
    const delta = mode === 'duration' ? p.timeStep : 1;
    base[i].r = Math.min(hi, base[i].r + delta);
    result.code = 'conservative-reps'; result.changed = [i];
    result.next = input.baseline.map((row,j)=>j===i?base[i]:copy(row));
    result.reasons.push('Два выполнения без RPE: один небольшой шаг в одной неизвестной строке, вес неизменен.');
    return result;
  }
  const ready = work.filter(i => effort(a.sets[i]) !== null && effort(a.sets[i]) <= 9)
    .sort((i, j) => effort(a.sets[i]) - effort(a.sets[j]) || wave.indexOf(i) - wave.indexOf(j));
  result.queue = ready.map(i => i + 1);
  if (mode === 'duration') {
    if (partial) return hold('partial', 'Для прибавки времени нужен полный факт рабочих подходов.');
    const i = ready.find(i => effort(a.sets[i]) <= 8 && attained(a.sets[i], base[i], mode) && base[i].r < hi);
    if (i === undefined) return hold('no-candidate', 'Время повторить: готовой позиции до верхней границы нет.');
    base[i].r = Math.min(hi, base[i].r + p.timeStep); result.changed = [i]; result.code = 'time';
    result.next = input.baseline.map((row,j)=>j===i?base[i]:copy(row));
    result.reasons.push('Один настроенный шаг времени; формула Epley не применяется.'); return result;
  }
  const previousInformative = !partial && b && work.every(i => complete(b.sets[i], mode) && b.sets[i].role === 'work');
  const budgetLimit = previousInformative ? .03 : .015;
  const totalCost = candidate => work.reduce((sum, i) => sum + cost(candidate[i], a.sets[i], mode), 0) / allWork.length;
  const initialCost = totalCost(base);
  if (initialCost > budgetLimit + 1e-10) return hold('catch-up', 'Повтор базовой цели уже превышает условный бюджет; дополнительной прибавки нет.');
  let exception = null;
  for (let pass = 0; pass < 2; pass++) for (const i of ready) {
    const fact = a.sets[i], target = base[i];
    if (result.changed.includes(i) && result.formulas.some(f => f.set === i + 1)) continue;
    let candidate;
    if (target.r < hi && (!repetitionsOnly || target.r <= fact.r) && target.r + 1 - fact.r <= Math.max(0, rir(fact) - 1) && target.r + 1 >= lo) {
      candidate = {...target, r: target.r + 1};
    } else if (pass === 0 && canRaiseWeight && !repetitionsOnly && target.r >= hi && fact.r >= hi) {
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
      if (repetitionsOnly) {
        result.code = 'progress'; result.budget = totalCost(base);
        result.reasons.unshift('Добавлен один повтор в подходе ' + (i + 1) + '.');
        return result;
      }
      if (candidate.w !== fact.w) result.formulas.push({set: i + 1, capacity: capacity(fact), weight: candidate.w, reps: candidate.r});
    } else if (!result.changed.length && effort(fact) <= 8 && candidate.w !== fact.w && previousInformative && enoughBase(a) && enoughBase(b) && !exception) exception = {i, candidate};
  }
  if (!result.changed.length && exception) {
    base[exception.i] = exception.candidate; result.changed = [exception.i]; result.granularity = true;
    result.formulas.push({set: exception.i + 1, capacity: capacity(a.sets[exception.i]), weight: exception.candidate.w, reps: exception.candidate.r});
  }
  result.budget = totalCost(base);
  result.next = input.baseline.map((row,i)=>result.changed.includes(i)?base[i]:copy(row));
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
  const fact = row => ({w:!filled(row.factWeight) && ['bodyweight','duration'].includes(profile.mode) ? 0 : uiNumber(row.factWeight),
    r:uiNumber(row.factReps),rpe:uiNumber(row.rpe),role:row.role === 'warmup' ? 'warmup' : 'work'});
  const previous = sessions.slice(0, targetIndex).flatMap((session, order) => {
    if (session.source === 'model_example_at_owner_request') return [];
    const item = byExercise(session, exerciseId);
    return item ? [{session, exercise:item, order}] : [];
  });
  const prior = previous.filter(({exercise:item}) => item.sets.some(row => row.role !== 'warmup' && recorded(fact(row),profile.mode)));
  const dated = prior.filter(item => /^\d{4}-\d{2}-\d{2}$/.test(item.session.date || ''));
  const targetDate = target.date || dated.reduce((date,item)=>item.session.date > date ? item.session.date : date,'');
  const comparable = dated.filter(item=>item.session.date<=targetDate).toSorted((a,b)=>a.order-b.order);
  const latest = comparable.at(-1)?.exercise;
  const warmupSource = previous.filter(({session}) => !target.date || !session.date || session.date <= target.date)
    .findLast(({exercise:item}) => item.sets.some(row => recorded(fact(row),profile.mode)))?.exercise;
  const warmupIndices = [];
  const hasPlan = exercise.sets.some(row => row.role !== 'warmup' && (filled(row.planWeight) || filled(row.planReps)));
  let limitation;
  const limit = (code, reason) => { limitation ??= {code,reason}; };
  if (!comparable.length) limit('no-history', 'Для прибавки пока нет предыдущего результата с датой.');
  if (comparable.length && prior.some(item => item.order > comparable.at(-1).order && !dated.includes(item))) limit('undated', 'У более свежего результата нет даты. Оставляем план без прибавки.');
  if (profile.last_reduced && !hasPlan) limit('configuration', 'После облегчённого занятия нужен обычный план. Прибавку пока не предлагаем.');
  const baseline = exercise.sets.map((row, i) => {
    let w = uiNumber(row.planWeight), r = uiNumber(row.planReps);
    if (row.role === 'warmup') {
      const last = warmupSource?.sets[i] && fact(warmupSource.sets[i]);
      if (recorded(last,profile.mode)) {
        w = last.w; r = last.r; warmupIndices.push(i);
      }
    } else if (!hasPlan) {
      const last = latest?.sets[i] && fact(latest.sets[i]);
      w = last?.w ?? ''; r = last?.r ?? '';
    }
    if (!filled(w) && ['bodyweight','duration'].includes(profile.mode)) w = 0;
    return {w:Number.isFinite(w) && w >= 0 ? w : '',r:Number.isFinite(r) && r > 0 ? r : '',role:row.role === 'warmup' ? 'warmup' : 'work'};
  });
  // Dates are editable labels; the journal's record order defines preceding facts.
  const history = comparable.map(({session,exercise:item,order}) => ({id:String(order).padStart(12,'0'),date:session.date,
    sets:item.sets.map(fact)}));
  if (history.length) Object.assign(history.at(-1),{reduced:!!profile.last_reduced,changedConditions:!!profile.changed_conditions,hold:!!profile.hold});
  const p = {mode:profile.mode,range:profile.rep_range,timeRange:profile.rep_range,timeStep:profile.time_step};
  if (p.mode === 'external') {
    const step = Number(profile.load_step), weights = baseline.filter(row => row.role === 'work').map(row => row.w);
    if (step > 0 && Number.isFinite(step) && weights.length && weights.every(w => Number.isFinite(w) && w > 0)) {
      const min = Math.min(...weights);
      if (weights.every(w => Math.abs((w-min)/step-Math.round((w-min)/step)) <= 1e-7)) {
        p.loads = [...new Set(weights.flatMap(w => [w,Number((w+step).toFixed(6))]))].sort((a,b)=>a-b);
      }
    }
  }
  // A collision can only suppress an extra suggestion, never authorize one.
  const signature = records => {
    const facts = JSON.stringify(records.slice(-5).map(({session,exercise:item}) => [
    session.session_id,
    item.sets.map(row => row.role === 'warmup' ? null : [
      uiNumber(row.factWeight), uiNumber(row.factReps), uiNumber(row.rpe),
    ]),
    ]));
    let hash = 2166136261;
    for (let i=0; i<facts.length; i++) hash = Math.imul(hash ^ facts.charCodeAt(i), 16777619);
    return 'facts-v1:' + (hash >>> 0).toString(16);
  };
  const evidence = signature(comparable);
  // Keep pre-upgrade receipts valid when edited dates used to reorder the same facts.
  const legacyPrior = previous.filter(({exercise:item}) => item.sets.some(row => row.role !== 'warmup' && (filled(row.factWeight) || filled(row.factReps))));
  const legacyDated = legacyPrior.filter(item => /^\d{4}-\d{2}-\d{2}$/.test(item.session.date || ''));
  const legacyDate = target.date || legacyDated.reduce((date,item)=>item.session.date > date ? item.session.date : date,'');
  const legacyEvidence = signature(legacyDated.filter(item=>item.session.date<=legacyDate)
    .toSorted((a,b)=>a.session.date.localeCompare(b.session.date)||a.order-b.order));
  const input = {profile:p,baseline,history,historyOrder:'journal',targetDate,limitation,alreadyApplied:[evidence,legacyEvidence].includes(exercise.progressionEvidence),offerStarter:!hasPlan && !profile.last_reduced && !profile.changed_conditions && !profile.hold && !prior.length};
  return {input,evidence,warmupIndices,sourceIds:comparable.slice(-2).map(item=>({number:item.session.number,date:item.session.date})),
    fingerprint:JSON.stringify({targetId:target.session_id,targetDate:target.date,sets:exercise.sets,input,profile,evidence})};
}

export function planApplication(request, result) {
  const repeatable = request.input.history.length > 0 && !request.input.limitation
    && !['unsupported','configuration','coach','reduced','conditions','context'].includes(result.code);
  const rows = result.next.map((row,i) => {
    if (row.role === 'warmup') return request.warmupIndices.includes(i) ? row : null;
    return (result.changed.length > 0 || repeatable) && recorded(row,request.input.profile.mode) ? row : null;
  });
  return {rows, needsReview: !result.changed.length && !repeatable
    && request.input.baseline.some(row=>row.role !== 'warmup')};
}
