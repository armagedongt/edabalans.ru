import assert from 'node:assert/strict'

const playwright = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const { chromium } = playwright.chromium ? playwright : playwright.default
const base = process.env.WEATHER_BASE_URL || 'http://127.0.0.1:8790'
const date = '2026-09-19'
const hours = Array.from({ length: 24 }, (_, index) => `${date}T${String(index).padStart(2, '0')}:00`)

function forecast(point = 0) {
  return {
    hourly: {
      time: hours,
      temperature_2m: hours.map((_, index) => 10 + index / 10),
      apparent_temperature: hours.map((_, index) => 9 + index / 10),
      precipitation: hours.map((_, index) => index === 1 ? point + 0.4 : 0),
      snowfall: hours.map(() => 0),
      wind_speed_10m: hours.map((_, index) => 4 + point + index / 10),
      wind_gusts_10m: hours.map((_, index) => 7 + point + index / 10),
      wind_direction_10m: hours.map((_, index) => 90 + index),
      weather_code: hours.map(() => 3),
      is_day: hours.map(() => 1),
    },
    daily: {
      time: Array.from({ length: 12 }, (_, index) => `2026-09-${String(19 + index).padStart(2, '0')}`),
      temperature_2m_max: Array.from({ length: 12 }, () => 14),
      temperature_2m_min: Array.from({ length: 12 }, () => 8),
      precipitation_sum: Array.from({ length: 12 }, () => 0.4),
    },
  }
}

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  const mapRequestUnits = []
  await page.route('https://api.open-meteo.com/v1/forecast**', async (route) => {
    const request = new URL(route.request().url())
    const isMapRequest = request.searchParams.get('latitude').includes(',')
    if (isMapRequest) mapRequestUnits.push(request.searchParams.get('wind_speed_unit'))
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(isMapRequest ? Array.from({ length: 25 }, (_, index) => forecast(index / 10)) : forecast()),
    })
  })
  await page.goto(`${base}/weather/`, { waitUntil: 'domcontentloaded' })
  await page.locator('.map-cell').first().waitFor()
  assert.equal(await page.locator('.hour[aria-pressed="true"]').count(), 1)
  assert.equal(await page.locator('.hour[aria-pressed="true"] .hour-time').textContent(), '00:00')
  assert.equal(await page.locator('.map-cell').count(), 25)
  assert.ok(mapRequestUnits.includes('ms'))

  await page.locator('.hour').nth(1).click()
  await page.locator('#map-time').getByText('01:00').waitFor()
  await page.locator('.map-grid').getByText('0,4 мм').first().waitFor()
  assert.equal(await page.locator('.hour[aria-pressed="true"] .hour-time').textContent(), '01:00')
  assert.match(await page.locator('.map-grid').innerText(), /0,4 мм/)

  await page.locator('[data-map-mode="wind"]').click()
  await page.locator('.map-cell.wind').first().waitFor()
  assert.match(await page.locator('.map-grid').innerText(), /м\/с/)
  assert.match(await page.locator('.map-grid').innerText(), /км\/ч/)
  assert.match(await page.locator('.map-grid').innerText(), /порывы/)
  console.log('weather: selected hour controls precipitation/wind map passed')
} finally {
  await browser.close()
}
