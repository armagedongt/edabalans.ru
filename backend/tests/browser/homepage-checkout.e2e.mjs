import assert from 'node:assert/strict'
import { join } from 'node:path'

const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8790'
const appUrl = 'https://app.edabalans.test'
const tildaUrl = 'https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/mk1'
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
})

const catalog = {
  version: 3,
  tariffs: [
    {
      code: 'site.masterclass.basic',
      name: 'Самостоятельный',
      sale_amount: 3900,
      compare_at_amount: 4900,
    },
  ],
}

try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  let checkoutBody = null
  let failNextStoredOfferValidation = false

  await page.route(`${tildaUrl}**`, route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><head><meta charset="utf-8"></head><body>
      <div class="t-rec"><div class="t123__centeredContainer">
        <div data-edabalans-homepage></div>
      </div></div>
      <script src="${appUrl}/homepage.js"></script>
    </body></html>`,
  }))

  await page.route(`${appUrl}/**`, async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/api/public/browser-journey') {
      await route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*','access-control-allow-methods':'POST, OPTIONS','access-control-allow-headers':'Content-Type'},body:JSON.stringify({context:'managed-homepage-browser',transfer:'managed-homepage-transfer'})});
      return;
    }
    if (url.pathname.startsWith('/api/pricing/site')) {
      if (request.method() === 'GET' && url.searchParams.get('intensive_offer') === 'offer-test' && failNextStoredOfferValidation) {
        failNextStoredOfferValidation = false
        await route.fulfill({status: 503, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: '{}'})
        return
      }
      if (request.method() === 'GET' && url.searchParams.get('intensive_offer') === 'expired-test') {
        await route.fulfill({status: 403, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: '{}'})
        return
      }
      await route.fulfill({
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify(request.method() === 'POST'
          ? { cart_command: '#order:Самостоятельный · №12345678=2900' }
          : (url.searchParams.get('intensive_offer')
            ? {...catalog, intensive_offer: {offer_id: 'intensive-day4-1000', discount_amount: 1000, expires_at: '2099-01-01T00:00:00Z'}}
            : catalog)),
      })
      return
    }
    if (url.pathname === '/api/payments/robokassa/start' && request.method() === 'POST') {
      checkoutBody = Object.fromEntries(new URLSearchParams(request.postData() || ''))
      await route.fulfill({
        contentType: 'text/html',
        body: `<!doctype html><form id="payment" action="https://auth.robokassa.ru/Merchant/Index.aspx" method="POST">
          <input name="MerchantLogin" value="test-shop"><input name="OutSum" value="2900"><input name="InvId" value="123">
        </form><script>document.getElementById('payment').submit()</script>`,
      })
      return
    }
    const upstream = await fetch(`${baseUrl}${url.pathname}${url.search}`)
    await route.fulfill({
      status: upstream.status,
      headers: { ...Object.fromEntries(upstream.headers), 'access-control-allow-origin': '*' },
      body: Buffer.from(await upstream.arrayBuffer()),
    })
  })

  await page.route('https://auth.robokassa.ru/**', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><title>Robokassa test form</title>',
  }))

  await page.goto(`${tildaUrl}?intensive_offer=offer-test`, {
    waitUntil: 'domcontentloaded',
  })
  await page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button').waitFor({ state: 'visible' })
  failNextStoredOfferValidation = true
  await page.goto(`${tildaUrl}?utm_source=telegram_channel&utm_content=post_42&yclid=channel-click`, { waitUntil: 'domcontentloaded' })
  const tildaButton = page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button')
  await tildaButton.waitFor({ state: 'visible' })
  const checkoutEndpoint = await page.locator('#edb-pricing-neurozeh-v1').getAttribute('data-checkout-endpoint')
  if (checkoutEndpoint !== `${appUrl}/api/payments/robokassa/start`) {
    throw new Error(`Loader did not rewrite cross-origin checkout endpoint: ${checkoutEndpoint}`)
  }
  await tildaButton.click()
  if (!(await page.locator('.edb-checkout-modal').isVisible())) {
    throw new Error('Direct Robokassa email modal did not open in Tilda embed mode')
  }
  await page.locator('.edb-checkout-email').fill('test@example.ru')
  await page.locator('input[name=accept_offer]').check()
  await page.locator('input[name=data_consent]').check()
  if (await page.locator('input[name=accept_offer]').count() !== 1 || await page.locator('input[name=data_consent]').count() !== 1) throw new Error('Consent fields must be separate');
  const paymentNavigation = page.waitForURL('https://auth.robokassa.ru/**')
  await page.locator('.edb-checkout-form').evaluate(form => form.requestSubmit())
  await paymentNavigation

  if (checkoutBody?.accept_offer !== 'true' || checkoutBody?.data_consent !== 'true') throw new Error('Consent confirmations missing from checkout');
  if (checkoutBody?.browser_context !== 'managed-homepage-browser') throw new Error('Managed homepage checkout lost browser context');
  if (checkoutBody?.price_code !== 'site.masterclass.basic' || checkoutBody?.intensive_offer !== 'offer-test') {
    throw new Error(`Stored intensive offer was not restored in Tilda checkout: ${JSON.stringify(checkoutBody)}`)
  }
  if (checkoutBody?.utm_source !== 'telegram_channel'
      || checkoutBody?.utm_content !== 'post_42'
      || checkoutBody?.yclid !== 'channel-click') {
    throw new Error(`Channel attribution was lost by the Tilda loader: ${JSON.stringify(checkoutBody)}`)
  }

  await page.goto(`${tildaUrl}?intensive_offer=expired-test`, { waitUntil: 'domcontentloaded' })
  const regularButton = page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button')
  await regularButton.waitFor({ state: 'visible' })
  if (new URL(page.url()).searchParams.has('intensive_offer')) {
    throw new Error('Expired intensive offer was left in the Tilda page URL')
  }
  checkoutBody = null
  await regularButton.click()
  if (!(await page.locator('.edb-checkout-modal').isVisible())) {
    throw new Error('Direct Robokassa email modal did not open after an expired offer')
  }

  const consultCatalog = {
    ...catalog,
    tariffs: [...catalog.tariffs, {
      code: 'site.masterclass.consult',
      name: 'С консультацией',
      sale_amount: 16800,
      compare_at_amount: 22500,
      course_support_amount: 3000,
    }],
  }
  await page.route('**/api/pricing/site/preview**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(consultCatalog),
  }))
  await page.goto(`${baseUrl}/preview/homepage-release-candidate`, { waitUntil: 'domcontentloaded' })
  const standaloneButton = page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button')
  await standaloneButton.waitFor({ state: 'visible' })
  await standaloneButton.click()
  if (!(await page.locator('.edb-checkout-modal').isVisible())) {
    throw new Error('Direct Robokassa email modal did not open in standalone mode')
  }
  assert.equal(await page.locator('.edb-checkout-support').isVisible(), false)
  await page.keyboard.press('Escape')

  const consultCard = page.locator('[data-price-code="site.masterclass.consult"]')
  assert.match(await consultCard.locator('[data-price-field="sale"]').textContent(), /16\s800 ₽/)
  assert.match(await consultCard.locator('[data-price-field="discount"] strong').textContent(), /−25%/)
  assert.equal(await consultCard.getByText('Ответы на вопросы').isVisible(), false)
  const dialog = page.getByRole('dialog', { name: 'Переход к оплате' })
  const amount = dialog.locator('.edb-checkout-amount')
  const submit = dialog.getByRole('button', { name: 'Перейти к оплате' })
  const yes = dialog.getByRole('radio', { name: 'Да', exact: true })
  const no = dialog.getByRole('radio', { name: 'Нет', exact: true })
  await page.route(`${baseUrl}/api/payments/robokassa/start`, route => route.fulfill({
    status: 204,
  }))
  const openConsult = () => consultCard.getByRole('button', { name: 'Начать прямо сейчас' }).click()
  const evidenceDir = process.env.CHECKOUT_EVIDENCE_DIR
  for (const width of [360, 430, 480, 481, 768, 1440, 1628]) {
    await page.setViewportSize({ width, height: 760 })
    await openConsult()
    assert.equal(await yes.isChecked(), false)
    assert.equal(await no.isChecked(), false)
    assert.equal(await submit.isDisabled(), true)
    assert.match(await amount.textContent(), /16\s800 ₽/)
    const box = await dialog.boundingBox()
    assert(box && box.x >= 0 && box.x + box.width <= width && box.y >= 0 && box.y + box.height <= 760,
      `Checkout dialog does not fit at ${width}px: ${JSON.stringify(box)}`)
    assert.equal(await dialog.evaluate(node => node.scrollWidth > node.clientWidth), false)
    if (evidenceDir) await dialog.screenshot({ path: join(evidenceDir, `checkout-${width}-unselected.png`) })
    await yes.check()
    assert.match(await amount.textContent(), /19\s800 ₽/)
    await dialog.getByRole('textbox', { name: 'Электронная почта' }).fill('test@example.test')
    await dialog.locator('input[name="accept_offer"]').check()
    await dialog.locator('input[name="data_consent"]').check()
    assert.equal(await submit.isEnabled(), true)
    if (evidenceDir) await dialog.screenshot({ path: join(evidenceDir, `checkout-${width}-yes.png`) })
    await no.check()
    assert.match(await amount.textContent(), /16\s800 ₽/)
    if (evidenceDir) await dialog.screenshot({ path: join(evidenceDir, `checkout-${width}-no.png`) })
    await page.keyboard.press('Escape')
  }
  for (const [radio, value] of [[no, 'false'], [yes, 'true']]) {
    await page.evaluate(() => {
      const ready = new Promise(resolve => { window.finishCheckoutJourney = resolve })
      window.EdabalansBrowserJourney = { ready, context: () => '' }
    })
    await openConsult()
    await radio.check()
    const request = page.waitForRequest(req => req.method() === 'POST' && req.url() === `${baseUrl}/api/payments/robokassa/start`)
    await submit.click()
    assert.equal(await yes.isDisabled(), true)
    assert.equal(await no.isDisabled(), true)
    await page.evaluate(() => window.finishCheckoutJourney())
    const form = new URLSearchParams((await request).postData())
    assert.equal(form.get('course_support'), value)
    assert.equal(form.get('price_code'), 'site.masterclass.consult')
    assert.equal(form.get('accept_offer'), 'true')
    assert.equal(form.get('data_consent'), 'true')
    assert.equal(form.has('amount'), false)
    await page.keyboard.press('Escape')
  }
  await page.route('**/api/pricing/site/preview?intensive_offer=support-offer', route => route.fulfill({
    json: { ...consultCatalog, tariffs: consultCatalog.tariffs.map(tariff => ({
      ...tariff, personal_sale_amount: tariff.sale_amount - 1000,
    })) },
  }))
  await page.goto(`${baseUrl}/preview/homepage-release-candidate?intensive_offer=support-offer`, { waitUntil: 'domcontentloaded' })
  await openConsult()
  await yes.check()
  assert.match(await amount.textContent(), /18\s800 ₽/)
  await no.check()
  assert.match(await amount.textContent(), /15\s800 ₽/)
} finally {
  await browser.close()
}
