import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL
  ? ((await import(process.env.PLAYWRIGHT_MODULE_URL)).default || await import(process.env.PLAYWRIGHT_MODULE_URL))
  : require('playwright')
const { chromium } = playwrightModule

const baseUrl = process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8790'
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
})

try {
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } })
  let state = {
    identified: true,
    platform: 'telegram',
    opened_days: [1],
    assignment_days: [1],
    current_day: 2,
    unlocked_days: [1, 2],
    unlock_at: { '3': '2099-01-01T00:00:00Z' },
    offer: null,
  }
  await page.addInitScript(() => { window.ym = () => {} })
  await page.route(`${baseUrl}/api/intensive/state`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(state),
  }))

  for (const width of [360, 430, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`${baseUrl}/intensive?visual-test=available-${width}`, { waitUntil: 'domcontentloaded' })
    await page.locator('.day-card.is-next-open').waitFor({ state: 'visible' })
    if (!await page.locator('.day-card[data-day="1"].is-read').count() || await page.locator('.day-card[data-day="1"] [data-day-status]').innerText() !== 'Прочитано') {
      throw new Error(`The completed day has no compact read marker at ${width}px`)
    }
    if (await page.locator('.day-card[data-day="2"] [data-day-status]').count() !== 0) {
      throw new Error(`The next unread open day has unrequested copy at ${width}px`)
    }
    if (!await page.locator('.day-card[data-day="3"]').evaluate(card => card.classList.contains('is-next-locked'))) {
      throw new Error(`The nearest closed day is not visually promoted at ${width}px`)
    }
    if (await page.locator('.day-card[data-day="3"] .day-card__status').innerText() !== 'Сначала прочитайте предыдущую часть') {
      throw new Error(`A locked later day does not explain the prerequisite at ${width}px`)
    }
    if (await page.locator('.day-card[data-day="4"] [data-day-status]').count() !== 0) {
      throw new Error(`A farther locked day is not quiet at ${width}px`)
    }
    const emphasis = await page.evaluate(() => {
      const open = document.querySelector('.day-card[data-day="2"]')
      const locked = document.querySelector('.day-card[data-day="3"]')
      return {
        openShadow: getComputedStyle(open).boxShadow,
        lockedBorder: getComputedStyle(locked).borderTopWidth,
        lockedMinHeight: Number.parseFloat(getComputedStyle(locked).minHeight),
      }
    })
    if (emphasis.openShadow === 'none' || emphasis.lockedBorder !== '1px' || emphasis.lockedMinHeight < 146) {
      throw new Error(`The progress-card emphasis is missing at ${width}px: ${JSON.stringify(emphasis)}`)
    }
    const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    if (overflows) throw new Error(`The menu overflows horizontally at ${width}px`)
  }

  await page.setViewportSize({ width: 360, height: 900 })

  const timerUnlockAt = new Date(Date.now() + 5000).toISOString()
  state = {
    ...state,
    opened_days: [1, 2],
    assignment_days: [1, 2],
    current_day: 3,
    unlock_at: { '3': timerUnlockAt },
  }
  await page.goto(`${baseUrl}/intensive?visual-test=timer`, { waitUntil: 'domcontentloaded' })
  await page.locator('.day-card.is-next-locked').waitFor({ state: 'visible' })
  const timerText = await page.locator('.day-card[data-day="3"] .day-card__status').innerText()
  if (!/^Следующая часть откроется через\s+\d{2}:\d{2}:\d{2}$/.test(timerText)) {
    throw new Error(`The closed day timer is missing: ${timerText}`)
  }
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) {
    throw new Error('The timer status overflows at 360px')
  }
  const legacyLockedLabel = await page.locator('.day-card[data-day="3"]').evaluate(card => (
    getComputedStyle(card, '::after').content
  ))
  if (legacyLockedLabel !== 'none') {
    throw new Error(`The highlighted locked day has conflicting copy: ${legacyLockedLabel}`)
  }
  setTimeout(() => {
    state = {
      ...state,
      unlocked_days: [1, 2, 3],
    }
  }, 1500)
  await page.locator('.day-card[data-day="3"].is-next-open').waitFor({ state: 'visible' })
  await page.locator('.day-card[data-day="3"]').click()
  await page.waitForURL(`${baseUrl}/intensive/day-3`)

  state = {
    ...state,
    opened_days: [1],
    assignment_days: [],
    current_day: 2,
    unlocked_days: [1],
    unlock_at: {},
  }
  await page.goto(`${baseUrl}/intensive?visual-test=prerequisite`, { waitUntil: 'domcontentloaded' })
  await page.locator('.day-card.is-next-locked').waitFor({ state: 'visible' })
  const prerequisite = await page.locator('.day-card[data-day="2"] .day-card__status').innerText()
  if (prerequisite !== 'Сначала прочитайте предыдущую часть') {
    throw new Error(`The blocked-day prerequisite is unclear: ${prerequisite}`)
  }
} finally {
  await browser.close()
}
