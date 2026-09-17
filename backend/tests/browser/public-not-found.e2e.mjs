import assert from 'node:assert/strict'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const base = process.env.PUBLIC_NOT_FOUND_BASE_URL || 'http://127.0.0.1:8775'
const browser = await chromium.launch({ headless: true })

try {
  for (const width of [360, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    const fragmentRequests = []
    await page.route('https://edabalans.ru/**', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith('.svg')) {
        await route.abort()
        return
      }
      if (url.pathname.endsWith('404-fragment.html')) {
        fragmentRequests.push({ url: request.url(), headers: await request.allHeaders() })
      }
      const response = await context.request.get(base + url.pathname)
      await route.fulfill({ response })
    })
    await page.goto(base + '/public-site-errors/404-fragment.html?E=private-marker')
    await page.setContent('<div data-edabalans-404><a href="https://похудение-это-есть.рф/">На главную</a></div>')
    await page.addScriptTag({ url: base + '/public-site-errors/404.js' })
    await page.locator('[data-edabalans-404][data-mounted="true"]').waitFor()
    await page.locator('[data-edabalans-site-footer] a[href="https://t.me/FitnessSergey"]').waitFor()
    await page.addScriptTag({ url: base + '/public-site-errors/404.js' })
    assert.equal(await page.locator('.ed404').count(), 1)
    assert.equal(fragmentRequests.length, 1)
    assert.equal(fragmentRequests[0].url, 'https://edabalans.ru/public-site-errors/404-fragment.html')
    assert.equal(fragmentRequests[0].headers.referer, undefined)
    assert.equal(fragmentRequests[0].headers.cookie, undefined)
    assert.equal(await page.locator('meta[name="robots"]').getAttribute('content'), 'noindex,nofollow')
    assert.equal(await page.getByRole('heading', { name: 'Страница не найдена' }).count(), 1)
    assert.equal(await page.locator('.ed404__links a').count(), 4)
    assert.equal(await page.locator('.ed404__links').isVisible(), true)
    assert.equal((await page.locator('.ed404').innerHTML()).includes('private-marker'), false)
    const headerNav = page.locator(width === 360 ? '.eb-site-header__mobile-links' : '.eb-site-header__nav')
    if (width === 360) await page.getByRole('button', { name: 'Открыть меню' }).click()
    assert.equal(await headerNav.locator('a').filter({ hasText: /^Главная$/ }).getAttribute('href'), 'https://похудение-это-есть.рф/')
    assert.equal(await headerNav.locator('a').filter({ hasText: /^Блог$/ }).getAttribute('href'), 'https://edabalans.ru/blog')
    assert.equal(await headerNav.locator('a').filter({ hasText: /^Бесплатный интенсив$/ }).isVisible(), true)
    await context.close()
  }
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.route('https://edabalans.ru/**', route => route.abort())
  await page.goto(base + '/public-site-errors/404-fragment.html')
  await page.setContent('<div data-edabalans-404><a href="https://похудение-это-есть.рф/">На главную</a></div>')
  await page.addScriptTag({ url: base + '/public-site-errors/404.js' })
  await page.waitForFunction(() => !document.querySelector('[data-edabalans-404]').dataset.loading)
  assert.equal(await page.getByRole('link', { name: 'На главную' }).isVisible(), true)
  await context.close()
  console.log('404 loader: desktop/mobile mount, idempotence, safe fetch, broken image and fetch failure passed')
} finally {
  await browser.close()
}
