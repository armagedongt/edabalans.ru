const fs=require('node:fs'), assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const {chromium}=createRequire(process.env.NODE_PATH+'/package.json')('./');
const manifest=JSON.parse(fs.readFileSync('content/blog/manifest.json','utf8'));
const batch=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const base=process.env.BLOG_CHECK_URL||'http://127.0.0.1:8789';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  for(const width of [360,1440]) for(const decision of batch.articles){
   const article=manifest.articles.find(a=>a.source_id===decision.source_id);
   assert.ok(article);
   const context=await browser.newContext({viewport:{width,height:900}});
   const page=await context.newPage(), errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('https://edabalans.ru/**',async route=>{
    const url=new URL(route.request().url());
    const response=await context.request.get(base+url.pathname+url.search);
    await route.fulfill({response});
   });
   const ready=page.waitForResponse(r=>r.url().endsWith('/blog/reader/context'));
   const response=await page.goto(base+'/blog/articles/'+article.slug,{waitUntil:'load'});
   assert.equal(response.status(),200);
   await ready;
   if(decision.decision==='assigned'){
    await page.waitForSelector('#reader-channel-inline');
    assert.equal(await page.locator('#reader-channel-inline').count(),1);
    assert.equal(await page.locator('#reader-channel-inline').evaluate(n=>n.nextElementSibling.id),decision.anchor);
    assert.equal(await page.locator('#reader-channel-inline').evaluate(n=>n.previousElementSibling?.matches('.blog-cta,.reader-related')),false);
   }
   await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
   await page.waitForSelector('#reader-popup[open]');
   if(decision.decision==='no_slot') assert.equal(await page.locator('#reader-channel-inline').count(),0);
   assert.deepEqual(errors,[]);
   console.log(JSON.stringify({source_id:decision.source_id,width,decision:decision.decision,pass:true}));
   await context.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
