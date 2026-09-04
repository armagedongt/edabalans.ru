const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.DIRECT_INTENSIVE_BASE_URL || 'http://127.0.0.1:8790'
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 1000 } })
  await page.addInitScript(() => {
    window.__edbGoals = []
    window.ym = (...args) => window.__edbGoals.push(args)
  })
  await page.goto(
    `${baseUrl}/preview/direct-intensive?utm_source=yandex&utm_medium=cpc&utm_campaign=search&utm_content=cat&utm_term=start&utm_id=77&yclid=click-901&ignored=secret`,
    { waitUntil: 'networkidle' },
  )

  const snapshot = await page.evaluate(() => ({
    links: Object.fromEntries([...document.querySelectorAll('[data-edb-channel]')].map(link => [link.dataset.edbChannel, link.href])),
    qr: Object.fromEntries([...document.querySelectorAll('[data-edb-qr]')].map(option => [option.dataset.edbQr, option.querySelector('img').src])),
    failedImages: [...document.images].filter(image => !image.complete || !image.naturalWidth).map(image => image.src),
  }))
  for (const value of [...Object.values(snapshot.links), ...Object.values(snapshot.qr)]) {
    if (!value.includes('utm_id=77') || !value.includes('yclid=click-901') || value.includes('ignored=')) {
      throw new Error(`Bad attribution URL: ${value}`)
    }
  }
  if (!snapshot.links.max.includes('to=max') || !snapshot.qr.max.includes('/qr/max')) throw new Error('MAX routing is incomplete')
  if (snapshot.failedImages.length) throw new Error(`Images failed: ${snapshot.failedImages.join(', ')}`)

  for (const channel of ['telegram', 'max']) {
    const link = page.locator(`[data-edb-channel=${channel}]`)
    await link.evaluate(element => element.addEventListener('click', event => event.preventDefault()))
    await link.click()
  }
  const goals = await page.evaluate(() => window.__edbGoals.map(args => args[2]))
  if (!goals.includes('intensive_telegram_click') || !goals.includes('intensive_max_click')) {
    throw new Error(`Wrong goals: ${goals}`)
  }

  await page.goto(`${baseUrl}/preview/direct-intensive`, { waitUntil: 'networkidle' })
  const restored = await page.locator('[data-edb-channel=max]').getAttribute('href')
  if (!restored.includes('utm_id=77') || !restored.includes('yclid=click-901') || !restored.includes('to=max')) {
    throw new Error(`Session attribution was not restored: ${restored}`)
  }
} finally {
  await browser.close()
}
