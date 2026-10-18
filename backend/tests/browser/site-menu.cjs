const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.MENU_TEST_URL || 'http://127.0.0.1:8776';
const evidence = process.env.MENU_EVIDENCE_DIR;
(async () => {
  const browser = await chromium.launch();
  try {
    for (const width of [360, 430, 768, 899, 900, 1440]) {
      for (const [name, route] of [['homepage','/preview/homepage-release-candidate'], ['intensive','/intensive']]) {
        const context = await browser.newContext({viewport:{width,height:850}});
        const page = await context.newPage();
        const errors=[];
        page.on('pageerror', e => errors.push(e.message));
        await page.route('https://mc.yandex.ru/**', r=>r.abort());
        await page.goto(base+route, {waitUntil:'domcontentloaded'});
        const toggle=page.locator('[data-site-menu-toggle]');
        const panel=page.locator('[data-site-menu]');
        await toggle.waitFor({state:'visible'});
        const closed=await toggle.boundingBox();
        assert.equal(closed.y > 650, name==='intensive' && width<900, name+' trigger position at '+width);
        if (name==='intensive' && width<900) {
          const cookie=page.locator('[data-cookie-dismiss]');
          if (await cookie.isVisible()) assert(await cookie.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),'cookie acceptance remains reachable');
        }
        if (name==='intensive' || width>=900) assert(await page.locator('.site-menu-toggle__label').isVisible());
        await page.evaluate(()=>window.scrollTo(0,300));
        if (evidence) await page.screenshot({path:path.join(evidence,`${name}-${width}-closed.png`)});
        await toggle.click();
        await page.waitForFunction(()=>document.querySelector('[data-site-menu-toggle]').getAttribute('aria-expanded')==='true');
        await page.waitForFunction(width => {
          const panel = document.querySelector('[data-site-menu]');
          const button = document.querySelector('[data-site-menu-toggle]');
          return getComputedStyle(panel).visibility === 'visible' &&
            Math.round(button.getBoundingClientRect().width) === (width >= 900 ? 44 : 38);
        }, width);
        assert(await panel.isVisible());
        assert.equal(await panel.getAttribute('aria-hidden'),'false');
        const expanded=page.locator('[data-site-menu-contents]');
        assert.equal(await expanded.getAttribute('aria-expanded'),'true');
        const box=await panel.boundingBox();
        assert.equal(Math.round(box.width),width>=900?400:width);
        const button=await toggle.boundingBox();
        assert(button.y>=0 && button.y+button.height<=58,'cross stays in blue band');
        assert.equal(Math.round(button.width),width>=900?44:38);
        const position=await page.evaluate(()=>window.scrollY);
        await page.mouse.move(50,500);
        await page.mouse.wheel(0,500);
        await page.waitForTimeout(100);
        assert.equal(await page.evaluate(()=>window.scrollY),position,'page stays frozen');
        await page.mouse.move(box.x + box.width / 2, 600);
        await page.mouse.wheel(0, 800);
        await page.waitForTimeout(100);
        if (await panel.evaluate(el=>el.scrollHeight>el.clientHeight)) assert(await panel.evaluate(el=>el.scrollTop)>0,'outline scrolls independently');
        await panel.evaluate(el=>el.scrollTo(0,0));
        if (evidence) await page.screenshot({path:path.join(evidence,`${name}-${width}-open.png`)});
        await expanded.click();
        assert.equal(await expanded.getAttribute('aria-expanded'),'false');
        assert.equal(await panel.locator('.site-menu-contents').isVisible(),false,'outline actually collapses');
        await expanded.click();
        assert(await panel.locator('.site-menu-contents').isVisible(),'outline expands again');
        const contacts=panel.getByRole('button',{name:/^Контакты/});
        await contacts.click();
        assert(await panel.getByRole('link',{name:'Telegram-канал',exact:true}).isVisible());
        await panel.getByRole('button',{name:/^Личный кабинет/}).click();
        assert(await panel.getByRole('link',{name:'Войти',exact:true}).isVisible());
        await toggle.focus();
        await page.keyboard.press('Shift+Tab');
        assert(await panel.evaluate(el=>el.contains(document.activeElement)),'focus wraps into menu');
        await page.keyboard.press('Escape');
        assert.equal(await toggle.getAttribute('aria-expanded'),'false');
        assert.equal(await panel.getAttribute('aria-hidden'),'true');
        assert(await toggle.evaluate(el=>el===document.activeElement));
        await toggle.click();
        const first=panel.locator('.site-menu-contents a').first();
        const href=await first.getAttribute('href');
        await first.click();
        assert.equal(await toggle.getAttribute('aria-expanded'),'false');
        assert.equal(new URL(page.url()).hash,href);
        assert(!await page.evaluate(()=>document.documentElement.classList.contains('site-menu-open')));
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no horizontal overflow');
        assert.deepEqual(errors,[],name+' page errors');
        console.log('PASS',name,width);
        await context.close();
      }
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
