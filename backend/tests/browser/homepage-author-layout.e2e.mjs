import assert from 'node:assert/strict'

const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8790'
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
})

try {
  const page = await browser.newPage({ viewport: { width: 360, height: 1000 } })
  for (const width of [360, 430, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto(`${baseUrl}/preview/homepage-version/next?rev=author-layout-test`, {
      waitUntil: 'domcontentloaded',
    })

    const geometry = await page.evaluate(() => {
      const title = document.querySelector('.author-section__subheading--challenge')
      const prompt = document.querySelector('.author-section__challenge-copy')
      const image = document.querySelector('.author-section__meme')
      const copy = document.querySelector('.author-section__after-meme')
      if (!title || !prompt || !image || !copy) return null
      const titleRect = title.getBoundingClientRect()
      const promptRect = prompt.getBoundingClientRect()
      const imageRect = image.getBoundingClientRect()
      const copyRect = copy.getBoundingClientRect()
      return {
        positions: [titleRect.top, promptRect.top, imageRect.top, copyRect.top],
        imageBottom: imageRect.bottom,
        copyTop: copyRect.top,
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }
    })

    assert.ok(geometry, `Author block geometry is missing at ${width}px`)
    assert.deepEqual(
      geometry.positions,
      [...geometry.positions].sort((left, right) => left - right),
      `Author block order is incorrect at ${width}px`,
    )
    assert.ok(
      Math.abs(geometry.copyTop - geometry.imageBottom) <= 0.05,
      `Author image has an external bottom gap at ${width}px: ${JSON.stringify(geometry)}`,
    )
    assert.equal(
      geometry.scrollWidth,
      geometry.clientWidth,
      `Author block causes horizontal overflow at ${width}px`,
    )
  }
} finally {
  await browser.close()
}
