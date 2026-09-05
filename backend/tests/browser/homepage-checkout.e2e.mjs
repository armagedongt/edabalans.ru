const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8791'
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
  await page.addInitScript(() => {
    window.__cartProducts = []
    window.__cartOpenCount = 0
    window.tcart__addProduct = product => window.__cartProducts.push(product)
    window.tcart__openCart = () => { window.__cartOpenCount += 1 }
  })

  let checkoutBody = null
  await page.route('**/api/pricing/site**', async route => {
    const request = route.request()
    if (request.method() === 'POST') {
      checkoutBody = request.postDataJSON()
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ cart_command: '#order:Самостоятельный · №12345678=2900' }),
      })
      return
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(catalog) })
  })

  await page.goto(`${baseUrl}/preview/homepage-tilda-shell?intensive_offer=offer-test`, {
    waitUntil: 'domcontentloaded',
  })
  const tildaButton = page.locator('[data-price-code="site.masterclass.basic"] .edb-pricing-button')
  await tildaButton.waitFor({ state: 'visible' })
  await tildaButton.click()
  await page.waitForFunction(() => window.__cartOpenCount === 1)

  if (checkoutBody?.price_code !== 'site.masterclass.basic' || checkoutBody?.intensive_offer !== 'offer-test') {
    throw new Error(`Wrong Tilda checkout body: ${JSON.stringify(checkoutBody)}`)
  }
  const cart = await page.evaluate(() => ({ products: window.__cartProducts, opens: window.__cartOpenCount }))
  if (
    cart.opens !== 1
    || cart.products.length !== 1
    || cart.products[0].name !== 'Самостоятельный · №12345678'
    || cart.products[0].price !== 2900
    || cart.products[0].quantity !== 1
  ) {
    throw new Error(`Native Tilda cart was not opened correctly: ${JSON.stringify(cart)}`)
  }
  if (await page.locator('.edb-checkout-modal').isVisible()) {
    throw new Error('Direct Robokassa email modal opened in Tilda embed mode')
  }

  await page.unroute('**/api/pricing/site**')
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
