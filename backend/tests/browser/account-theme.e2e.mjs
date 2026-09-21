import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const origin = process.env.QA_BASE_URL || 'http://127.0.0.1:8798';
assert(/^(localhost|127\.0\.0\.1)$/.test(new URL(origin).hostname), 'Use a synthetic local fixture, never a real account');
const out = process.env.QA_OUT;
assert(out, 'QA_OUT must name a fresh external evidence directory');
await mkdir(out, {recursive:true});
const browser = await chromium.launch({headless:true,args:['--disable-gpu','--in-process-gpu']});
const context = await browser.newContext({viewport:{width:1440,height:1000}, reducedMotion:'reduce',ignoreHTTPSErrors:true});
const page = await context.newPage();
const errors = [];
const widths = [320,359,360,430,768,900,901,1200,1201,1440];
page.on('pageerror', e => errors.push(String(e)));
// No outgoing production API request is allowed in this local test.
await context.route('**/api/**', route => {
  assert.equal(new URL(route.request().url()).origin, origin);
  return route.continue();
});
const ready = () => page.waitForFunction(() => !document.querySelector('.ed-loading-screen') && document.querySelector('.account-theme-toggle'));
const skin = () => page.evaluate(() => ({theme:document.documentElement.dataset.accountTheme,bg:getComputedStyle(document.body).backgroundColor}));
const checkPlacement = async width => {
  const geometry = await page.evaluate(() => {
    const toggle = document.querySelector('.account-theme-toggle');
    const box = toggle.getBoundingClientRect();
    const header = document.querySelector('#masterclass-course-app .topbar');
    const controls = [...header.querySelectorAll('.menu,.mobile-content,.mobile-account,.account-theme-toggle')]
      .filter(el => getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none')
      .map(el => {const r=el.getBoundingClientRect();return {x:r.x,right:r.right,y:r.y,height:r.height};})
      .sort((a,b)=>a.x-b.x);
    return {count:document.querySelectorAll('.account-theme-toggle').length,
      inSidebarHeader:toggle.parentElement.matches('.preview-sidebar-header'),position:getComputedStyle(toggle).position,
      accountHidden:getComputedStyle(header.querySelector('.mobile-account')).display==='none',
      sidebarControls:[...document.querySelectorAll('.preview-sidebar-header>*')].map(el=>{const r=el.getBoundingClientRect();return {x:r.x,right:r.right,y:r.y,height:r.height};}),
      themeIconWidth:toggle.querySelector('svg').getBoundingClientRect().width,
      closeLineWidth:parseFloat(getComputedStyle(document.querySelector('.close-menu'),'::before').width),
      backCenter:document.querySelector('#article-view:not([hidden]) #back')?.getBoundingClientRect().y + (document.querySelector('#article-view:not([hidden]) #back')?.getBoundingClientRect().height || 0)/2,
      x:box.x,right:box.right,y:box.y,width:box.width,height:box.height,controls};
  });
  assert.equal(geometry.count,1);
  assert(geometry.width>=(width<=900?32:44) && geometry.height>=(width<=900?32:44),'Theme target must match the agreed responsive size');
  if(width<=900) {
    assert(geometry.inSidebarHeader,'Mobile theme control must be in the outline next to close');
    assert(geometry.accountHidden,'Mobile course topbar must omit the account link');
    const row=geometry.sidebarControls;
    assert(geometry.width<44 && geometry.height<44,'Mobile theme control must be smaller than the rejected version');
    assert.equal(row[2].right-row[2].x,geometry.width,'Close and theme buttons must retain equal widths');
    assert.equal(row[2].height,geometry.height,'Close and theme buttons must retain equal heights');
    assert(geometry.themeIconWidth<22 && geometry.closeLineWidth<26,'Both mobile symbols must be smaller than the rejected version');
    for(let i=1;i<row.length;i++) {
      assert(row[i-1].right<=row[i].x,'Logo, theme and close must not overlap');
      assert(Math.abs(row[i-1].y+row[i-1].height/2-row[i].y-row[i].height/2)<1,'Outline header controls must align');
    }
    for(let i=1;i<geometry.controls.length;i++) {
      assert(geometry.controls[i-1].right<=geometry.controls[i].x,'Header controls overlap');
      const a=geometry.controls[i-1],b=geometry.controls[i];
      assert(Math.abs(a.y+a.height/2-b.y-b.height/2)<1,'Header controls must share one row');
    }
  } else {
    assert.equal(geometry.position,'fixed');
    assert.equal(geometry.y,38);
    assert.equal(geometry.right,width-20);
    if(Number.isFinite(geometry.backCenter)) assert(Math.abs(geometry.y+geometry.height/2-geometry.backCenter)<1,'Theme toggle must align with the back button');
  }
};
try {
  // Saved dark theme must cover the real native loader before account data arrives.
  const cold = await browser.newContext({viewport:{width:360,height:1000}});
  await cold.addInitScript(() => localStorage.setItem('edabalans-account-theme-v1','dark'));
  let releaseAccount;
  const pendingAccount = new Promise(resolve => { releaseAccount=resolve; });
  await cold.route(origin+'/api/account-auth/account',async route => {
    await pendingAccount;
    return route.continue();
  });
  const boot = await cold.newPage();
  await boot.goto(origin+'/lk',{waitUntil:'domcontentloaded'});
  await boot.locator('.ed-loading-screen').waitFor();
  assert.equal(await boot.evaluate(()=>document.documentElement.dataset.accountTheme),'dark');
  assert.equal(await boot.locator('.ed-loading-screen').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(23, 26, 32)');
  await boot.screenshot({path:out+'/saved-dark-loader-360.png'});
  releaseAccount();
  await boot.locator('.account-card').first().waitFor();
  await boot.waitForFunction(()=>!document.querySelector('.ed-loading-screen'));
  assert.equal(await boot.locator('.account-theme-toggle').count(),1);
  await cold.close();
  // First-visit consent actions use the same readable dark surface as other UI.
  const legalPage = await context.newPage();
  await legalPage.route(origin+'/api/account-auth/account',async route => {
    const response=await route.fetch();
    const account=await response.json();
    account.legal={required:true,documents:[{code:'disclaimer',title:'Тестовый документ',accepted:false}]};
    await route.fulfill({json:account});
  });
  await legalPage.goto(origin+'/lk?theme=dark');
  const accept=legalPage.locator('#accept-legal');
  await accept.waitFor();
  assert(await accept.isDisabled());
  await legalPage.locator('[data-legal="disclaimer"]').check();
  assert(await accept.isEnabled());
  assert.equal(await accept.evaluate(el=>getComputedStyle(el).color),'rgb(105, 201, 255)');
  assert.equal(await accept.evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(38, 52, 66)');
  for(const width of [360,1440]) {
    await legalPage.setViewportSize({width,height:1000});
    await accept.scrollIntoViewIfNeeded();
    await legalPage.screenshot({path:out+'/legal-gate-dark-'+width+'.png'});
  }
  // No acceptance POST: never modify real or synthetic user consents in this test.
  await legalPage.close();
  const dqs = await context.newPage();
  await dqs.goto(origin+'/lk?theme=dark&course_day=4&course_material=day-04-dqs');
  await dqs.locator('#dqs-open-app').waitFor();
  for (const id of ['dqs-open-app','dqs-print']) {
    const colors = await dqs.locator('#'+id).evaluate(el => {
      const style=getComputedStyle(el);
      return {background:style.backgroundColor,color:style.color};
    });
    assert.notEqual(colors.background,colors.color,'DQS action must not become white on white');
    assert.equal(colors.color,'rgb(105, 201, 255)');
  }
  await dqs.locator('#dqs-open-app').scrollIntoViewIfNeeded();
  await dqs.screenshot({path:out+'/dqs-actions-dark-1440.png'});
  await dqs.close();
  await page.goto(origin+'/lk?theme=light');
  await page.locator('.account-card').first().waitFor();
  await ready();
  assert.deepEqual(await skin(), {theme:'light',bg:'rgb(255, 255, 255)'});
  await page.evaluate(()=>document.fonts.ready);
  assert(await page.evaluate(()=>document.fonts.check('800 23px Manrope','Курсы')));
  await page.screenshot({path:out+'/account-light-1440.png',fullPage:true});
  await page.getByRole('button', {name:'Включить тёмную тему',exact:true}).click();
  assert.deepEqual(await skin(), {theme:'dark',bg:'rgb(23, 26, 32)'});
  assert.equal(await page.locator('.account-theme-toggle').getAttribute('aria-pressed'),'true');
  await page.reload(); await ready();
  assert.equal((await skin()).theme, 'dark');
  for (const width of widths) {
    await page.setViewportSize({width,height:1000});
    assert(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:out+'/account-dark-'+width+'.png',fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-app="masterclass-course"]').click(); await ready();
  await page.locator('#day .hero h1').waitFor();
  assert.equal(await page.locator('.account-theme-toggle').count(),1);
  assert(await page.locator('.content > .account-theme-toggle').count());
  assert.equal(await page.locator('.sidebar .account-theme-toggle').count(),0);
  for (const width of widths) {
    await page.setViewportSize({width,height:1000});
    await checkPlacement(width);
    if(width<=900) {await page.locator('#menu').click(); await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().x)<1);}
    await page.screenshot({path:out+'/outline-dark-'+width+'.png'});
    if(width<=900) {await page.locator('#close').click();await page.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<1);}
    await page.screenshot({path:out+'/day-dark-'+width+'.png',fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-step="0"]').click();
  await page.locator('#article .article-note-accent').first().waitFor();
  assert.equal((await skin()).theme,'dark');
  assert.equal(await page.locator('#article').evaluate(el=>getComputedStyle(el).color),'rgb(237, 241, 245)');
  assert.equal(await page.locator('#article .article-note-accent').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(81, 71, 43)');
  for(const width of widths) {
    await page.setViewportSize({width,height:1000});
    await page.evaluate(async()=>{scrollTo({top:0,behavior:'instant'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));scrollTo({top:0,behavior:'instant'});});
    await page.waitForFunction(()=>scrollY===0);
    await checkPlacement(width);
    if(width<=900) {
      const contents=page.locator('#mobile-article-toc-button');
      assert(await contents.isVisible(),'Material Contents must remain visible on mobile');
      await contents.click();
      const popover=page.locator('#mobile-article-toc-popover');
      assert(await popover.isVisible(),'Mobile Contents must open on click');
      const link=popover.locator('nav a').first();
      const href=await link.getAttribute('href');
      await page.screenshot({path:out+'/contents-mobile-dark-'+width+'.png'});
      await link.click();
      assert(!(await popover.isVisible()),'Contents must close after navigation');
      assert.equal(await page.evaluate(()=>document.activeElement.id),href.slice(1));
      await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
      await page.waitForFunction(()=>scrollY===0);
    }
    await page.screenshot({path:out+'/material-dark-'+width+'.png'});
    for(const [name,selector] of [['note','.article-note-accent'],['table','.dqs-score-table-wrap'],['gallery','#article [data-gallery]'],['navigation','.article-nav']]) {
      await page.locator(selector).first().scrollIntoViewIfNeeded();
      if(name==='gallery') {
        await page.locator(selector).first().locator('img').first().evaluate(img=>img.decode());
        assert.equal(await page.locator(selector).first().locator('.gallery-slide').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(34, 40, 49)');
      }
      await page.screenshot({path:out+'/material-'+name+'-dark-'+width+'.png'});
      if(width>900) {
        const safe = await page.locator(selector).first().evaluate(el=>el.getBoundingClientRect().right <= document.querySelector('.account-theme-toggle').getBoundingClientRect().left);
        assert(safe,'Fixed theme control must not cover scrolled material blocks');
      }
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  await page.setViewportSize({width:1440,height:1000});
  const gallery = page.locator('#article [data-gallery]').first();
  if(await gallery.count()) {
    await gallery.scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/gallery-dark-1440.png'});
  }
  await page.locator('#article-toc-button').hover();
  assert(await page.locator('#article-toc-popover').isVisible());
  await page.screenshot({path:out+'/toc-dark-1440.png'});
  await page.getByRole('button',{name:'Включить светлую тему',exact:true}).click();
  assert.equal((await skin()).theme,'light');
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#article .article-note-accent')).backgroundColor==='rgb(255, 246, 201)');
  assert.equal(await page.locator('#article .article-note-accent').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 246, 201)');
  await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:out+'/material-light-1440.png'});
  await page.reload(); await ready();
  assert.equal((await skin()).theme,'light');
  for(const width of widths) {
    await page.setViewportSize({width,height:1000});
    await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
    await checkPlacement(width);
    await page.screenshot({path:out+'/material-light-'+width+'.png'});
    if(width<=900) {
      await page.locator('#menu').click();
      await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().x)<1);
      await page.screenshot({path:out+'/outline-light-'+width+'.png'});
      await page.locator('#close').click();
      await page.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<1);
    }
  }
  await page.setViewportSize({width:360,height:1000});
  await page.locator('#menu').click();
  await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().x)<1);
  await page.getByRole('button',{name:'Включить тёмную тему',exact:true}).click();
  assert.equal((await skin()).theme,'dark');
  await page.locator('.account-theme-toggle').focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('.account-theme-toggle').evaluate(el=>getComputedStyle(el).outlineStyle),'solid');
  await page.screenshot({path:out+'/outline-dark-focused-360.png'});
  await page.getByRole('button',{name:'Включить светлую тему',exact:true}).click();
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#back').click();
  await page.locator('#day .hero h1').waitFor();
  await page.screenshot({path:out+'/day-light-1440.png',fullPage:true});
  assert.deepEqual(errors,[]);
  await writeFile(out+'/result.json',JSON.stringify({passed:true,widths,errors},null,2));
  console.log('PASS: dark/light toggle, persistence, dashboard → day → material, outline, notes, tables, navigation, TOC, responsive widths.');
} finally {
  await browser.close();
}
