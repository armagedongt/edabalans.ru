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
    body: `<!doctype html><html><head></head><body>
      <div class="t-rec"><div class="t123__centeredContainer">
        <div data-edabalans-homepage></div>
      </div></div>
      <script src="${appUrl}/homepage.js"></script>
    </body></html>`,
  }))

  await page.route(`${appUrl}/**`, async route => {
    const request = route.request()
    const url = new URL(request.url())
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
    if (url.pathname === '/api/payments/robokassa/checkout' && request.method() === 'POST') {
      checkoutBody = request.postDataJSON()
      await route.fulfill({
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify({
          payment_form: {
            action: 'https://auth.robokassa.ru/Merchant/Index.aspx',
            fields: { MerchantLogin: 'test-shop', OutSum: '2900', InvId: '123' },
          },
        }),
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
  await page.goto(tildaUrl, { waitUntil: 'domcontentloaded' })
  const tildaButton = page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button')
  await tildaButton.waitFor({ state: 'visible' })
  const checkoutEndpoint = await page.locator('#edb-pricing-neurozeh-v1').getAttribute('data-checkout-endpoint')
  if (checkoutEndpoint !== `${appUrl}/api/payments/robokassa/checkout`) {
    throw new Error(`Loader did not rewrite cross-origin checkout endpoint: ${checkoutEndpoint}`)
  }
  await tildaButton.click()
  if (!(await page.locator('.edb-checkout-modal').isVisible())) {
    throw new Error('Direct Robokassa email modal did not open in Tilda embed mode')
  }
  await page.locator('.edb-checkout-email').fill('test@example.ru')
  await page.locator('.edb-checkout-consent').check()
  const paymentNavigation = page.waitForURL('https://auth.robokassa.ru/**')
  await page.locator('.edb-checkout-form').evaluate(form => form.requestSubmit())
  await paymentNavigation

  if (checkoutBody?.price_code !== 'site.masterclass.basic' || checkoutBody?.intensive_offer !== 'offer-test') {
    throw new Error(`Stored intensive offer was not restored in Tilda checkout: ${JSON.stringify(checkoutBody)}`)
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

  await page.route('**/api/pricing/site/preview**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(catalog),
  }))
  await page.goto(`${baseUrl}/preview/homepage-mobile`, { waitUntil: 'domcontentloaded' })
  const standaloneButton = page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button')
  await standaloneButton.waitFor({ state: 'visible' })
  await standaloneButton.click()
  if (!(await page.locator('.edb-checkout-modal').isVisible())) {
    throw new Error('Direct Robokassa email modal did not open in standalone mode')
  }
} finally {
  await browser.close()
}
