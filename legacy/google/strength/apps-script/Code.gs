// Силовые тренировки — Apps Script
// База: https://docs.google.com/spreadsheets/d/1lcuFzG8T4aHhctCE5PXPjc3IjVnXhzUptrX_silrVIE/edit


const SPREADSHEET_ID = '1lcuFzG8T4aHhctCE5PXPjc3IjVnXhzUptrX_silrVIE';
const ADMIN_EMAIL = 'admin@example.invalid';


const SHEETS = {
  USERS: 'Users',
  TYPES: 'Workout_Types',
  CATALOG: 'Exercise_Catalog',
  SESSIONS: 'Sessions',
  SESSION_EXERCISES: 'Session_Exercises',
  SETS: 'Sets',
  META: 'Meta'
};


function doGet(e) {
  try {
    const p = (e && e.parameter) || {};
    const action = String(p.action || 'ping');


    if (action === 'ping') {
      return json_({ ok: true, service: 'strength-training', time: new Date().toISOString() });
    }


    if (action === 'openUser') {
      const user = resolveUser_(p.email, p.user_id, p.admin_email);
      return json_({ ok: true, user: user });
    }


    if (action === 'getWorkout') {
      const user = resolveUser_(p.email, p.user_id, p.admin_email);
      const type = Number(p.type || 1);
      return json_({ ok: true, user: user, workout: getWorkout_(user.user_id, type) });
    }


    if (action === 'getStats') {
      const user = resolveUser_(p.email, p.user_id, p.admin_email);
      const type = Number(p.type || 1);
      const exerciseId = String(p.exercise_id || '');
      return json_({ ok: true, user: user, stats: get8RmHistory_(user.user_id, type, exerciseId) });
    }


    if (action === 'adminListUsers') {
      requireAdmin_(p.admin_email);
      return json_({ ok: true, users: getRows_(SHEETS.USERS) });
    }


    throw new Error('Unknown action: ' + action);


  } catch (err) {
    return json_({ ok: false, error: String(err && err.message ? err.message : err) });
  }
}


function doPost(e) {
  try {
    const body = parseBody_(e);
    const action = String(body.action || '');


    if (action === 'saveSession') {
      const actor = resolveUser_(body.email, body.user_id, body.admin_email);
      const targetUserId = body.target_user_id || actor.user_id;
      if (targetUserId !== actor.user_id) requireAdmin_(body.admin_email || body.email);
      const saved = saveSession_(targetUserId, Number(body.workout_type), body.session);
      return json_({ ok: true, session: saved });
    }


    if (action === 'saveExerciseSettings') {
      const actor = resolveUser_(body.email, body.user_id, body.admin_email);
      const targetUserId = body.target_user_id || actor.user_id;
      if (targetUserId !== actor.user_id) requireAdmin_(body.admin_email || body.email);
      saveExerciseSettings_(targetUserId, Number(body.workout_type), body.exercises || []);
      return json_({ ok: true });
    }


    if (action === 'addExercise') {
      requireAdmin_(body.admin_email || body.email);
      const created = addExercise_(String(body.target_user_id || body.user_id || ''), Number(body.workout_type), String(body.exercise_name || ''));
      return json_({ ok: true, exercise: created });
    }


    throw new Error('Unknown action: ' + action);


  } catch (err) {
    return json_({ ok: false, error: String(err && err.message ? err.message : err) });
  }
}


function resolveUser_(email, userId, adminEmail) {
  const users = getRows_(SHEETS.USERS);


  if (userId) {
    const foundById = users.find(function (u) { return String(u.user_id) === String(userId); });
    if (!foundById) throw new Error('User not found');
    if (String(foundById.status || '').toLowerCase() !== 'active' && String(adminEmail || '').toLowerCase() !== ADMIN_EMAIL.toLowerCase()) throw new Error('Access denied');
    return foundById;
  }


  const normalized = String(email || '').trim().toLowerCase();
  if (!normalized) throw new Error('Email is required');


  const user = users.find(function (u) { return String(u.email || '').trim().toLowerCase() === normalized; });
  if (!user) throw new Error('Access denied');
  if (String(user.status || '').toLowerCase() !== 'active') throw new Error('Access denied');
  return user;
}


function requireAdmin_(email) {
  if (String(email || '').trim().toLowerCase() !== ADMIN_EMAIL.toLowerCase()) throw new Error('Admin access required');
}


function getWorkout_(userId, type) {
  const types = getRows_(SHEETS.TYPES).filter(function (r) { return String(r.user_id) === String(userId); }).sort(function (a, b) { return Number(a.sort_order || 0) - Number(b.sort_order || 0); });
  const catalog = getRows_(SHEETS.CATALOG).filter(function (r) { return String(r.user_id) === String(userId) && Number(r.workout_type) === Number(type); }).sort(function (a, b) { return Number(a.sort_order || 0) - Number(b.sort_order || 0); });
  const sessions = getRows_(SHEETS.SESSIONS).filter(function (r) { return String(r.user_id) === String(userId) && Number(r.workout_type) === Number(type); }).sort(function (a, b) { return Number(a.session_number || 0) - Number(b.session_number || 0); });


  const sessionIds = {};
  sessions.forEach(function (s) { sessionIds[String(s.session_id)] = true; });


  const sessionExercises = getRows_(SHEETS.SESSION_EXERCISES).filter(function (r) { return !!sessionIds[String(r.session_id)]; });
  const sets = getRows_(SHEETS.SETS).filter(function (r) { return !!sessionIds[String(r.session_id)]; });


  return { workout_types: types, exercise_catalog: catalog, sessions: sessions, session_exercises: sessionExercises, sets: sets };
}


function saveSession_(userId, workoutType, session) {
  if (!userId) throw new Error('user_id is required');
  if (!workoutType) throw new Error('workout_type is required');
  if (!session) throw new Error('session is required');


  const sessions = getRows_(SHEETS.SESSIONS);
  let sessionNumber = Number(session.session_number || 0);


  if (!sessionNumber) {
    const own = sessions.filter(function (r) { return String(r.user_id) === String(userId) && Number(r.workout_type) === Number(workoutType); });
    sessionNumber = own.reduce(function (max, r) { return Math.max(max, Number(r.session_number || 0)); }, 0) + 1;
  }


  const sessionId = String(session.session_id || '') || (String(userId) + '_t' + String(workoutType) + '_s' + pad2_(sessionNumber));
  const now = new Date().toISOString();


  const sessionRow = {
    session_id: sessionId,
    user_id: userId,
    workout_type: workoutType,
    session_number: sessionNumber,
    date: session.date || '',
    status: isSessionFilledPayload_(session) ? 'filled' : 'planned',
    legacy_group: '',
    source: 'app',
    created_at: session.created_at || now,
    updated_at: now
  };


  upsertByKey_(SHEETS.SESSIONS, 'session_id', sessionId, sessionRow);
  deleteRowsByValue_(SHEETS.SESSION_EXERCISES, 'session_id', sessionId);
  deleteRowsByValue_(SHEETS.SETS, 'session_id', sessionId);


  const exercises = session.exercises || [];


  exercises.forEach(function (ex, exIndex) {
    appendObject_(SHEETS.SESSION_EXERCISES, {
      session_id: sessionId,
      user_id: userId,
      workout_type: workoutType,
      session_number: sessionNumber,
      exercise_id: ex.exercise_id,
      exercise_name: ex.exercise_name || '',
      sort_order: Number(ex.sort_order || exIndex + 1),
      note: ex.note || '',
      source: 'app'
    });


    (ex.sets || []).forEach(function (set, setIndex) {
      appendObject_(SHEETS.SETS, {
        session_id: sessionId,
        user_id: userId,
        workout_type: workoutType,
        session_number: sessionNumber,
        exercise_id: ex.exercise_id,
        exercise_name: ex.exercise_name || '',
        set_number: Number(set.set_number || setIndex + 1),
        plan_weight: cleanNumber_(set.plan_weight),
        plan_reps: cleanNumber_(set.plan_reps),
        fact_weight: cleanNumber_(set.fact_weight),
        fact_reps: cleanNumber_(set.fact_reps),
        rpe: cleanNumber_(set.rpe),
        plan_weight_raw: '', plan_reps_raw: '', fact_weight_raw: '', fact_reps_raw: '', rpe_raw: '', source: 'app'
      });
    });
  });


  return sessionRow;
}


function isSessionFilledPayload_(session) {
  const exercises = session.exercises || [];
  for (let i = 0; i < exercises.length; i++) {
    const sets = exercises[i].sets || [];
    for (let j = 0; j < sets.length; j++) {
      if (sets[j].rpe !== '' && sets[j].rpe !== null && typeof sets[j].rpe !== 'undefined') return true;
    }
  }
  return false;
}


function saveExerciseSettings_(userId, workoutType, exercises) {
  const catalog = getRows_(SHEETS.CATALOG);


  exercises.forEach(function (item, index) {
    const found = catalog.find(function (r) {
      return String(r.user_id) === String(userId) && Number(r.workout_type) === Number(workoutType) && String(r.exercise_id) === String(item.exercise_id);
    });


    if (!found) return;
    found.active = item.active === false ? false : true;
    found.sort_order = Number(item.sort_order || index + 1);
    upsertCompositeCatalog_(found);
  });
}


function addExercise_(userId, workoutType, exerciseName) {
  if (!userId) throw new Error('target_user_id is required');
  exerciseName = String(exerciseName || '').trim();
  if (!exerciseName) throw new Error('exercise_name is required');


  const catalog = getRows_(SHEETS.CATALOG).filter(function (r) { return String(r.user_id) === String(userId) && Number(r.workout_type) === Number(workoutType); });
  const maxOrder = catalog.reduce(function (m, r) { return Math.max(m, Number(r.sort_order || 0)); }, 0);
  const exerciseId = 'custom_' + Utilities.getUuid().replace(/-/g, '').slice(0, 12);


  const row = { user_id: userId, workout_type: workoutType, exercise_id: exerciseId, exercise_name: exerciseName, active: true, sort_order: maxOrder + 1, source: 'app' };
  appendObject_(SHEETS.CATALOG, row);
  return row;
}


function upsertCompositeCatalog_(obj) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEETS.CATALOG);
  const values = sheet.getDataRange().getValues();
  const headers = values[0];
  const ixUser = headers.indexOf('user_id');
  const ixType = headers.indexOf('workout_type');
  const ixExercise = headers.indexOf('exercise_id');


  for (let r = 1; r < values.length; r++) {
    if (String(values[r][ixUser]) === String(obj.user_id) && Number(values[r][ixType]) === Number(obj.workout_type) && String(values[r][ixExercise]) === String(obj.exercise_id)) {
      const row = headers.map(function (h) { return typeof obj[h] === 'undefined' ? values[r][headers.indexOf(h)] : obj[h]; });
      sheet.getRange(r + 1, 1, 1, headers.length).setValues([row]);
      return;
    }
  }
}


function calculate8Rm_(weight, reps, rpe) {
  weight = Number(weight); reps = Number(reps); rpe = Number(rpe);
  if (!isFinite(weight) || !isFinite(reps) || !isFinite(rpe) || weight <= 0 || reps <= 0 || rpe < 1 || rpe > 10) return null;
  const rir = Math.max(0, 10 - rpe);
  const effectiveReps = reps + rir;
  const estimated1Rm = weight * (1 + effectiveReps / 30);
  return estimated1Rm / (1 + 8 / 30);
}


function get8RmHistory_(userId, workoutType, exerciseId) {
  if (!exerciseId) throw new Error('exercise_id is required');


  const sessions = getRows_(SHEETS.SESSIONS).filter(function (r) {
    return String(r.user_id) === String(userId) && Number(r.workout_type) === Number(workoutType) && String(r.date || '') !== '';
  }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });


  const allSets = getRows_(SHEETS.SETS);
  const result = [];


  sessions.forEach(function (session) {
    const sets = allSets.filter(function (r) { return String(r.session_id) === String(session.session_id) && String(r.exercise_id) === String(exerciseId); }).sort(function (a, b) { return Number(a.set_number || 0) - Number(b.set_number || 0); });
    const working = sets.slice(1);


    const candidates = working.map(function (set) {
      const estimate = calculate8Rm_(set.fact_weight, set.fact_reps, set.rpe);
      if (estimate === null) return null;
      return { set_number:Number(set.set_number), weight:Number(set.fact_weight), reps:Number(set.fact_reps), rpe:Number(set.rpe), estimated_8rm:estimate };
    }).filter(Boolean);


    if (!candidates.length) return;


    const maxWeight = candidates.reduce(function (m, c) { return Math.max(m, c.weight); }, 0);
    const sameWeight = candidates.filter(function (c) { return c.weight === maxWeight; });
    sameWeight.sort(function (a, b) { return b.estimated_8rm - a.estimated_8rm; });
    const best = sameWeight[0];


    result.push({ session_id:session.session_id, session_number:Number(session.session_number), date:session.date, estimated_8rm:round2_(best.estimated_8rm), source_set:best.set_number, source_weight:best.weight, source_reps:best.reps, source_rpe:best.rpe });
  });


  return result;
}


function getRows_(sheetName) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(sheetName);
  if (!sheet) throw new Error('Sheet not found: ' + sheetName);
  const values = sheet.getDataRange().getValues();
  if (!values.length) return [];
  const headers = values[0].map(function (h) { return String(h); });


  return values.slice(1).filter(function (row) { return row.some(function (cell) { return cell !== ''; }); }).map(function (row) {
    const obj = {};
    headers.forEach(function (header, index) { obj[header] = normalizeCell_(row[index]); });
    return obj;
  });
}


function appendObject_(sheetName, obj) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(sheetName);
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const row = headers.map(function (header) { return typeof obj[header] === 'undefined' ? '' : obj[header]; });
  sheet.appendRow(row);
}


function upsertByKey_(sheetName, keyName, keyValue, obj) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(sheetName);
  const values = sheet.getDataRange().getValues();
  const headers = values[0];
  const keyIndex = headers.indexOf(keyName);
  if (keyIndex < 0) throw new Error('Key column not found: ' + keyName);


  for (let r = 1; r < values.length; r++) {
    if (String(values[r][keyIndex]) === String(keyValue)) {
      const row = headers.map(function (header, i) { return typeof obj[header] === 'undefined' ? values[r][i] : obj[header]; });
      sheet.getRange(r + 1, 1, 1, headers.length).setValues([row]);
      return;
    }
  }


  appendObject_(sheetName, obj);
}


function deleteRowsByValue_(sheetName, keyName, keyValue) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(sheetName);
  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) return;
  const headers = values[0];
  const keyIndex = headers.indexOf(keyName);
  if (keyIndex < 0) throw new Error('Key column not found: ' + keyName);


  const kept = [headers];
  for (let r = 1; r < values.length; r++) {
    if (String(values[r][keyIndex]) !== String(keyValue)) kept.push(values[r]);
  }


  sheet.clearContents();
  sheet.getRange(1, 1, kept.length, headers.length).setValues(kept);
}


function normalizeCell_(value) {
  if (value instanceof Date) return Utilities.formatDate(value, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  return value;
}


function cleanNumber_(value) {
  if (value === '' || value === null || typeof value === 'undefined') return '';
  const n = Number(value);
  return isFinite(n) ? n : '';
}


function round2_(value) { return Math.round(Number(value) * 100) / 100; }
function pad2_(n) { return Number(n) < 10 ? '0' + Number(n) : String(Number(n)); }


function parseBody_(e) {
  if (!e || !e.postData || !e.postData.contents) throw new Error('JSON body is required');
  return JSON.parse(e.postData.contents);
}


function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
