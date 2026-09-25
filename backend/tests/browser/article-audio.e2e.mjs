import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const template = await readFile(new URL('../../../content/masterclass/components/article-audio/player.html', import.meta.url), 'utf8')
// A ten-second PCM fixture exercises real browser loading/decoding without private author media.
const wav = Buffer.alloc(44 + 8000 * 2 * 10)
wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8)
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34)
wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40)
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined })
try {
  const page = await browser.newPage({ viewport: { width: 360, height: 800 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('https://audio.test/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/voice.mp3') {
      const range = route.request().headers().range
      const start = Number(range?.match(/bytes=(\d+)-/)?.[1] || 0)
      return route.fulfill({ status: range ? 206 : 200, contentType: 'audio/wav', body: wav.subarray(start),
        headers: { 'Accept-Ranges': 'bytes', 'Content-Length': String(wav.length - start), ...(range ? { 'Content-Range': `bytes ${start}-${wav.length - 1}/${wav.length}` } : {}) } })
    }
    if (path === '/avatar.webp') return route.fulfill({ status: 204 })
    const values = { src: 'https://audio.test/voice.mp3', avatar: 'https://audio.test/avatar.webp', author: 'Сергей Воронцов', duration: '0:10' }
    return route.fulfill({ contentType: 'text/html', body: template.replace(/\{\{(src|avatar|author|duration)\}\}/g, (_, key) => values[key]) })
  })
  await page.goto('https://audio.test/player')
  assert.equal(await page.locator('audio').getAttribute('src'), null)
  assert.equal(await page.locator('audio').evaluate(audio => audio.paused), true)
  await page.locator('[data-voice-speed]').click()
  await page.locator('[data-voice-play]').click()
  await page.waitForFunction(() => document.querySelector('audio').currentTime > 0)
  assert.equal(await page.locator('audio').evaluate(audio => audio.playbackRate), 1.5)
  assert.equal(await page.locator('[data-voice-speed]').textContent(), '×1.5')
  assert.equal(await page.locator('[data-voice-widget]').getAttribute('data-state'), 'playing')
  await page.locator('[data-voice-play]').click()
  assert.equal(await page.locator('audio').evaluate(audio => audio.paused), true)
  assert.equal(await page.locator('[data-voice-widget]').getAttribute('data-state'), 'paused')
  await page.locator('[data-voice-seek]').fill('500')
  await page.waitForFunction(() => !document.querySelector('audio').seeking)
  const afterSeek = await page.locator('audio').evaluate(audio => ({time:audio.currentTime, duration:audio.duration, seekable:audio.seekable.length ? audio.seekable.end(0) : 0, value:document.querySelector('[data-voice-seek]').value}))
  assert.ok(Math.abs(afterSeek.time - 5) < 0.2, JSON.stringify(afterSeek))
  await page.locator('[data-voice-speed]').click()
  assert.equal(await page.locator('audio').evaluate(audio => audio.playbackRate), 2)
  assert.equal(await page.locator('[data-voice-speed]').textContent(), '×2')
  for (const width of [360, 430, 768, 1440]) {
    await page.setViewportSize({ width, height: 800 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  }
  assert.deepEqual(errors, [])
  console.log('PASS audio: lazy load, real playback, pause, seek, pre-play speed, responsive widths')
} finally { await browser.close() }
