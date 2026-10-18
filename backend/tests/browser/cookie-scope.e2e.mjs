import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const notice = readFileSync(new URL('../../app/static/site-cookie-notice.js', import.meta.url), 'utf8');
const journey = readFileSync(new URL('../../app/static/browser-journey.js', import.meta.url), 'utf8');
const primary = new URL('https://похудение-это-есть.рф').origin;
const browser = await chromium.launch({headless: true});
try {
  for (const origin of [primary, 'https://edabalans.ru']) {
    const context = await browser.newContext();
    const calls = [];
    const navigations = [];
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === '/fixture-session') return route.fulfill({contentType:'text/html', body:'Session fixture', headers:{'Set-Cookie':'edabalans_account_session=test-session; Path=/; Secure; HttpOnly; SameSite=Lax'}});
      if (url.pathname === '/cookie-notice.js') return route.fulfill({contentType:'application/javascript', body:notice});
      if (url.pathname === '/browser-journey.js') return route.fulfill({contentType:'application/javascript', body:journey});
      if (url.pathname === '/api/public/browser-journey') {
        const body = request.postDataJSON();
        calls.push(body);
        return route.fulfill({json:{context:'stable-browser', transfer:'signed-transfer'}});
      }
      navigations.push({path:url.pathname, cookies:await request.headerValue('cookie') || ''});
      const publicPage = !url.pathname.startsWith('/lk') && !url.pathname.startsWith('/apps/');
      return route.fulfill({contentType:'text/html', body:'<!doctype html><html><head><meta charset="utf-8">'+
        (publicPage ? '<script src="/cookie-notice.js" defer></script>' : '')+'</head><body>Fixture</body></html>'});
    });
    const page = await context.newPage();
    await page.goto(origin+'/fixture-session');
    await page.goto(origin+'/');
    await page.locator('[data-cookie-notice]:visible').waitFor();
    await page.waitForFunction(() => window.EdabalansBrowserJourney?.context());
    assert(calls.every(call => call.event === 'init' && !call.accepted));
    const acceptedPage = page.waitForResponse(response => response.url().endsWith('/api/public/browser-journey') && response.request().postDataJSON().event === 'page');
    await page.locator('[data-cookie-dismiss]').click();
    await page.waitForFunction(() => window.EdabalansCookieNotice.accepted());
    await acceptedPage;
    for (const path of ['/blog','/blog/example','/intensive','/lk','/apps/masterclass-course.html']) {
      await page.goto(origin+path);
      if (path.startsWith('/blog') || path === '/intensive') {
        await page.waitForFunction(() => window.EdabalansCookieNotice?.accepted() && window.EdabalansBrowserJourney?.context());
      }
      assert.equal(await page.locator('[data-cookie-notice]:visible').count(), 0, origin+path);
      assert((await context.cookies()).some(cookie => cookie.name === 'edabalans_cookie_notice'));
    }
    const cookies = await context.cookies(origin);
    const consent = cookies.filter(cookie => cookie.name === 'edabalans_cookie_notice');
    assert.equal(consent.length, 1);
    assert.equal(consent[0].path, '/');
    assert.equal(consent[0].secure, true);
    assert.equal(consent[0].sameSite, 'Lax');
    assert(consent[0].expires > Date.now()/1000 + 364*86400);
    assert.equal(cookies.filter(cookie => cookie.name === 'edabalans_visitor').length, 1);
    assert(calls.filter(call => call.page_url !== origin+'/').every(call => call.context === 'stable-browser' && call.accepted));
    assert(navigations.every(item => item.cookies.includes('edabalans_account_session=test-session')));
    assert(!await page.evaluate(() => document.cookie.includes('edabalans_account_session')));
    const opposite = origin === primary ? 'https://edabalans.ru' : primary;
    assert.equal((await context.cookies(opposite)).length, 0);
    const admin = new URL(origin); admin.hostname = 'admin.'+admin.hostname;
    await page.goto(admin.origin+'/lk');
    assert(!navigations.at(-1).cookies.includes('edabalans_account_session'));
    await context.close();
  }
  console.log('cookie scope: shared public consent/context, root paths, host-only account session and two-root isolation PASS');
} finally { await browser.close(); }
