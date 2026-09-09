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
  await page.waitForSelector('#edb-direct-intensive-v1 .edb-di-shell')
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
    const expectedAttribution = { alias: 'BMB6Y', landing_variant: 'instead', utm_source: 'yandex', utm_medium: 'cpc', utm_campaign: 'search', utm_content: 'cat', utm_term: 'start', yclid: 'click-901' }
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
    if (!requests.every(body => ['landing_variant', 'yclid', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'].every(key => body[key] === ({ landing_variant: 'instead', yclid: 'click-901', utm_source: 'yandex', utm_medium: 'cpc', utm_campaign: 'search', utm_content: 'cat', utm_term: 'start' })[key]))) throw new Error(`Session attribution was not restored: ${JSON.stringify(requests)}`)
    await context.close()
  }

  for (const channel of ['telegram', 'max']) {
    const { context, page, clickRequests } = await landing({ delay: 120 })
    await page.locator(`[data-edb-channel=${channel}]:visible`).click()
    await page.waitForURL(prepared[channel].button.deep)
    const deadline = Date.now() + 1000
    while (!clickRequests.length && Date.now() < deadline) await pause(10)
    if (clickRequests[0]?.payload !== prepared[channel].button.payload) throw new Error(`Missing ${channel} server click acknowledgement`)
    await context.close()
  }

  {
    const { context, page, events } = await landing({ delay: 1200 })
    await page.locator('[data-edb-channel=telegram]:visible').click()
    const deadline = Date.now() + 1000
    while (!events.some(event => event.payload.event === 'intensive_telegram_click') && Date.now() < deadline) await pause(5)
    const clickEvent = events.find(event => event.payload.event === 'intensive_telegram_click')
    if (!clickEvent) throw new Error('Timed fallback click event was not emitted')
    const elapsed = clickEvent.payload.__browserAt - clickEvent.payload.__clickAt
    // CI scheduling can resume the page noticeably after the 500 ms timer fires;
    // keep a strict lower bound while allowing harmless event-loop delay.
    if (elapsed < 475 || elapsed > 800) throw new Error(`Fallback wait must use the 500 ms timer, got ${elapsed} ms`)
    await page.waitForURL(fallbacks.telegram)
    await context.close()
  }

  {
    const { context, page } = await landing({ api: 'failure' })
    await page.locator('[data-edb-channel=max]:visible').click()
    await page.waitForURL(fallbacks.max)
    await context.close()
  }

  {
    const { context, page } = await landing({ api: 'network' })
    await page.locator('[data-edb-channel=telegram]:visible').click()
    await page.waitForURL(fallbacks.telegram)
    await context.close()
  }

  {
    const { context, page } = await landing({ viewport: { width: 390, height: 844 } })
    const responsive = await page.evaluate(() => {
      const sticky = document.querySelector('.edb-di-sticky-actions')
      const inline = document.querySelector('.edb-di-actions--inline')
      const qr = document.querySelector('.edb-di-qr')
      const inlineTelegramNote = inline.querySelector('.edb-di-note')
      return {
        stickyDisplay: getComputedStyle(sticky).display,
        stickyPosition: getComputedStyle(sticky).position,
        inlineDisplay: getComputedStyle(inline).display,
        qrDisplay: getComputedStyle(qr).display,
        visibleButtons: [...document.querySelectorAll('[data-edb-channel]')].filter(link => link.getClientRects().length > 0).length,
        inlineTelegramNote: inlineTelegramNote?.textContent?.trim(),
      }
    })
    if (responsive.qrDisplay !== 'none') throw new Error(`QR must be absent on mobile, got display=${responsive.qrDisplay}`)
    if (responsive.inlineDisplay !== 'grid') throw new Error(`Inline actions must remain visible on mobile, got display=${responsive.inlineDisplay}`)
    if (responsive.stickyDisplay !== 'none') throw new Error(`Sticky actions must be hidden on this variant: ${JSON.stringify(responsive)}`)
    if (responsive.visibleButtons !== 2) throw new Error(`Expected two visible mobile buttons, got ${responsive.visibleButtons}`)
    if (responsive.inlineTelegramNote !== 'только с VPN') throw new Error(`VPN note must stay below the inline Telegram action: ${JSON.stringify(responsive)}`)
    await context.close()
  }

  {
    const { context, page } = await landing({ viewport: { width: 1200, height: 1000 } })
    const responsive = await page.evaluate(() => ({
      stickyDisplay: getComputedStyle(document.querySelector('.edb-di-sticky-actions')).display,
      inlineDisplay: getComputedStyle(document.querySelector('.edb-di-actions--inline')).display,
      qrDisplay: getComputedStyle(document.querySelector('.edb-di-qr')).display,
    }))
    if (responsive.stickyDisplay !== 'none') throw new Error(`Sticky actions must be hidden on desktop: ${JSON.stringify(responsive)}`)
    if (responsive.inlineDisplay !== 'grid' || responsive.qrDisplay !== 'block') throw new Error(`Desktop actions and QR must remain visible: ${JSON.stringify(responsive)}`)
    await context.close()
  }

  for (const width of [360, 430, 768, 1440]) {
    const { context, page } = await landing({ viewport: { width, height: width < 900 ? 900 : 1000 } })
    const fit = await page.evaluate(() => {
      const root = document.querySelector('#edb-direct-intensive-v1')
      const accent = document.querySelector('.edb-di-hero-accent')
      const rootRect = root.getBoundingClientRect()
      const accentRect = accent?.getBoundingClientRect()
      const legalRect = document.querySelector('.edb-di-legal-line').getBoundingClientRect()
      return {
        rootOverflow: root.scrollWidth - root.clientWidth,
        accentLeft: accentRect ? accentRect.left - rootRect.left : 0,
        accentRight: accentRect ? rootRect.right - accentRect.right : 0,
        accentTextOverflow: accent ? accent.scrollWidth - accent.clientWidth : 0,
        legalLeft: legalRect.left - rootRect.left,
        legalRight: rootRect.right - legalRect.right,
      }
    })
    if (fit.rootOverflow > 1 || fit.accentLeft < -1 || fit.accentRight < -1 || fit.accentTextOverflow > 1 || fit.legalLeft < -1 || fit.legalRight < -1) throw new Error(`Responsive content is clipped at ${width}px: ${JSON.stringify(fit)}`)
    await context.close()
  }

  for (const variant of [
    { id: 'topics', items: 4, boldFragments: 0, marker: 'Научитесь, как с помощью изменения пищевых привычек' },
    { id: 'motivation-hero', items: 0, boldFragments: 0, marker: 'ПОРА МЕНЯТЬ ПОДХОД!' },
    { id: 'instead', items: 5, boldFragments: 6, marker: 'А вместо случайных попыток — понятный порядок действий. Читайте, как всё это сделать в моем бесплатном интенсиве «Последнее похудение»! 👇' },
  ]) {
    const { context, page } = await landing({
      viewport: { width: 360, height: 900 },
      url: `${baseUrl}/preview/direct-intensive?variant=${variant.id}`,
    })
    const state = await page.evaluate(() => ({
      variant: document.querySelector('#edb-direct-intensive-v1').dataset.landingVariant,
      items: document.querySelectorAll('.edb-di-item').length,
      text: document.querySelector('.edb-di-shell').innerText,
      boldFragments: document.querySelectorAll('.edb-di-shell strong').length,
      overflow: document.querySelector('#edb-direct-intensive-v1').scrollWidth - document.querySelector('#edb-direct-intensive-v1').clientWidth,
    }))
    if (state.variant !== variant.id || state.items !== variant.items || !state.text.includes(variant.marker) || state.boldFragments !== variant.boldFragments || state.overflow > 1) {
      throw new Error(`Bad ${variant.id} variant: ${JSON.stringify(state)}`)
    }
    await context.close()
  }

  for (const variant of ['topics', 'motivation-hero', 'instead']) {
    const { context, page } = await landing({
      viewport: { width: 320, height: 900 },
      url: `${baseUrl}/preview/direct-intensive?variant=${variant}`,
    })
    await page.evaluate(() => document.fonts.ready)
    const fit = await page.evaluate(() => {
      const root = document.querySelector('#edb-direct-intensive-v1')
      const heading = document.querySelector('.edb-di-hero-split, .edb-di-hero-stack, .edb-di-opening-heading, .edb-di-body-heading, .edb-di-lead')
      const cta = document.querySelector('.edb-di-cta-lead')
      const arrows = cta?.querySelector('.edb-di-cta-arrows')
      const inlineActions = document.querySelector('.edb-di-actions--inline')
      const stickyActions = document.querySelector('.edb-di-sticky-actions')
      const legal = document.querySelector('.edb-di-legal')
      const checkPairs = [...document.querySelectorAll('.edb-di-list--checks .edb-di-item')].map(item => ({
        prefixTop: item.querySelector('.edb-di-item-prefix').getBoundingClientRect().top,
        resultTop: item.querySelector('.edb-di-item-result').getBoundingClientRect().top,
      }))
      return {
        rootOverflow: root.scrollWidth - root.clientWidth,
        headingAlign: getComputedStyle(heading).textAlign,
        ctaOverflow: cta ? cta.scrollWidth - cta.clientWidth : 0,
        hasSplitArrows: !!arrows,
        splitArrowsLayout: arrows ? getComputedStyle(arrows).gridTemplateColumns : 'none',
        inlineActionsDisplay: getComputedStyle(inlineActions).display,
        stickyActionsDisplay: getComputedStyle(stickyActions).display,
        inlineButtonHeight: inlineActions.querySelector('.edb-di-button').getBoundingClientRect().height,
        inlineButtonRadius: getComputedStyle(inlineActions.querySelector('.edb-di-button')).borderRadius,
        inlineVpnNote: inlineActions.querySelector('.edb-di-note')?.textContent?.trim(),
        inlineButtonVpnNote: inlineActions.querySelector('.edb-di-button-note')?.textContent?.trim(),
        legalBottomGap: window.innerHeight - legal.getBoundingClientRect().bottom,
        firstCheckStaysInline: checkPairs.length ? Math.abs(checkPairs[0].prefixTop - checkPairs[0].resultTop) < 1 : true,
        wrappedCheckCount: checkPairs.filter(pair => pair.resultTop - pair.prefixTop > 1).length,
      }
    })
    const expectsSplitArrows = false
    const expectedHeadingAlignment = 'left'
    if (fit.rootOverflow > 1 || !fit.headingAlign.includes(expectedHeadingAlignment) || fit.ctaOverflow > 1 || expectsSplitArrows !== fit.hasSplitArrows || (expectsSplitArrows && fit.splitArrowsLayout === 'none')) {
      throw new Error(`Variant ${variant} clips or is not left-aligned at 320px: ${JSON.stringify(fit)}`)
    }
    const expectsInlineActions = variant === 'instead' || variant.startsWith('motivation')
    if (expectsInlineActions && (fit.inlineActionsDisplay !== 'grid' || fit.stickyActionsDisplay !== 'none' || fit.inlineButtonHeight !== 54 || fit.inlineButtonRadius !== '13px' || fit.inlineVpnNote !== 'только с VPN' || fit.inlineButtonVpnNote || fit.legalBottomGap > 12)) {
      throw new Error(`Inline actions or footer are misplaced for ${variant}: ${JSON.stringify(fit)}`)
    }
    if (variant.startsWith('instead') && (!fit.firstCheckStaysInline || fit.wrappedCheckCount < 1)) {
      throw new Error(`Instead list must wrap only when its content needs it: ${JSON.stringify(fit)}`)
    }
    if (variant === 'instead' && !(await page.locator('.edb-di-approach-heading, .edb-di-hero-accent').filter({ hasText: 'Надо менять подход!' }).count())) {
      throw new Error('Instead variant must keep the orange approach accent')
    }
    await context.close()
  }

  {
    const { context, page } = await landing({
      viewport: { width: 1000, height: 900 },
      url: `${baseUrl}/preview/direct-intensive?variant=instead`,
    })
    await page.evaluate(() => document.fonts.ready)
    const allChecksStayInline = await page.evaluate(() => [...document.querySelectorAll('.edb-di-list--checks .edb-di-item')].every(item => {
      const prefixTop = item.querySelector('.edb-di-item-prefix').getBoundingClientRect().top
      const resultTop = item.querySelector('.edb-di-item-result').getBoundingClientRect().top
      return Math.abs(prefixTop - resultTop) < 1
    }))
    if (!allChecksStayInline) throw new Error('Instead list must keep every item on one line on desktop')
    await context.close()
  }

  for (const channel of ['telegram', 'max']) {
    const { context, page } = await landing({ viewport: { width: 390, height: 844 } })
    await page.waitForFunction(kind => document.querySelector(`[data-edb-channel="${kind}"]`).href.includes('?start=U'), channel)
    await page.locator(`[data-edb-channel=${channel}]:visible`).click()
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
