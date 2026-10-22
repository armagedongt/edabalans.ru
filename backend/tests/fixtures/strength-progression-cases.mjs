const clone = x => structuredClone(x);
function example(id, name, weight, reps, range, loads, mode = 'external') {
  const baseline = [
    {w: weight * .4, r: 10, role: 'warmup'},
    ...Array.from({length: 3}, () => ({w: weight, r: reps, role: 'work'})),
  ];
  if (mode !== 'external') baseline.shift();
  const sets = baseline.map(row => ({...row, rpe: row.role === 'warmup' ? 6 : 8}));
  return {id, title: name, targetDate: '2026-10-22', profile: {mode, range, loads}, baseline,
    history: [{id: id + '-a', date: '2026-10-14', sets: clone(sets)}, {id: id + '-b', date: '2026-10-21', sets: clone(sets)}]};
}
export function createCases() {
  const cases = [
    example('bench', 'Жим штанги лёжа — рост повторов', 60, 10, [8, 15], [20, 40, 60, 62.5, 65, 70]),
    example('squat', 'Приседания со штангой — одна ступень +5 кг', 100, 15, [6, 15], [20, 40, 60, 80, 100, 105, 110]),
    example('leg-press', 'Жим ногами — несколько микроприбавок', 200, 15, [8, 15], [100, 150, 200, 202.5, 205, 210]),
    example('rdl', 'Румынская тяга — крупная ступень +10 кг', 80, 15, [8, 15], [20, 40, 60, 80, 90, 100]),
    example('lateral', 'Разведение гантелей в стороны — крупный относительный шаг', 10, 20, [12, 20], [4, 6, 8, 10, 12, 14]),
    example('calf', 'Подъёмы на носки — верх диапазона', 70, 20, [12, 20], [30, 40, 50, 60, 70, 80]),
    example('triceps', 'Разгибание рук на блоке — все рабочие RPE9–10', 25, 12, [10, 18], [10, 15, 20, 25, 30]),
    example('biceps', 'Сгибание рук — готовность важнее очереди', 10, 12, [10, 18], [6, 8, 10, 12, 14]),
    example('bridge', 'Ягодичный мост — без RPE, два выполнения', 100, 10, [8, 15], [60, 80, 100, 105, 110]),
    example('leg-curl', 'Сгибание ног — одна запись без RPE', 30, 12, [10, 18], [20, 25, 30, 35]),
    example('leg-extension', 'Разгибание ног — неполный факт', 40, 12, [10, 18], [20, 30, 40, 45, 50]),
    example('abduction', 'Разведение ног — намеренно облегчённый день', 40, 15, [12, 20], [20, 30, 40, 45, 50]),
    example('adduction', 'Сведение ног — разовый сильный спад', 40, 15, [12, 20], [20, 30, 40, 45, 50]),
    example('row', 'Горизонтальная тяга — повторяющийся спад', 60, 15, [8, 15], [20, 40, 60, 65, 70]),
    example('pulldown', 'Тяга верхнего блока — смена оборудования', 60, 12, [8, 15], [20, 40, 60, 65, 70]),
    example('pullup', 'Подтягивания — собственный вес', 0, 8, [6, 15], [], 'bodyweight'),
    example('gravitron', 'Подтягивания в гравитроне — помощь неизменна', 30, 10, [6, 15], [], 'assisted'),
    example('plank', 'Планка — отдельная ветвь времени', 0, 30, [20, 60], [], 'duration'),
    example('incline', 'Жим гантелей на наклонной — слишком большой следующий вес', 8, 15, [12, 15], [4, 6, 8, 12, 16]),
    example('shoulder', 'Жим от плеч в тренажёре — усилие уменьшилось, цифры прежние', 40, 10, [8, 15], [20, 30, 40, 45, 50]),
  ];
  const by = id => cases.find(c => c.id === id), last = c => c.history.at(-1);
  last(by('triceps')).sets.slice(1).forEach((row, i) => row.rpe = i === 1 ? 10 : 9);
  last(by('biceps')).sets[1].rpe = 8; last(by('biceps')).sets[2].rpe = 10; last(by('biceps')).sets[3].rpe = 9;
  by('bridge').history.forEach(h => h.sets.forEach(row => row.rpe = null));
  by('leg-curl').history = by('leg-curl').history.slice(-1); last(by('leg-curl')).sets.forEach(row => row.rpe = null);
  last(by('leg-extension')).sets[2].r = null;
  last(by('abduction')).reduced = true; last(by('abduction')).sets = last(by('abduction')).sets.slice(0, 2);
  for (const id of ['adduction', 'row']) {
    const c = by(id), old = clone(c.history[0]); old.id += '-older'; old.date = '2026-10-07'; c.history.unshift(old);
    last(c).sets.slice(1).forEach(row => row.r = 8);
    if (id === 'row') { const bad = clone(last(c)); bad.id += '-previous'; bad.date = '2026-10-18'; c.history.splice(-1, 0, bad); }
  }
  last(by('pulldown')).changedConditions = true;
  by('plank').profile.timeRange = [20, 60]; by('plank').profile.timeStep = 5;
  by('shoulder').history[0].sets.slice(1).forEach(row => row.rpe = 10);
  last(by('shoulder')).sets.slice(1).forEach(row => row.rpe = 9);
  return cases;
}
