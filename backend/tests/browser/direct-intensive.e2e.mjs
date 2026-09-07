const playwrightModule = process.env.PLAYWRIGHT_MODULE_URL || 'playwright'
const { chromium } = await import(playwrightModule)

const baseUrl = process.env.DIRECT_INTENSIVE_BASE_URL || 'http://127.0.0.1:8790'
const landingUrl = `${baseUrl}/preview/direct-intensive?utm_source=yandex&utm_medium=cpc&utm_campaign=search&utm_content=cat&utm_term=start&utm_id=77&yclid=click-901&ignored=secret`
const fallbacks = {
  telegram: 'https://t.me/Fitness_Talks_bot?start=BMB6Y',
  max: 'https://max.ru/id230409966750_bot?start=BMB6Y',
}
const prepared = {
  telegram: {
    button: { deep: 'https://t.me/Fitness_Talks_bot?start=UtgButton123', payload: 'UtgButton123' },
    qr: { deep: 'https://t.me/Fitness_Talks_bot?start=UtgQr123', payload: 'UtgQr123', qr: 'https://edabalans.ru/q/UtgQr123' },
  },
  max: {
    button: { deep: 'https://max.ru/id230409966750_bot?start=UmaxButton123', payload: 'UmaxButton123' },
    qr: { deep: 'https://max.ru/id230409966750_bot?start=UmaxQr123', payload: 'UmaxQr123', qr: 'https://edabalans.ru/q/UmaxQr123' },
  },
}
const browser = await chromium.launch({ headless: true })
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))

async function landing({ api = 'success', delay = 0, viewport = { width: 1200, height: 1000 }, url = landingUrl } = {}) {
  const context = await browser.newContext({ viewport })
  const page = await context.newPage()
  const requests = []
  const clickRequests = []
  const events = []
  await page.exposeFunction('__edbRecordEvent', payload => events.push({ payload, at: Date.now() }))
  await page.addInitScript(() => {
    window.__edbGoals = []
    window.__edbQrPayloads = []
    window.__edbQrRendered = {}
    window.ym = (...args) => window.__edbGoals.push(args)
    document.addEventListener('click', event => {
      if (event.target.closest('[data-edb-channel]')) window.__edbClickStarted = performance.now()
    }, true)
    window.dataLayer = { push: payload => window.__edbRecordEvent({ ...payload, __browserAt: performance.now(), __clickAt: window.__edbClickStarted }) }
    let qrFactory
    Object.defineProperty(window, 'qrcode', {
      configurable: true,
      get: () => qrFactory,
      set: value => {
        qrFactory = new Proxy(value, {
          apply(target, thisArg, args) {
            const code = Reflect.apply(target, thisArg, args)
            const addData = code.addData
            code.addData = data => {
              code.__edbPayload = data
              window.__edbQrPayloads.push(data)
              return addData.call(code, data)
            }
            const createSvgTag = code.createSvgTag
            code.createSvgTag = (...svgArgs) => {
              const svg = createSvgTag.apply(code, svgArgs)
              window.__edbQrRendered[code.__edbPayload] = svg
              return svg
            }
            return code
          },
          get: (target, property) => Reflect.get(target, property),
          set: (target, property, next) => Reflect.set(target, property, next),
        })
      },
    })
  })
  await page.route('https://edabalans.ru/api/messaging/start-link', async route => {
    const request = route.request()
    const origin = request.headers().origin || baseUrl
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'content-type' } })
      return
    }
    const body = request.postDataJSON()
    requests.push(body)
    if (delay) await pause(delay)
    if (api === 'network') {
      await route.abort('failed')
      return
    }
    if (api === 'failure') {
      await route.fulfill({ status: 503, headers: { 'Access-Control-Allow-Origin': origin }, body: '{"detail":"unavailable"}' })
      return
    }
    const channel = body.messenger === 'tg' ? 'telegram' : 'max'
    const issued = prepared[channel][body.entry]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': origin },
      body: JSON.stringify({ messenger: body.messenger, entry: body.entry, deep_link: issued.deep, fallback_url: fallbacks[channel], payload: issued.payload, click_url: 'https://edabalans.ru/api/messaging/start-link/click', qr_url: issued.qr || `https://edabalans.ru/q/${issued.payload}`, expires_in_seconds: 604800 }),
    })
  })
  await page.route('https://edabalans.ru/api/messaging/start-link/click', async route => {
    clickRequests.push(route.request().postDataJSON())
    await route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': baseUrl } })
  })
  await page.route('https://t.me/**', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<title>Telegram direct</title>' }))
  await page.route('https://max.ru/**', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<title>MAX direct</title>' }))
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  return { context, page, requests, clickRequests, events }
}

async function waitForRequests(requests) {
  const deadline = Date.now() + 3000
  while (requests.length < 4 && Date.now() < deadline) await pause(20)
  if (requests.length !== 4) throw new Error(`Expected four prefetch calls, got ${requests.length}`)
}

try {
  {
    const { context, page, requests } = await landing()
    await waitForRequests(requests)
    await page.waitForFunction(() => [...document.querySelectorAll('[data-edb-channel]')].every(link => link.href.includes('?start=U')))
    const expectedAttribution = { alias: 'BMB6Y', utm_source: 'yandex', utm_medium: 'cpc', utm_campaign: 'search', utm_content: 'cat', utm_term: 'start', yclid: 'click-901' }
    const byKey = Object.fromEntries(requests.map(body => [`${body.messenger}:${body.entry}`, body]))
    for (const messenger of ['tg', 'max']) for (const entry of ['button', 'qr']) {
      const expected = { messenger, entry, ...expectedAttribution }
      if (JSON.stringify(byKey[`${messenger}:${entry}`]) !== JSON.stringify(expected)) throw new Error(`Bad ${messenger}:${entry} request: ${JSON.stringify(byKey[`${messenger}:${entry}`])}`)
    }

    const snapshot = await page.evaluate(() => ({
      links: Object.fromEntries([...document.querySelectorAll('[data-edb-channel]')].map(link => [link.dataset.edbChannel, link.href])),
      encodedQrPayloads: window.__edbQrPayloads,
      renderedQr: window.__edbQrRendered,
      qr: Object.fromEntries([...document.querySelectorAll('[data-edb-qr]')].map(option => {
        const image = option.querySelector('img')
        return [option.dataset.edbQr, { destination: image.dataset.edbDestination, src: image.src }]
      })),
    }))
    for (const channel of ['telegram', 'max']) {
      if (snapshot.links[channel] !== prepared[channel].button.deep) throw new Error(`Wrong ${channel} link`)
      if (snapshot.qr[channel].destination !== prepared[channel].qr.qr) throw new Error(`Wrong ${channel} QR destination`)
      if (!snapshot.qr[channel].src.startsWith('data:image/svg+xml')) throw new Error(`Wrong ${channel} QR image`)
      const expectedQr = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(snapshot.renderedQr[prepared[channel].qr.qr])}`
      if (snapshot.qr[channel].src !== expectedQr) throw new Error(`${channel} image does not contain its prepared QR`)
    }
    for (const channel of ['telegram', 'max']) if (!snapshot.encodedQrPayloads.includes(prepared[channel].qr.qr)) throw new Error(`QR did not encode tracked ${channel} URL`)
    await page.locator('[data-edb-qr=max]').click()
    if (await page.locator('[data-edb-qr=max]').getAttribute('aria-selected') !== 'true') throw new Error('MAX QR was not selected')

    requests.length = 0
    await page.goto(`${baseUrl}/preview/direct-intensive`, { waitUntil: 'domcontentloaded' })
    await waitForRequests(requests)
    if (!requests.every(body => ['yclid', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'].every(key => body[key] === ({ yclid: 'click-901', utm_source: 'yandex', utm_medium: 'cpc', utm_campaign: 'search', utm_content: 'cat', utm_term: 'start' })[key]))) throw new Error(`Session attribution was not restored: ${JSON.stringify(requests)}`)
    await context.close()
  }

  for (const channel of ['telegram', 'max']) {
    const { context, page, clickRequests } = await landing({ delay: 120 })
    await page.locator(`[data-edb-channel=${channel}]`).click()
    await page.waitForURL(prepared[channel].button.deep)
    const deadline = Date.now() + 1000
    while (!clickRequests.length && Date.now() < deadline) await pause(10)
    if (clickRequests[0]?.payload !== prepared[channel].button.payload) throw new Error(`Missing ${channel} server click acknowledgement`)
    await context.close()
  }

  {
    const { context, page, events } = await landing({ delay: 1200 })
    await page.locator('[data-edb-channel=telegram]').click()
    const deadline = Date.now() + 1000
    while (!events.some(event => event.payload.event === 'intensive_telegram_click') && Date.now() < deadline) await pause(5)
    const clickEvent = events.find(event => event.payload.event === 'intensive_telegram_click')
    if (!clickEvent) throw new Error('Timed fallback click event was not emitted')
    const elapsed = clickEvent.payload.__browserAt - clickEvent.payload.__clickAt
    if (elapsed < 475 || elapsed > 525) throw new Error(`Fallback wait must stay at or below 500 ms plus event-loop overhead, got ${elapsed} ms`)
    await page.waitForURL(fallbacks.telegram)
    await context.close()
  }

  {
    const { context, page } = await landing({ api: 'failure' })
    await page.locator('[data-edb-channel=max]').click()
    await page.waitForURL(fallbacks.max)
    await context.close()
  }

  {
    const { context, page } = await landing({ api: 'network' })
    await page.locator('[data-edb-channel=telegram]').click()
    await page.waitForURL(fallbacks.telegram)
    await context.close()
  }

  {
    const { context, page } = await landing({ viewport: { width: 390, height: 844 } })
    const display = await page.locator('.edb-di-qr').evaluate(element => getComputedStyle(element).display)
    if (display !== 'none') throw new Error(`QR must be absent on mobile, got display=${display}`)
    await context.close()
  }

  for (const channel of ['telegram', 'max']) {
    const { context, page } = await landing({ viewport: { width: 390, height: 844 } })
    await page.waitForFunction(kind => document.querySelector(`[data-edb-channel="${kind}"]`).href.includes('?start=U'), channel)
    await page.locator(`[data-edb-channel=${channel}]`).click()
    await page.waitForURL(prepared[channel].button.deep)
    await context.close()
  }

  {
    const longYclid = 'y'.repeat(600)
    const { context, requests } = await landing({ url: `${baseUrl}/preview/direct-intensive?utm_source=yandex&yclid=${longYclid}` })
    await waitForRequests(requests)
    if (!requests.every(body => body.yclid.length === 500)) throw new Error('Attribution values must be truncated to 500 characters')
    await context.close()
  }
} finally {
  await browser.close()
}
