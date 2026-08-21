/* DQS BACKEND: клиент + админка */
const SPREADSHEET_ID='13Ms00YmGP_IPW3FgzagMlx6rsuNFHV-aNxDkt1IkwqE';
const ALLOWED_SHEET='Allowed_Emails';
const DATA_SHEET='DQS_Data';
const DAY_COUNT=30;
const CATEGORY_COUNT=17;


const CATEGORY_SCORES=[
[2,2,2,1,0,0,0,-1],
[2,2,2,1,0,0,0,-1],
[2,2,2,1,0,0,0,-1],
[2,2,1,0,0,-1,-2,-2],
[2,2,1,0,-1,-2,-2,-2],
[2,0,-1,-2,-2,-2,-2,-2],
[2,0,-1,-2,-2,-2,-2,-2],
[1,0,0,-1,-2,-2,-2,-2],
[2,2,1,0,-1,-1,-1,-2],
[2,2,1,0,-1,-1,-1,-2],
[2,2,1,0,-1,-1,-1,-2],
[0,-1,-2,-2,-2,-2,-2,-2],
[-2,-2,-2,-2,-2,-2,-2,-2],
[-2,-2,-2,-2,-2,-2,-2,-2],
[-2,-2,-2,-2,-2,-2,-2,-2],
[-2,-2,-2,-2,-2,-2,-2,-2],
[-2,-2,-2,-2,-2,-2,-2,-2]
];


function doGet(e){
  try{
    const p=e&&e.parameter?e.parameter:{};
    const action=String(p.action||'ping');
    let result;
    switch(action){
      case 'ping': result=handlePing(); break;
      case 'openUser': result=handleOpenUser(p); break;
      case 'setStartDate': result=handleSetStartDate(p); break;
      case 'saveDay': result=handleSaveDay(p); break;
      case 'adminLogin': result=handleAdminLogin(p); break;
      case 'adminListUsers': result=handleAdminListUsers(p); break;
      case 'adminGetUser': result=handleAdminGetUser(p); break;
      default: result={ok:false,error:'UNKNOWN_ACTION'};
    }
    return output(result,p.callback);
  }catch(error){
    return output({ok:false,error:error&&error.message?error.message:String(error)},e&&e.parameter?e.parameter.callback:'');
  }
}


function handlePing(){return {ok:true,service:'DQS',dayCount:DAY_COUNT,categoryCount:CATEGORY_COUNT,time:new Date().toISOString()};}


function handleOpenUser(p){
  const email=normalizeEmail(p.email);
  if(!email)return {ok:false,error:'Введите email'};
  if(!isAllowedEmail(email))return {ok:false,error:'Этот email не найден в списке доступа'};
  const lock=LockService.getScriptLock(); lock.waitLock(10000);
  try{
    const sheet=ensureDataSheet();
    let row=findUserRow(sheet,email);
    if(!row)row=createUserRow(sheet,email);
    const values=sheet.getRange(row,1,1,4+DAY_COUNT).getValues()[0];
    const startDate=normalizeStoredDate(values[1]);
    const days=[];
    for(let i=0;i<DAY_COUNT;i++)days.push(parseStoredDay(values[4+i]));
    return {ok:true,email,startDate:startDate||'',needsStartDate:!startDate,days};
  }finally{lock.releaseLock();}
}


function handleSetStartDate(p){
  const email=normalizeEmail(p.email), requestedDate=normalizeDateString(p.startDate);
  if(!email)return {ok:false,error:'EMAIL_REQUIRED'};
  if(!isAllowedEmail(email))return {ok:false,error:'ACCESS_DENIED'};
  if(!requestedDate)return {ok:false,error:'Некорректная дата'};
  const lock=LockService.getScriptLock(); lock.waitLock(10000);
  try{
    const sheet=ensureDataSheet();
    let row=findUserRow(sheet,email); if(!row)row=createUserRow(sheet,email);
    const current=normalizeStoredDate(sheet.getRange(row,2).getValue());
    if(current)return {ok:true,startDate:current,alreadySet:true};
    const now=new Date();
    sheet.getRange(row,2).setValue(requestedDate);
    sheet.getRange(row,4).setValue(now);
    return {ok:true,startDate:requestedDate,alreadySet:false};
  }finally{lock.releaseLock();}
}


function handleSaveDay(p){
  const email=normalizeEmail(p.email);
  if(!email)return {ok:false,error:'EMAIL_REQUIRED'};
  if(!isAllowedEmail(email))return {ok:false,error:'ACCESS_DENIED'};
  const dayNumber=parseInt(p.day,10);
  if(!Number.isInteger(dayNumber)||dayNumber<1||dayNumber>DAY_COUNT)return {ok:false,error:'INVALID_DAY'};
  let incoming;
  try{incoming=JSON.parse(String(p.data||''));}catch(e){return {ok:false,error:'INVALID_JSON'};}
  const validation=validateDayData(incoming); if(!validation.ok)return validation;
  const lock=LockService.getScriptLock(); lock.waitLock(10000);
  try{
    const sheet=ensureDataSheet();
    const row=findUserRow(sheet,email); if(!row)return {ok:false,error:'USER_NOT_FOUND'};
    const startDate=normalizeStoredDate(sheet.getRange(row,2).getValue());
    if(!startDate)return {ok:false,error:'START_DATE_REQUIRED'};
    const now=new Date();
    const data={v:2,updated:now.toISOString(),p:incoming.p.map(v=>Math.round(Number(v)*2)/2),d:incoming.d.map(v=>v===true?true:v===false?false:null)};
    sheet.getRange(row,4+dayNumber).setValue(JSON.stringify(data));
    sheet.getRange(row,4).setValue(now);
    return {ok:true,data};
  }finally{lock.releaseLock();}
}


function handleAdminLogin(p){
  const email=normalizeEmail(p.email);
  if(!email)return {ok:false,error:'EMAIL_REQUIRED'};
  if(!isAdminEmail(email))return {ok:false,error:'Нет доступа к админ-панели'};
  return {ok:true,email,admin:true};
}


function handleAdminListUsers(p){
  const adminEmail=normalizeEmail(p.email||p.adminEmail);
  if(!isAdminEmail(adminEmail))return {ok:false,error:'ACCESS_DENIED'};
  const sheet=ensureDataSheet(), lastRow=sheet.getLastRow();
  if(lastRow<2)return {ok:true,users:[],summary:{total:0,active3Days:0,inactive3Days:0,completed30:0}};
  const values=sheet.getRange(2,1,lastRow-1,4+DAY_COUNT).getValues();
  const users=[]; let active3Days=0,inactive3Days=0,completed30=0;
  for(let r=0;r<values.length;r++){
    const row=values[r], email=normalizeEmail(row[0]); if(!email)continue;
    const startDate=normalizeStoredDate(row[1]), createdAt=normalizeTimestamp(row[2]), updatedAt=normalizeTimestamp(row[3]);
    const days=[]; for(let i=0;i<DAY_COUNT;i++)days.push(parseStoredDay(row[4+i]));
    const summary=summarizeUserDays(days,startDate);
    users.push({email,startDate:startDate||'',createdAt:createdAt||'',updatedAt:updatedAt||'',filledDays:summary.filledDays,emptyDays:DAY_COUNT-summary.filledDays,lastFilledDay:summary.lastFilledDay,lastFilledDate:summary.lastFilledDate,averageDqs:summary.averageDqs,last7AverageDqs:summary.last7AverageDqs,completed:summary.completed,active3Days:summary.active3Days});
    if(summary.active3Days)active3Days++;
    if(summary.filledDays>0&&!summary.active3Days)inactive3Days++;
    if(summary.completed)completed30++;
  }
  users.sort((a,b)=>(b.updatedAt?new Date(b.updatedAt).getTime():0)-(a.updatedAt?new Date(a.updatedAt).getTime():0));
  return {ok:true,users,summary:{total:users.length,active3Days,inactive3Days,completed30}};
}


function handleAdminGetUser(p){
  const adminEmail=normalizeEmail(p.adminEmail||p.email), userEmail=normalizeEmail(p.userEmail);
  if(!isAdminEmail(adminEmail))return {ok:false,error:'ACCESS_DENIED'};
  if(!userEmail)return {ok:false,error:'USER_EMAIL_REQUIRED'};
  const sheet=ensureDataSheet(), row=findUserRow(sheet,userEmail); if(!row)return {ok:false,error:'USER_NOT_FOUND'};
  const values=sheet.getRange(row,1,1,4+DAY_COUNT).getValues()[0];
  const startDate=normalizeStoredDate(values[1]);
  const days=[]; for(let i=0;i<DAY_COUNT;i++)days.push(parseStoredDay(values[4+i]));
  const summary=summarizeUserDays(days,startDate);
  return {ok:true,user:{email:normalizeEmail(values[0]),startDate:startDate||'',createdAt:normalizeTimestamp(values[2])||'',updatedAt:normalizeTimestamp(values[3])||'',days,summary}};
}


function summarizeUserDays(days,startDate){
  const filled=[]; let lastFilledDay=0;
  for(let i=0;i<DAY_COUNT;i++)if(isFilledDay(days[i])){filled.push({dayNumber:i+1,dqs:calcDayDqs(days[i]),healthy:calcGroupScore(days[i],0,11),unhealthy:calcGroupScore(days[i],12,16)});lastFilledDay=i+1;}
  const averageDqs=average(filled.map(x=>x.dqs));
  const last7AverageDqs=average(filled.slice(-7).map(x=>x.dqs));
  const lastFilledDate=startDate&&lastFilledDay?addDaysToDateString(startDate,lastFilledDay-1):'';
  return {filledDays:filled.length,lastFilledDay,lastFilledDate,averageDqs,last7AverageDqs,completed:isFilledDay(days[DAY_COUNT-1]),active3Days:isDateWithinLastDays(lastFilledDate,3)};
}


function calcDayDqs(day){let t=0;if(!day)return 0;for(let i=0;i<CATEGORY_COUNT;i++)t+=calcCategoryScore(day,i);return round1(t);}
function calcGroupScore(day,a,b){let t=0;if(!day)return 0;for(let i=a;i<=b;i++)t+=calcCategoryScore(day,i);return round1(t);}
function calcCategoryScore(day,i){
  if(!day||!Array.isArray(day.p))return 0;
  const portions=Math.max(0,Number(day.p[i]||0)), whole=Math.floor(portions+1e-9), fraction=Math.round((portions-whole)*2)/2;
  let total=0; for(let pos=1;pos<=whole;pos++)total+=getScoreForPortion(i,pos); if(fraction>0)total+=fraction*getScoreForPortion(i,whole+1);
  if([0,1,2,3,4,8].includes(i)&&Array.isArray(day.d)&&day.d[i]===true)total+=1;
  return round1(total);
}
function getScoreForPortion(i,pos){const s=CATEGORY_SCORES[i];return pos<=s.length?s[pos-1]:s[s.length-1];}
function isFilledDay(day){if(!day)return false;if(Array.isArray(day.p)&&day.p.some(v=>Number(v||0)>0))return true;if(Array.isArray(day.d)&&day.d.some(v=>v===true))return true;return false;}


function isAllowedEmail(email){
  const normalized=normalizeEmail(email); if(!normalized)return false;
  const ss=SpreadsheetApp.openById(SPREADSHEET_ID), sheet=ss.getSheetByName(ALLOWED_SHEET); if(!sheet)throw new Error('Лист Allowed_Emails не найден');
  const lastRow=sheet.getLastRow(); if(lastRow<2)return false;
  const width=Math.min(2,Math.max(1,sheet.getLastColumn()));
  const values=sheet.getRange(2,1,lastRow-1,width).getValues();
  for(let i=0;i<values.length;i++)if(normalizeEmail(values[i][0])===normalized){const status=width>=2?String(values[i][1]||'').trim().toLowerCase():'';return !status||status==='active';}
  return false;
}
function getAdminEmail(){
  const ss=SpreadsheetApp.openById(SPREADSHEET_ID), sheet=ss.getSheetByName(ALLOWED_SHEET); if(!sheet)throw new Error('Лист Allowed_Emails не найден');
  const lastRow=sheet.getLastRow(); if(lastRow<2)return '';
  const values=sheet.getRange(2,1,lastRow-1,1).getValues();
  for(let i=0;i<values.length;i++){const email=normalizeEmail(values[i][0]);if(email)return email;}
  return '';
}
function isAdminEmail(email){const n=normalizeEmail(email);if(!n)return false;return n===getAdminEmail()&&isAllowedEmail(n);}


function ensureDataSheet(){
  const ss=SpreadsheetApp.openById(SPREADSHEET_ID); let sheet=ss.getSheetByName(DATA_SHEET); if(!sheet)sheet=ss.insertSheet(DATA_SHEET);
  const headers=['email','start_date','created_at','updated_at']; for(let i=1;i<=DAY_COUNT;i++)headers.push('day_'+String(i).padStart(2,'0'));
  if(sheet.getMaxColumns()<headers.length)sheet.insertColumnsAfter(sheet.getMaxColumns(),headers.length-sheet.getMaxColumns());
  const existing=sheet.getRange(1,1,1,headers.length).getValues()[0];
  let need=false; for(let i=0;i<headers.length;i++)if(String(existing[i]||'')!==headers[i]){need=true;break;}
  if(need)sheet.getRange(1,1,1,headers.length).setValues([headers]);
  return sheet;
}
function findUserRow(sheet,email){const n=normalizeEmail(email),lr=sheet.getLastRow();if(lr<2)return 0;const v=sheet.getRange(2,1,lr-1,1).getValues();for(let i=0;i<v.length;i++)if(normalizeEmail(v[i][0])===n)return i+2;return 0;}
function createUserRow(sheet,email){const now=new Date(),row=[normalizeEmail(email),'',now,now];for(let i=0;i<DAY_COUNT;i++)row.push('');sheet.appendRow(row);return sheet.getLastRow();}


function validateDayData(data){
  if(!data||typeof data!=='object')return {ok:false,error:'INVALID_DATA'};
  if(!Array.isArray(data.p)||data.p.length!==CATEGORY_COUNT)return {ok:false,error:'INVALID_PORTIONS'};
  if(!Array.isArray(data.d)||data.d.length!==CATEGORY_COUNT)return {ok:false,error:'INVALID_DIVERSITY'};
  for(let i=0;i<CATEGORY_COUNT;i++){
    const v=Number(data.p[i]); if(!Number.isFinite(v)||v<0)return {ok:false,error:'INVALID_PORTION_VALUE'};
    if(Math.abs(v*2-Math.round(v*2))>.000001)return {ok:false,error:'PORTION_MUST_BE_HALF_STEP'};
    const d=data.d[i]; if(d!==true&&d!==false&&d!==null)return {ok:false,error:'INVALID_DIVERSITY_VALUE'};
  }
  return {ok:true};
}
function parseStoredDay(value){
  if(value===''||value===null||typeof value==='undefined')return null;
  let data; try{data=typeof value==='string'?JSON.parse(value):value;}catch(e){return null;}
  const val=validateDayData(data); if(!val.ok)return null;
  return {v:data.v||2,updated:data.updated||'',p:data.p.map(v=>Math.round(Number(v)*2)/2),d:data.d.map(v=>v===true?true:v===false?false:null)};
}


function normalizeDateString(value){
  const text=String(value||'').trim(); if(!/^\d{4}-\d{2}-\d{2}$/.test(text))return '';
  const p=text.split('-').map(Number),d=new Date(p[0],p[1]-1,p[2]);
  if(d.getFullYear()!==p[0]||d.getMonth()!==p[1]-1||d.getDate()!==p[2])return '';
  return text;
}
function normalizeStoredDate(value){
  if(!value)return '';
  if(Object.prototype.toString.call(value)==='[object Date]'&&!isNaN(value.getTime()))return Utilities.formatDate(value,Session.getScriptTimeZone(),'yyyy-MM-dd');
  return normalizeDateString(String(value).trim());
}
function addDaysToDateString(dateString,days){const valid=normalizeDateString(dateString);if(!valid)return '';const p=valid.split('-').map(Number),d=new Date(p[0],p[1]-1,p[2]);d.setDate(d.getDate()+Number(days||0));return Utilities.formatDate(d,Session.getScriptTimeZone(),'yyyy-MM-dd');}
function isDateWithinLastDays(dateString,count){const valid=normalizeDateString(dateString);if(!valid)return false;const p=valid.split('-').map(Number),target=Date.UTC(p[0],p[1]-1,p[2]),now=new Date(),today=Date.UTC(now.getFullYear(),now.getMonth(),now.getDate()),diff=Math.floor((today-target)/86400000);return diff>=0&&diff<Number(count||0);}
function normalizeEmail(value){return String(value||'').trim().toLowerCase();}
function normalizeTimestamp(value){if(!value)return '';if(Object.prototype.toString.call(value)==='[object Date]'&&!isNaN(value.getTime()))return value.toISOString();const d=new Date(value);return isNaN(d.getTime())?'':d.toISOString();}
function average(values){if(!values||!values.length)return null;return round1(values.reduce((s,v)=>s+Number(v||0),0)/values.length);}
function round1(value){return Math.round((Number(value||0)+Number.EPSILON)*10)/10;}
function output(data,callback){const json=JSON.stringify(data),cb=String(callback||'').trim();if(cb&&/^[A-Za-z_$][0-9A-Za-z_$]*$/.test(cb))return ContentService.createTextOutput(cb+'('+json+');').setMimeType(ContentService.MimeType.JAVASCRIPT);return ContentService.createTextOutput(json).setMimeType(ContentService.MimeType.JSON);}
