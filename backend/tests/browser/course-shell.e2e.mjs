import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const origin = process.env.QA_BASE_URL || 'http://127.0.0.1:8876';
assert(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
assert(process.env.QA_OUT, 'QA_OUT must name an external evidence directory');
await mkdir(process.env.QA_OUT, {recursive:true});
// Serve real app fragments/assets locally; only private course data is synthetic.
const widths = [359,360,361,429,430,431,619,620,621,768,899,900,901,1440];
const browser = await chromium.launch({headless:true});
const errors = [];
const referenceSkin = {};
const results = [];
const article = '<p>Начало материала.</p>' + [1,2,3].map(n =>
  `<h2>Раздел ${n}</h2><p>${'Текст для проверки перехода по содержанию. '.repeat(35)}</p>`).join('');

try {
  for (const {code,entry} of ['masterclass','recipes','calories'].flatMap(code=>['direct','embedded'].map(entry=>({code,entry}))).concat({code:'future',entry:'direct'})) {
    const context = await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(`${code}/${entry}: ${e}`));
    await page.addInitScript(() => {
      window.EdabalansIdentity = {email:'fixture@example.test',source:'native'};
      window.EdabalansAppHost = location.origin;
    });
    const appCode = code === 'future' ? 'masterclass' : code;
    const query = appCode === 'recipes' ? 'recipes_section=1&recipes_material=fixture-article'
      : appCode === 'calories' ? 'calories_stage=1&calories_material=fixture-article'
      : 'course_day=1&course_material=fixture-article';
    const step = {id:'fixture-article',kind:'article',title:'Проверка оболочки курса',summary:'',durationMinutes:3};
    const manifest = {courseCode:code,courseVersion:'fixture',structureVersion:1,title:'Тестовый курс',
      navigation:code === 'masterclass' || code === 'future' ? 'days' : 'materials',
      linearNavigation:code === 'recipes',days:[{number:1,title:'Тестовый раздел',checks:[],steps:[step]}]};
    const progress = {course_version:'fixture',structure_version:1,fully_unlocked:true,current_day:1,
      server_now:new Date().toISOString(),days:[{number:1,opened:true,can_open:true,completed_steps:[],checkmarks:{}}]};
    const calls = [];
    await page.route('**/api/**', route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, origin);
      assert.equal(route.request().method(), 'GET', 'Navigation must not mutate progress');
      calls.push(url.pathname + url.search);
      if (url.pathname.endsWith('/manifest')) return route.fulfill({json:manifest});
      if (url.pathname.endsWith('/materials')) {
        assert.equal(url.searchParams.get('step_id'), step.id, 'Fetch only the selected material');
        return route.fulfill({json:{materials:{[step.id]:{html:article,word_count:400,version:1}}}});
      }
      return route.fulfill({json:progress});
    });
    if (code === 'future') {
      await page.route(origin + '/apps/masterclass-course.html**', async route => {
        const response = await route.fetch();
        // A new course ID must inherit the same shell without a CSS/JS allowlist edit.
        const html = (await response.text()).replaceAll('masterclass-course-app','future-course-app');
        await route.fulfill({response,body:html});
      });
    }
    if (entry==='embedded') {
      await page.route(origin+'/fixture-lk**', route => route.fulfill({contentType:'text/html; charset=utf-8',body:`<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/assets/account-visual.css"><div id="account-app"><main class="account-shell"><button id="fixture-open">Открыть курс</button></main><div id="fixture-slot"></div></div><script src="/assets/account-theme.js"></script><script src="/embed.js"></script><script>document.querySelector('#fixture-open').onclick=function(){document.querySelector('.account-shell').remove();var mount=document.querySelector('#fixture-slot');mount.className='fixture-host';mount.setAttribute('data-edabalans-app','${appCode}-course');mount.setAttribute('data-edabalans-manual','true');EdabalansEmbed.load(mount);}</script>`}));
      await page.goto(`${origin}/fixture-lk?${query}`);
      await page.locator('.account-shell .account-theme-toggle').waitFor();
      await page.locator('#fixture-open').click();
      await page.waitForFunction(()=>!document.querySelector('.ed-loading-screen'));
      assert(await page.locator('.course-shell.fixture-host').count(), 'Mount preserves host classes');
    } else await page.goto(`${origin}/apps/${appCode}-course.html?${query}`);
    await page.locator('#article h2').first().waitFor();
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.locator('.course-shell').count(),1);
    assert.equal(await page.locator('.account-theme-toggle').count(),1);
    const label = `${code}-${entry}`;

    for (const theme of ['light','dark']) {
      if (theme === 'dark') await page.locator('.account-theme-toggle').click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.accountTheme),theme);
      await page.screenshot();
      const skin = await page.evaluate(() => {
        const css = selector => getComputedStyle(document.querySelector(selector));
        return {sidebar:css('.sidebar').backgroundImage,article:css('#article').color,
          navigation:css('#next').backgroundImage,background:css('body').backgroundColor};
      });
      assert.equal(skin.article, theme==='dark'?'rgb(237, 241, 245)':'rgb(23, 25, 30)', 'Readable article text after theme paint');
      assert.equal(skin.background, theme==='dark'?'rgb(23, 26, 32)':'rgb(255, 255, 255)', 'Course page surface follows theme');
      if (code==='masterclass' && entry==='direct') referenceSkin[theme] = skin;
      assert.deepEqual(skin, referenceSkin[theme], `${label}: shared ${theme} surfaces`);
      if(theme==='dark') assert.notDeepEqual(skin, referenceSkin.light, 'Theme must change rendered surfaces');
      for (const width of widths) {
        await page.setViewportSize({width,height:1000});
        if (width<=900 && await page.locator(".sidebar.open").count()) await page.locator("#close").click();
        await page.evaluate(async () => { document.body.getBoundingClientRect(); await document.fonts.ready; await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); scrollTo({top:0,behavior:'instant'}); });
        await page.screenshot();
        const geometry = await page.evaluate(() => {
          const rect = selector => {
            const element = document.querySelector(selector), r = element.getBoundingClientRect();
            const s = getComputedStyle(element);
            return {x:r.x,right:r.right,y:r.y,height:r.height,display:s.display,font:s.font,padding:s.padding};
          };
          return {viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,overflow:document.documentElement.scrollWidth > innerWidth,
            menu:rect('#menu'),brand:rect('.course-topbar-brand'),lockup:rect('.course-topbar-brand__lockup'),
            contents:rect('#mobile-article-toc-button'),back:rect('#back'),meta:rect('#count'),
            toggleInSidebar:document.querySelector('.account-theme-toggle').parentElement.matches('.preview-sidebar-header')};
        });
        assert.equal(geometry.overflow,false,`${code}/${theme}/${width}: overflow`);
        assert(Math.abs(geometry.back.y + geometry.back.height/2 - geometry.meta.y - geometry.meta.height/2)<1,
          'Return and metadata must share one row');
        assert.equal(geometry.toggleInSidebar,width<=900);
        if (width<=900) {
          assert.notEqual(geometry.brand.display,'none');
          assert.equal(geometry.menu.font,geometry.contents.font);
          assert.equal(geometry.menu.padding,geometry.contents.padding);
          assert(geometry.menu.right<=geometry.lockup.x && geometry.lockup.right<=geometry.contents.x,
            `${code}/${width}: logo or buttons overlap`);
          await page.locator('#mobile-article-toc-button').click();
          await page.screenshot({path:`${process.env.QA_OUT}/${label}-${theme}-contents-${width}.png`});
          assert(await page.locator('#mobile-article-toc-popover').isVisible());
          await page.locator('#mobile-article-toc-popover a').nth(1).click();
          assert.equal(await page.evaluate(() => document.activeElement.textContent),'Раздел 2');
          assert.equal(await page.locator('#mobile-article-toc-popover').isVisible(),false);
          await page.locator('#menu').click();
          assert(await page.locator('.sidebar').evaluate(el => el.classList.contains('open')));
          await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().x)<1);
          assert(await page.locator('.sidebar-account').isVisible());
          await page.screenshot({path:`${process.env.QA_OUT}/${label}-${theme}-outline-${width}.png`});
          await page.locator('#close').click();
          assert.equal(await page.locator('.sidebar').evaluate(el => el.classList.contains('open')),false);
          await page.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<1);
        } else {
          await page.locator('#article-toc-button').hover();
          await page.screenshot({path:`${process.env.QA_OUT}/${label}-${theme}-contents-${width}.png`});
          assert(await page.locator('#article-toc-popover').isVisible());
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('#article-toc-popover').isVisible(),false);
        }
        await page.evaluate(async () => { document.body.getBoundingClientRect(); await document.fonts.ready; await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); scrollTo({top:0,behavior:'instant'}); });
        await page.screenshot({path:`${process.env.QA_OUT}/${label}-${theme}-material-${width}.png`});
        results.push({code,entry,theme,width,geometry,skin});
      }
      assert.equal(await page.locator('.sidebar-account').getAttribute('href'),'/lk');
      await page.locator('#article-outline').click();
      assert(await page.locator('.sidebar').isVisible());
      if (page.viewportSize().width<=900) await page.locator('#close').click();
      const item = manifest.navigation==='materials' ? '[data-material-index="0"]' : '[data-step="0"]';
      await page.locator(item).click();
      await page.locator('#article h2').first().waitFor();
    }
    assert.equal(calls.filter(url => url.includes('/materials?')).length,1,'Reopening reuses material cache');
    await context.close();
  }
  assert.deepEqual(errors,[]);
  await writeFile(`${process.env.QA_OUT}/result.json`,JSON.stringify({passed:true,widths,results,errors},null,2));
  console.log(`PASS: shared header, outline, contents, theme, return and cache; ${results.length} course/theme/viewport cases`);
} finally {
  await browser.close();
}
