import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const staticRoot = new URL('../../app/static/', import.meta.url)
const standard = await readFile(new URL('video-player-development/player-standard-with-contents.html', staticRoot), 'utf8')
const publicPlayer = await readFile(new URL('homepage-preview/vsl-player.html', staticRoot), 'utf8')
const coordinator = await readFile(new URL('homepage-preview/media-coordinator.js', staticRoot), 'utf8')
const origin = 'https://player.test'
const trustedParent = 'https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai'
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined })
let checks = 0

// Network/media decoding are outside these player-control integration tests.
// The DOM, inline player scripts, listeners, focus and postMessage are real.
async function fixture(storage = 'normal') {
  const page = await browser.newPage({ viewport: { width: 430, height: 800 } })
  const errors = []
  const payloads = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(({ storage }) => {
    const states = new WeakMap()
    function state(media) {
      if (!states.has(media)) states.set(media, { time: 0, paused: true, ended: false })
      return states.get(media)
    }
    Object.defineProperties(HTMLMediaElement.prototype, {
      paused: { get() { return state(this).paused } },
      ended: { get() { return state(this).ended } },
      readyState: { get() { return this.getAttribute('src') ? 4 : 0 } },
      duration: { get() { return this.getAttribute('src') ? (this.matches('.mvp__video--preview') && !location.search.includes('intensive-day-1') ? 8 : 100) : NaN } },
      currentTime: {
        get() { return state(this).time },
        set(value) { state(this).time = value; state(this).ended = false; queueMicrotask(() => this.dispatchEvent(new Event('seeked'))) }
      }
    })
    HTMLMediaElement.prototype.play = function () {
      state(this).paused = false
      state(this).ended = false
      this.dispatchEvent(new Event('play'))
      return Promise.resolve()
    }
    HTMLMediaElement.prototype.pause = function () {
      state(this).paused = true
      this.dispatchEvent(new Event('pause'))
    }
    HTMLMediaElement.prototype.load = function () {}
    window.finishMedia = media => {
      state(media).ended = true
      state(media).paused = true
      media.dispatchEvent(new Event('ended'))
    }
    if (storage === 'read-blocked') Storage.prototype.getItem = () => { throw new DOMException('Storage disabled', 'SecurityError') }
    if (storage === 'write-blocked') Storage.prototype.setItem = () => { throw new DOMException('Quota exceeded', 'QuotaExceededError') }
    if (storage === 'corrupt') localStorage.setItem('mvp_analytics_v1:viewer_id', 'not-a-uuid')
  }, { storage })
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.origin === trustedParent && url.pathname === '/parent') {
      return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<script>window.received=[];addEventListener('message',e=>received.push({origin:e.origin,data:e.data}))</script><iframe src="${origin}/public?context=homepage-vsl&parent_origin=${encodeURIComponent(trustedParent)}" allow="autoplay"></iframe>` })
    }
    if (url.origin !== origin) return route.abort()
    if (url.pathname === '/api/public/video-analytics') {
      payloads.push(route.request().postDataJSON())
      return route.fulfill({ json: { ok: true } })
    }
    let html
    if (url.pathname === '/standard') html = standard
    else if (url.pathname === '/public') html = publicPlayer
    else if (url.pathname === '/peer') html = '<script>window.commands=[];addEventListener("message",e=>commands.push(e.data))</script>'
    else if (url.pathname === '/coordinator') html = `<video id="circle" muted></video><audio id="voice"></audio><iframe data-media-player src="${origin}/peer"></iframe><iframe data-media-player src="${origin}/peer"></iframe><script>${coordinator}</script>`
    else return route.fulfill({ status: 404, body: '' })
    return route.fulfill({ contentType: 'text/html; charset=utf-8', body: html })
  })
  return { page, payloads, errors, async close() { assert.deepEqual(errors, []); await page.close(); checks++ } }
}

try {
  const lesson = await fixture()
  const title = '<img src=x onerror="window.chapterInjected=true"> & "test"'
  const query = new URLSearchParams({ src: 'https://media.test/lesson.mp4', poster: 'https://media.test/poster.jpg', chapters: JSON.stringify([['00:00', title], ['00:42', 'Практика']]) })
  await lesson.page.goto(`${origin}/standard?${query}`)
  assert.equal(await lesson.page.locator('.mvp__chapter-title').first().textContent(), title)
  assert.equal(await lesson.page.locator('.mvp__chapters img').count(), 0)
  assert.equal(await lesson.page.evaluate(() => window.chapterInjected), undefined)
  assert.equal(await lesson.page.locator('video').evaluate(video => video.paused), true)
  assert.equal(await lesson.page.locator('video').getAttribute('poster'), 'https://media.test/poster.jpg')
  assert.equal(await lesson.page.locator('.mvp__drawer').evaluate(drawer => drawer.inert), true)
  await lesson.page.getByRole('button', { name: 'Содержание' }).click()
  assert.equal(await lesson.page.getByRole('button', { name: 'Содержание' }).getAttribute('aria-expanded'), 'true')
  assert.equal(await lesson.page.locator('.mvp__close').evaluate(button => document.activeElement === button), true)
  await lesson.page.getByRole('button', { name: '0:42 Практика' }).click()
  assert.equal(await lesson.page.locator('video').evaluate(video => video.currentTime), 42)
  assert.equal(await lesson.page.locator('.mvp__drawer').evaluate(drawer => drawer.inert), true)
  assert.equal(await lesson.page.locator('.mvp__contents-btn').evaluate(button => document.activeElement === button), true)
  await lesson.page.getByRole('button', { name: 'Содержание' }).click()
  await lesson.page.keyboard.press('Escape')
  assert.equal(await lesson.page.getByRole('button', { name: 'Содержание' }).getAttribute('aria-expanded'), 'false')
  assert.equal(await lesson.page.locator('.mvp__contents-btn').evaluate(button => document.activeElement === button), true)
  for (const rate of [1.25, 1.5, 1.75, 2, 1]) {
    await lesson.page.getByRole('button', { name: 'Скорость', exact: true }).click()
    await lesson.page.getByRole('button', { name: `x ${rate}`, exact: true }).last().click()
    assert.equal(await lesson.page.locator('video').evaluate(video => video.playbackRate), rate)
  }
  assert.deepEqual(lesson.payloads, [])
  await lesson.close()

  const empty = await fixture()
  await empty.page.goto(`${origin}/standard?src=https://media.test/lesson.mp4`)
  assert.equal(await empty.page.locator('.mvp__contents-btn').isVisible(), false)
  await empty.close()

  for (const context of ['unknown', 'toString']) {
    const bad = await fixture()
    await bad.page.goto(`${origin}/public?context=${context}`)
    assert.equal(await bad.page.getByRole('alert').textContent(), 'Неизвестный профиль видео')
    assert.equal(await bad.page.locator('video[src]').count(), 0)
    assert.deepEqual(bad.payloads, [])
    await bad.close()
  }

  for (const storage of ['read-blocked', 'write-blocked', 'corrupt']) {
    const playback = await fixture(storage)
    await playback.page.goto(`${origin}/public?context=homepage-vsl`)
    assert.equal(await playback.page.locator('.mvp__video--main').getAttribute('src'), null)
    assert.deepEqual(playback.payloads, [])
    const engagedResponse = playback.page.waitForResponse(response => response.url().endsWith('/api/public/video-analytics'))
    await playback.page.getByRole('button', { name: 'Включить звук' }).click()
    await playback.page.waitForFunction(() => !document.querySelector('.mvp__video--preview').muted)
    await engagedResponse
    assert.equal(playback.payloads[0].event, 'video_engaged')
    assert.match(playback.payloads[0].viewer_id, /^[0-9a-f-]{36}$/i)
    assert.match(playback.payloads[0].session_id, /^[0-9a-f-]{36}$/i)
    assert.equal(playback.payloads[0].page_path, '/public')
    const session = playback.payloads[0].session_id
    await playback.page.locator('.mvp__video--preview').evaluate(video => { video.currentTime = 8; window.finishMedia(video) })
    await playback.page.waitForFunction(() => document.querySelector('.mvp').classList.contains('mvp--main-active'))
    assert.equal(await playback.page.locator('.mvp__video--main').evaluate(video => video.currentTime), 8)
    const exitResponse = playback.page.waitForResponse(response => response.request().postDataJSON()?.event === 'video_exit')
    await playback.page.evaluate(() => dispatchEvent(new Event('pagehide')))
    await exitResponse
    assert.equal(playback.payloads.length, 2)
    assert.ok(playback.payloads.every(payload => payload.session_id === session && payload.viewer_id === playback.payloads[0].viewer_id))
    await playback.close()
  }

  const embedded = await fixture()
  await embedded.page.goto(`${trustedParent}/parent`)
  const embeddedResponse = embedded.page.waitForResponse(response => response.url().endsWith('/api/public/video-analytics'))
  await embedded.page.frameLocator('iframe').getByRole('button', { name: 'Включить звук' }).click()
  await embeddedResponse
  await embedded.page.waitForFunction(() => received.some(message => message.data.type === 'edabalans:video-analytics'))
  const message = await embedded.page.evaluate(() => received.find(message => message.data.type === 'edabalans:video-analytics'))
  assert.equal(message.origin, origin)
  assert.equal(message.data.context, 'homepage-vsl')
  assert.deepEqual(message.data.payload, embedded.payloads[0])
  await embedded.close()

  for (const context of ['homepage-vsl', 'anya-review', 'intensive-day-1']) {
    const profile = await fixture()
    await profile.page.goto(`${origin}/public?context=${context}`)
    const engagedResponse = profile.page.waitForResponse(response => response.url().endsWith('/api/public/video-analytics'))
    await profile.page.getByRole('button', { name: 'Включить звук' }).click()
    await engagedResponse
    const seekable = context === 'intensive-day-1'
    assert.equal(await profile.page.locator('.mvp').evaluate(root => root.classList.contains('mvp--seekable')), seekable)
    assert.equal(await profile.page.locator('.mvp__video--preview').evaluate(video => video.loop), false)
    assert.equal(await profile.page.locator('.mvp__video--main').getAttribute('src') === null, seekable)
    const result = await profile.page.locator('.mvp__progress').evaluate(progress => {
      const video = document.querySelector('.mvp__video--preview')
      video.currentTime = 50
      video.dispatchEvent(new Event('timeupdate'))
      const shown = parseFloat(document.querySelector('.mvp__progress-fill').style.width)
      const rect = progress.getBoundingClientRect()
      progress.dispatchEvent(new MouseEvent('click', { clientX: rect.left + rect.width / 4 }))
      return { shown, time: video.currentTime }
    })
    assert.equal(result.time, seekable ? 25 : 50)
    if (seekable) assert.equal(result.shown, 50)
    else assert.ok(result.shown > 50)
    assert.equal(profile.payloads.some(payload => payload.event === 'video_complete'), false, 'Seeking must not mark the video watched')
    if (seekable) {
      const completed = profile.page.waitForResponse(response => response.request().postDataJSON()?.event === 'video_complete')
      await profile.page.locator('video').first().evaluate(video => {
        video.currentTime = 0
        video.dispatchEvent(new Event('timeupdate'))
        for (let second = 1; second <= 95; second++) {
          video.currentTime = second
          video.dispatchEvent(new Event('timeupdate'))
        }
      })
      await completed
      assert.equal(profile.payloads.filter(payload => payload.event === 'video_complete').length, 1)
    }
    await profile.close()
  }

  const sound = await fixture()
  await sound.page.goto(`${origin}/coordinator`)
  const peers = sound.page.frames().filter(frame => frame.url().includes('/peer'))
  assert.equal(peers.length, 2)
  await sound.page.evaluate(() => {
    const circle = document.querySelector('#circle')
    circle.play()
    circle.muted = false
    circle.dispatchEvent(new Event('volumechange'))
  })
  await peers[0].waitForFunction(() => commands.some(command => command.type === 'edabalans:pause-player'))
  assert.ok((await peers[0].evaluate(() => commands)).some(command => command.type === 'edabalans:pause-player'))
  await sound.page.evaluate(() => document.querySelector('#voice').play())
  assert.equal(await sound.page.locator('#circle').evaluate(video => video.paused), true)
  await peers[1].evaluate(() => parent.postMessage({ type: 'edabalans:player-active' }, 'https://player.test'))
  await sound.page.waitForFunction(() => document.querySelector('#voice').paused)
  await sound.page.evaluate(() => {
    document.querySelector('#voice').play()
    const circle = document.querySelector('#circle')
    circle.muted = false
    circle.volume = 1
    circle.dispatchEvent(new Event('volumechange'))
  })
  assert.equal(await sound.page.locator('#voice').evaluate(media => media.paused), false, 'Paused media must not claim sound focus')
  await sound.page.evaluate(() => {
    const circle = document.querySelector('#circle')
    circle.volume = 0
    circle.play()
    circle.dispatchEvent(new Event('volumechange'))
  })
  assert.equal(await sound.page.locator('#voice').evaluate(media => media.paused), false, 'Zero-volume playback must not claim sound focus')
  await sound.page.evaluate(() => {
    const circle = document.querySelector('#circle')
    circle.muted = true
    circle.volume = 1
    circle.play()
    circle.dispatchEvent(new Event('volumechange'))
  })
  assert.equal(await sound.page.locator('#circle').evaluate(video => video.paused), false, 'Muted loops must not claim sound focus')
  assert.equal(await sound.page.locator('#voice').evaluate(media => media.paused), false, 'Muted loops must not interrupt audible media')
  await sound.close()
  console.log(`Video player integration: ${checks} scenarios passed`)
} finally {
  await browser.close()
}
