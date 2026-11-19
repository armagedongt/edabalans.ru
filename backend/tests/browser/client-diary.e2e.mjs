import assert from "node:assert/strict";
import {createServer} from "node:http";
import {createRequire} from "node:module";
import {readFileSync} from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const require = createRequire(import.meta.url);
const {chromium, webkit} = process.env.CODEX_NODE_MODULES
  ? require(path.join(process.env.CODEX_NODE_MODULES, "playwright")) : await import("playwright");
const staticRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../app/static");
const id = "00000000-0000-0000-0000-000000000001";
const session = {start:"08:10", type:"Swim", moving_seconds:3600, elapsed_seconds:4500,
  kcal_total:600, kcal_active:530, active_estimated:true, basal_kcal_day:1344,
  duration_basis:"elapsed", source_url:"https://www.strava.com/activities/123"};
const imported = {categories:[], days:[
  {date:"2026-11-09",weight:60,kcal:1800,protein:100,steps:1000,training_sessions:[session, {...session,start:"18:00"}]},
  {date:"2026-11-10",weight:62,steps:0},
  {date:"2026-11-11",kcal:2000,protein:120,steps:3000},
  {date:"2026-11-12",weight:64,kcal:2200,steps:4000,steps_qualifier:">"}
], energy_summaries:[{start:"2026-11-01",end:"2026-11-07",active:500,resting:1500,total:2000}]};
const user = {id,display_name:"Synthetic client",email:"test@example.test"};
const server = createServer((req,res) => {
  const url = new URL(req.url,"http://localhost");
  if (url.pathname.includes("/admin/api/")) {
    const data = url.pathname.endsWith("/diary") ? {imported,notes:[],history_available:false}
      : {user,has_state:false,state:null,users:[]};
    res.setHeader("Content-Type","application/json");return res.end(JSON.stringify(data));
  }
  if (url.pathname === "/embed.js" || url.pathname.endsWith("/admin-shell.js")) {
    res.setHeader("Content-Type","application/javascript");return res.end("");
  }
  const name = url.pathname === "/admin/client-diary" ? "admin.html" : path.basename(url.pathname);
  try {
    const file = readFileSync(path.join(staticRoot,name));
    res.setHeader("Content-Type",name.endsWith(".js")?"application/javascript":name.endsWith(".css")?"text/css":"text/html");
    res.end(file);
  } catch {res.writeHead(404).end();}
});
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
try {
  for (const [engineName, engine] of [["chromium",chromium],["webkit",webkit]]) {
    const browser = await engine.launch({headless:true});
    try {
      for (const width of [390,1365]) {
        const page = await browser.newPage({viewport:{width,height:1000},hasTouch:true});
        const errors=[];page.on("pageerror",e=>errors.push(e.message));
        await page.goto(`${origin}/admin/client-diary?user=${id}&view=apps`);
        await page.addStyleTag({content:"*{scroll-behavior:auto!important}"});
        await page.locator(".diary-daily-grid tbody tr").first().waitFor();
        await page.locator("[data-diary-categories]").click();
        await page.locator("[data-diary-calories]").click();
        const table=page.locator(".diary-daily-grid table");
        const headers=await table.locator("thead th").allTextContents();
        const rows=table.locator("tbody tr");
        const cell=(row,label)=>rows.nth(row).locator("td,th").nth(headers.indexOf(label));
        assert.match(await cell(0,"Ккал трен. актив.").innerText(),/≈.*1\s*060/);
        assert.equal(await cell(0,"Тренировок").innerText(),"2");
        await cell(0,"Тренировка").locator("summary").click();
        assert.match(await cell(0,"Тренировка").innerText(),/600.*общие.*530.*активные/);
        await cell(0,"Тренировка").locator("summary").click();
        const visiblePoint=locator=>locator.evaluate(cell=>{
          const r=cell.getBoundingClientRect(),g=cell.closest(".diary-grid").getBoundingClientRect();
          const sticky=cell.parentElement.querySelector(".diary-date").getBoundingClientRect();
          const left=Math.max(r.left,g.left,sticky.right),right=Math.min(r.right,g.right,innerWidth);
          if(right<=left)throw new Error("Cell is covered by the sticky date column");
          return {x:(left+right)/2,y:r.top+r.height/2};
        });
        const drag=async (start,end) => {
          await start.evaluate(cell => { cell.closest(".diary-grid").scrollLeft=0; cell.scrollIntoView({block:"center",inline:"nearest",behavior:"instant"}); });
          const a=await visiblePoint(start);
          await page.mouse.move(a.x,a.y);
          await page.mouse.down();
          assert.equal(await page.locator(".diary-selection-tooltip").count(),1,
            "Pressing an uncovered numeric cell starts selection");
          await end.evaluate(cell => { cell.closest(".diary-grid").scrollLeft=0; cell.scrollIntoView({block:"center",inline:"nearest",behavior:"instant"}); });
          const b=await visiblePoint(end);
          await page.mouse.move(b.x,b.y,{steps:6});
          await page.mouse.up();
        };
        await drag(cell(0,"Вес"),cell(1,"Вес"));
        const popup=page.locator(".diary-selection-tooltip");
        assert.match(await popup.innerText(),/Вес: 61 \(2 знач\.\)/);
        assert.equal(await table.locator(".diary-cell-selected").count(),2);
        await page.keyboard.press("Escape");
        assert.equal(await popup.count(),0);
        await drag(cell(3,"Шаги"),cell(0,"Ккал"));
        const result=await popup.innerText();
        assert.match(result,/Ккал: 2\s*000 \(3 знач\.\)/);
        assert.match(result,/Белки: 110 \(2 знач\.\)/);
        assert.match(result,/Шаги: 1\s*333,33 \(3 знач\.\)/);
        assert(!result.includes("Вес:"));
        const bounds=await popup.boundingBox();
        assert(bounds.x>=0 && bounds.y>=0 && bounds.x+bounds.width<=width && bounds.y+bounds.height<=1000);
        await page.locator("[data-diary-calories]").click();
        assert.equal(await popup.count(),0);
        await drag(cell(0,"Ккал"),cell(2,"Шаги"));
        assert(!(await popup.innerText()).includes("Белки:"));
        await page.locator("h2").first().click();
        assert.equal(await popup.count(),0);
        const touchBox=await cell(0,"Ккал").boundingBox();
        await page.touchscreen.tap(touchBox.x+touchBox.width/2,touchBox.y+touchBox.height/2);
        assert.equal(await popup.count(),0);
        assert.equal(await cell(0,"Ккал").evaluate(cell => cell.dispatchEvent(new PointerEvent("pointerdown",{
          pointerType:"touch",button:0,bubbles:true,cancelable:true
        }))),true,"Touch default action must remain available");
        if(engineName==="chromium" && width===390){
          const grid=page.locator(".diary-daily-grid");
          await grid.evaluate(node=>{node.scrollLeft=0;node.scrollIntoView({block:"center",behavior:"instant"});});
          const rect=await grid.boundingBox();
          const cdp=await page.context().newCDPSession(page);
          const y=rect.y+rect.height/2,x=Math.min(width-30,rect.x+rect.width-30);
          await cdp.send("Input.dispatchTouchEvent",{type:"touchStart",touchPoints:[{x,y}]});
          for(let step=1;step<=6;step++)await cdp.send("Input.dispatchTouchEvent",{type:"touchMove",touchPoints:[{x:x-step*20,y}]});
          await cdp.send("Input.dispatchTouchEvent",{type:"touchEnd",touchPoints:[]});
          await page.waitForFunction(()=>document.querySelector(".diary-daily-grid").scrollLeft>0);
          assert.equal(await popup.count(),0);
          await cdp.detach();
        }
        await page.locator(".diary-notes-form [name=day]").fill("2026-11-13");
        await page.locator(".diary-notes-form [name=body]").fill("Synthetic day note");
        await drag(cell(0,"Ккал трен. актив."),cell(1,"Ккал трен. актив."));
        assert.match(await popup.innerText(),/Ккал трен\. актив\.: ≈ 1\s*060 \(1 знач\.\)/);
        await page.locator(".diary-notes-form button").focus();
        await page.keyboard.press("Enter");
        await page.locator("[data-diary-notes]").getByText(/Synthetic day note/).waitFor();
        assert.equal(await popup.count(),0);
        assert.equal(await rows.count(),5);
        assert.deepEqual(errors,[]);
        console.log(`PASS ${engineName} ${width}px: training, selection, means, blanks, zero, bounds, clear, touch`);
        await page.close();
      }
    } finally {await browser.close();}
  }
} finally {server.close();}
