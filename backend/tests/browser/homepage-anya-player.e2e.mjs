const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8790'
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
})

try {
  const page = await browser.newPage({ viewport: { width: 360, height: 900 } })
  for (const width of [360, 430, 599, 600, 601, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`${baseUrl}/preview/homepage-mobile`, { waitUntil: 'domcontentloaded' })

    const geometry = await page.evaluate(() => {
      const hero = document.querySelector('[data-homepage-block="hero-video"] .site-player__mask')?.getBoundingClientRect()
      const anya = document.querySelector('[data-homepage-block="anya-slider"] .site-player__mask')?.getBoundingClientRect()
      if (!hero || !anya) return null
      return {
        heroHeight: hero.height,
        anyaHeight: anya.height,
        anyaRatio: anya.width / anya.height,
      }
    })

    if (!geometry) throw new Error(`Player geometry is missing at ${width}px`)
    if (Math.abs(geometry.anyaHeight - geometry.heroHeight) > 0.05) {
      throw new Error(`Anya and main player heights differ at ${width}px: ${JSON.stringify(geometry)}`)
    }
    if (Math.abs(geometry.anyaRatio - (1080 / 1914)) > 0.0001) {
      throw new Error(`Anya frame is not 1080:1914 at ${width}px: ${JSON.stringify(geometry)}`)
    }
  }
} finally {
  await browser.close()
}
