const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8790'
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
})

try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } })
  let offerRequests = 0
  await page.route(`${baseUrl}/api/intensive/state`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      identified: true,
      platform: 'telegram',
      opened_days: [1, 2, 3, 4],
      assignment_days: [1, 2, 3],
      current_day: 4,
      unlocked_days: [1, 2, 3, 4],
      unlock_at: {},
      offer: null,
    }),
  }))
  await page.route(`${baseUrl}/api/intensive/offer-token`, route => {
    offerRequests += 1
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        offer_id: 'intensive-day4-1000',
        discount_amount: 1000,
        expires_at: '2099-01-01T00:00:00Z',
        token: 'offer-scroll-test',
      }),
    })
  })
  await page.route(`${baseUrl}/api/intensive/events`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ok: true}),
  }))

  await page.goto(`${baseUrl}/intensive/day-4`, { waitUntil: 'domcontentloaded' })
  const cta = page.locator('.masterclass-cta')
  await cta.waitFor({state: 'attached'})
  await page.waitForTimeout(250)
  if (offerRequests !== 0) {
    throw new Error(`Offer started before the day-four CTA entered the viewport: ${offerRequests}`)
  }

  await cta.scrollIntoViewIfNeeded()
  await page.waitForFunction(() => document.querySelector('.masterclass-cta')?.href.includes('intensive_offer=offer-scroll-test'))
  if (offerRequests !== 1) {
    throw new Error(`Offer endpoint called an unexpected number of times: ${offerRequests}`)
  }
  const href = await cta.getAttribute('href')
  if (!href?.includes('/mk1?intensive_offer=offer-scroll-test#masterclass')) {
    throw new Error(`Day-four CTA does not target discounted /mk1: ${href}`)
  }
} finally {
  await browser.close()
}
