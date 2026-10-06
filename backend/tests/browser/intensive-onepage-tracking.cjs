const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const tracker = fs.readFileSync(path.resolve(__dirname, "../../app/static/intensive/onepage-tracking.js"), "utf8");
const prefix = "intensive_onepage_";
const fixture = '<style>body{margin:0}header{position:fixed;top:0;height:60px;background:white;width:100%}main{width:600px;margin:120px auto}p{height:240px;margin:0}span[id]{scroll-margin-top:80px}footer{height:500px}</style>' +
  '<header class="reading-header"><a href="#block-3">Third section</a></header><button class="toc-trigger">Contents</button><dialog id="contents">Menu</dialog>' +
  '<main data-intensive-onepage data-intensive-revision="test-revision">' +
  Array.from({length:20},(_,i) => (i%5 === 0 ? '<span id="'+["block-1","block-2","block-3","actions"][i/5]+'" data-intensive-section="'+["block-1","block-2","block-3","actions"][i/5]+'"></span>' : "") +
    (i%5 === 0 ? '<h3 id="section-'+(i/5+1)+'">Topic '+(i/5+1)+'</h3>' : '') + '<p>'+("Text "+i+" ").repeat(100)+'</p>').join("") +
  '<span id="end" data-intensive-end></span><a data-intensive-channel="telegram" href="#channel">Telegram</a><a data-intensive-channel="max" href="#channel">MAX</a></main><footer></footer>';

(async()=>{
  const browser=await chromium.launch();
  let passed=0;
  async function setup(host="127.0.0.1", preloaded=false, brokenImage=false, options={}) {
    const context=await browser.newContext({viewport:{width:900,height:600}});
    const page=await context.newPage();
    const requests=[];
    const posts=[];
    await page.route("**/*", route=>{
      requests.push(route.request().url());
      if(route.request().method()==="POST") posts.push({url:route.request().url(),body:route.request().postDataJSON()});
      if(route.request().resourceType()==="document") return route.fulfill({contentType:"text/html",body:(options.calibrated ? '<style>body{margin:0}header{position:fixed;top:0;height:60px}main{margin:100px 0 0}p{height:500px;margin:0}</style><header class="reading-header">Header</header><main data-intensive-onepage data-intensive-revision="test-revision">' + '<p>'.concat("x".repeat(100),"</p>").repeat(10) + '<span data-intensive-end></span></main>' : fixture).replace("margin:120px auto", options.longLead ? "margin:1200px auto" : "margin:120px auto").replace('data-intensive-revision="test-revision"','data-intensive-revision="test-revision" data-intensive-identified="'+Boolean(options.identified)+'"') + (options.defer ? '<script defer src="/tracking.js"></script>' : "")});
      if(route.request().url().endsWith("/tracking.js")) return route.fulfill({contentType:"application/javascript",body:'window.__trackerReadyState=document.readyState;'+tracker});
      return route.fulfill({contentType:"application/javascript",body:""});
    });
    await page.goto((options.secure || host !== "127.0.0.1" ? "https://" : "http://")+host+"/article?utm_source=yandex&utm_campaign=test&yclid=123" + (options.personal ? "&"+options.personal+"=PRIVATE" : "") + (options.hash ? "#"+options.hash : ""),
      options.referrer ? {referer:options.referrer} : {});
    if(options.defer) await page.waitForFunction(()=>window.__intensiveOnepagePreviewEvents?.some(e=>e.event_type==="intensive_onepage_loaded"));
    await page.clock.install();
    await page.bringToFront();
    if(preloaded) await page.evaluate(()=>{
      window.ym=function(){(window.ym.a=window.ym.a||[]).push(Array.from(arguments));};
      window.ym(97331502,"init",{});
    });
    if(brokenImage) await page.evaluate(()=>new Promise(resolve=>{
      const img=document.createElement("img");img.onerror=resolve;img.src="/broken.png";
      document.querySelector("main").appendChild(img);
    }));
    if(!options.defer) await page.addScriptTag({content:tracker});
    await page.clock.runFor(100);
    return {page,context,requests,posts};
  }
  async function events(page) {
    return page.evaluate(()=>window.__intensiveOnepagePreviewEvents || (window.ym.a || [])
      .filter(call=>call[1]==="reachGoal").map(call=>({event_type:call[2],...call[3]})));
  }
  async function flush(page) { await page.clock.runFor(1100); }
  try {
    {
      const {page,context,requests}=await setup();
      let list=await events(page);
      assert(list.some(e=>e.event_type===prefix+"open"));
      assert(list.some(e=>e.event_type===prefix+"ready"));
      assert(list.some(e=>e.event_type===prefix+"loaded"));
      await page.locator(".reading-header a").click();await flush(page);
      list=await events(page);
      assert(list.some(e=>e.event_type===prefix+"navigation" && e.target==="block-3"));
      assert.equal(list.filter(e=>e.section==="block-3").length,1,"Visible anchor section is credited");
      assert(!list.some(e=>e.section==="block-2"),"Hash skip must not credit skipped section");
      assert(list.some(e=>e.event_type===prefix+"heading" && e.heading_id==="section-3" && e.heading_title==="Topic 3"));
      assert(!list.some(e=>e.heading_id==="section-2"),"Hash skip must not credit skipped headings");
      assert(!list.some(e=>e.event_type===prefix+"reading_start"),"Opening and jumping alone do not count as reading start");
      assert(!list.some(e=>e.event_type===prefix+"view_50"),"Deep navigation is not 50% viewing");
      await page.evaluate(()=>document.querySelector("#end").scrollIntoView());await flush(page);
      list=await events(page);
      assert(list.some(e=>e.event_type===prefix+"end"));
      assert(!list.some(e=>e.event_type===prefix+"view_90"),"End reached is not full reading");
      await page.locator('[data-intensive-channel="telegram"]').click();await flush(page);
      assert((await events(page)).some(e=>e.event_type===prefix+"telegram_click"));
      assert.equal(requests.length,1,"Local preview must send no analytics or API traffic");
      await context.close();passed++;
    }
    {
      // A new document loaded at a deep anchor does not credit preceding headings.
      const {page,context}=await setup("127.0.0.1",false,false,{hash:"block-3"});
      await flush(page);
      assert(!(await events(page)).some(e=>e.section==="block-1" || e.section==="block-2"));
      await context.close();passed++;
    }
    {
      const {page,context}=await setup();
      const height=await page.evaluate(()=>document.documentElement.scrollHeight);
      for(let y=0;y<height;y+=300) {await page.evaluate(y=>scrollTo(0,y),y);await flush(page);}
      await page.evaluate(()=>scrollTo(0,0));await flush(page);
      for(const percent of [10,25,50,75,90]) {
        assert.equal((await events(page)).filter(e=>e.event_type===prefix+"view_"+percent).length,1,"Each viewing milestone once");
      }
      for(const section of ["block-1","block-2","block-3","actions"]) {
        assert.equal((await events(page)).filter(e=>e.section===section).length,1,"Visible section once: "+section);
      }
      for(const id of ["section-1","section-2","section-3","section-4"]) assert.equal((await events(page)).filter(e=>e.event_type===prefix+"heading" && e.heading_id===id).length,1,"Each visible heading once");
      await page.addScriptTag({content:tracker});await flush(page);
      assert.equal((await events(page)).filter(e=>e.event_type===prefix+"open").length,1,"Duplicate tracker must not initialize twice");
      await page.evaluate(()=>window.dispatchEvent(new Event("pagehide")));
      const last = (await events(page)).filter(e=>e.event_type===prefix+"session").at(-1);
      assert.equal(last.heading_id,"section-1","Snapshot follows current place after returning to top");
      assert.equal(last.furthest_heading_id,"section-4","Returning to top does not erase farthest heading");
      await context.close();passed++;
    }
    {
      const {page,context}=await setup();
      await page.evaluate(()=>document.querySelector("#contents").showModal());
      await page.evaluate(()=>document.querySelector("#block-3").scrollIntoView());
      await page.clock.runFor(30000);
      let list = await events(page);
      assert(!list.some(e=>e.event_type===prefix+"reading_start"),"Time in content menu is not article reading");
      assert(!list.some(e=>e.heading_id==="section-3"),"Covered headings are not viewed");
      await page.evaluate(()=>document.querySelector("#contents").close());
      await page.clock.runFor(11000);
      list = await events(page);
      assert(list.some(e=>e.event_type===prefix+"reading_start"),"Reading resumes after closing contents");
      await context.close();passed++;
    }
    {
      const {page,context}=await setup("127.0.0.1",false,false,{longLead:true});
      await page.evaluate(()=>scrollTo(0, document.querySelector("main").offsetTop - innerHeight + 1));
      await page.clock.runFor(11000);
      assert(!(await events(page)).some(e=>e.event_type===prefix+"reading_start"),"Active time without 1% text is not reading start");
      await context.close();passed++;
    }
    {
      // Exactly one of ten equal text blocks is fully visible; this must be 10%, not decorative acceleration.
      const {page,context}=await setup("127.0.0.1",false,false,{calibrated:true});
      await page.evaluate(()=>window.dispatchEvent(new Event("pagehide")));
      const snapshot = (await events(page)).filter(e=>e.event_type===prefix+"session").at(-1);
      assert.equal(snapshot.viewed_percent,10,"Actual text coverage is not accelerated");
      assert.equal(snapshot.max_depth_percent,0,"Coverage is separate from scroll depth");
      await context.close();passed++;
    }
    {
      const {page,context}=await setup();
      await page.clock.runFor(30000);
      await page.evaluate(()=>window.dispatchEvent(new Event("blur")));
      await page.clock.runFor(120000);
      await page.evaluate(()=>window.dispatchEvent(new Event("pagehide")));
      let summaries=(await events(page)).filter(e=>e.event_type===prefix+"session");
      assert.equal(summaries.at(-1).active_seconds,30,"Background time excluded");
      await page.evaluate(()=>{window.dispatchEvent(new Event("pageshow"));window.dispatchEvent(new Event("focus"));});
      await page.clock.runFor(120000);
      await page.evaluate(()=>window.dispatchEvent(new Event("pagehide")));
      summaries=(await events(page)).filter(e=>e.event_type===prefix+"session");
      assert.equal(summaries.at(-1).active_seconds,90,"After one idle minute the timer stops");
      assert.equal((await events(page)).filter(e=>e.event_type===prefix+"active_60").length,1);
      const n=summaries.length;
      await page.evaluate(()=>window.dispatchEvent(new Event("pagehide")));
      assert.equal((await events(page)).filter(e=>e.event_type===prefix+"session").length,n,"Duplicate checkpoint suppressed");
      await context.close();passed++;
    }
    {
      const {page,context,requests}=await setup("intensive-analytics.test",false,false,{referrer:"http://intensive-analytics.test/source?utm_source=yandex&unrelated=EXCLUDE"});
      await page.locator('[data-intensive-channel="max"]').click();await flush(page);
      const calls=await page.evaluate(()=>Array.from(window.ym.a,call=>Array.from(call)));
      assert.equal(calls.filter(call=>call[1]==="init").length,1);
      assert(calls.find(call=>call[1]==="init")[2].defer);
      assert.equal(calls.filter(call=>call[1]==="hit").length,1);
      const hit=calls.find(call=>call[1]==="hit");
      assert.equal(hit[3].referer,"http://intensive-analytics.test/source?utm_source=yandex","Explicit hit filters referrer query");
      assert(!JSON.stringify(calls).includes("EXCLUDE"),"Unrelated referrer query excluded from explicit calls");
      assert((await events(page)).every(e=>e.utm_source==="yandex" && e.article_revision==="test-revision"));
      assert((await events(page)).some(e=>e.event_type===prefix+"max_click"));
      assert(!requests.some(url=>url.includes("/api/intensive/")),"Public traffic must not call the personal API");
      assert.equal(requests.filter(url=>url.includes("mc.yandex.ru")).length,1);
      await context.close();passed++;
    }
    {
      const {page,context}=await setup("intensive-analytics.test",true);
      const calls=await page.evaluate(()=>Array.from(window.ym.a,call=>Array.from(call)));
      assert.equal(calls.filter(call=>call[1]==="init").length,1,"Reuse existing counter initialization");
      assert.equal(calls.filter(call=>call[1]==="hit").length,0,"Do not duplicate existing pageview");
      await context.close();passed++;
    }
    {
      const {page,context}=await setup("127.0.0.1",false,true);
      await page.evaluate(()=>document.querySelector("img").dispatchEvent(new Event("error")));
      const errors=(await events(page)).filter(e=>e.event_type===prefix+"media_error");
      assert.equal(errors.length,1,"Broken image counted once even if already failed at initialization");
      assert.equal(errors[0].image_index,0);
      assert(!JSON.stringify(errors).includes("broken.png"),"Error telemetry does not transmit asset URLs");
      await context.close();passed++;
    }
    {
      // Real embedding: defer executes before DOMContentLoaded and window.load.
      const {page,context}=await setup("127.0.0.1",false,false,{defer:true});
      await flush(page);
      const list=await events(page);
      for(const event of ["open","ready","loaded"]) assert.equal(list.filter(e=>e.event_type===prefix+event).length,1,event+" from defer embedding");
      assert.equal(await page.evaluate(()=>window.__trackerReadyState),"interactive");
      assert.equal(typeof list.find(e=>e.event_type===prefix+"loaded").load_ms,"number");
      await context.close();passed++;
    }
    {
      for(const options of ["i","token"].flatMap(key=>[
        {personal:key}, {referrer:"http://intensive-analytics.test/source?"+key+"=PRIVATE"}
      ])) {
        const {page,context,requests}=await setup("intensive-analytics.test",false,false,options);
        await page.locator(".reading-header a").click();await flush(page);
        assert.equal(await page.evaluate(()=>typeof window.ym),"undefined","Personal link must not initialize SDK");
        assert.equal(requests.length,1,"No analytics requests for personal URL or referrer");
        await context.close();
      }
      passed++;
    }
    {
      const {page,context,posts}=await setup("intensive-analytics.test",false,false,{identified:true,secure:true});
      await page.clock.runFor(16000);
      assert((await events(page)).some(e=>e.event_type===prefix+"reading_start"),"Ten active seconds and visible text indicate start");
      await page.locator(".reading-header a").click();await flush(page);
      await page.evaluate(()=>document.querySelector("#end").scrollIntoView());await flush(page);
      await page.locator('[data-intensive-channel="telegram"]').click();await flush(page);
      const own=posts.filter(p=>p.url.includes("/api/intensive/events")).map(p=>p.body);
      for(const event of ["open","section","end","messenger_click","heading","reading_start","progress"]) assert(own.some(p=>p.event_type===prefix+event),"Personal event "+event);
      assert(own.some(p=>p.event_type===prefix+"section" && p.section==="block-3"),"Personal section retains its identifier");
      assert(own.some(p=>p.event_type===prefix+"messenger_click" && p.messenger==="telegram"),"Personal channel retains its identifier");
      assert(own.every(p=>p.event_id && !p.user_id && !p.token));
      assert(own.filter(p=>p.event_type===prefix+"progress").every(p=>p.visit_id && p.article_revision==="test-revision" && Number.isInteger(p.viewed_percent)));
      await context.close();passed++;
    }
    console.log(JSON.stringify({status:"pass",browser_scenarios:passed}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});

