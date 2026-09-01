#!/usr/bin/env node

import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const staticRoot = join(repositoryRoot, 'backend', 'app', 'static')
const homepageRoot = join(staticRoot, 'homepage-preview')
const upstreamOrigin = 'https://app.edabalans.ru'
const maximumRequestBody = 1024 * 1024
const portFlag = process.argv.indexOf('--port')
const port = Number(portFlag >= 0 ? process.argv[portFlag + 1] : 8771)

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('Use --port with a valid TCP port')
}

const allowedHosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`])
const allowedOrigins = new Set([`http://127.0.0.1:${port}`, `http://localhost:${port}`])

const homepageAssets = new Set([
  'crying-character.png',
  'final-cta-cat-clock.webp',
  'max-full-colored-dark-official.png',
  'money-bag-ruble-v1.webp',
  'montserrat-cyrillic.woff2',
  'montserrat-latin.woff2',
  'vsl-player.html',
  'weight-loss-after-masterclass.svg',
  'weight-loss-before-masterclass.svg',
])

const mimeTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml; charset=utf-8'],
  ['.webp', 'image/webp'],
  ['.woff2', 'font/woff2'],
])

function extension(path) {
  const index = path.lastIndexOf('.')
  return index < 0 ? '' : path.slice(index)
}

async function sendFile(response, path) {
  const file = await stat(path)
  response.writeHead(200, {
    'Content-Type': mimeTypes.get(extension(path)) || 'application/octet-stream',
    'Content-Length': file.size,
    'Cache-Control': 'no-cache',
    'X-Robots-Tag': 'noindex, nofollow',
  })
  createReadStream(path).pipe(response)
}

async function proxyCanonicalApi(request, response, url) {
  const allowedMethod = url.pathname === '/api/pricing/site/preview'
    || url.pathname.startsWith('/api/public-site/content/')
    ? 'GET'
    : 'POST'
  if (request.method !== allowedMethod) {
    response.writeHead(405, {
      'Content-Type': 'application/json; charset=utf-8',
      Allow: allowedMethod,
    })
    response.end(JSON.stringify({ detail: `Use ${allowedMethod} for this preview endpoint` }))
    return
  }
  const target = new URL(`${url.pathname}${url.search}`, upstreamOrigin)
  const headers = {
    Accept: request.headers.accept || 'application/json',
    Origin: upstreamOrigin,
  }
  if (request.headers['content-type']) headers['Content-Type'] = request.headers['content-type']
  const chunks = []
  let requestSize = 0
  for await (const chunk of request) {
    requestSize += chunk.length
    if (requestSize > maximumRequestBody) {
      response.writeHead(413, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({ detail: 'Preview request body is too large' }))
      return
    }
    chunks.push(chunk)
  }
  const body = chunks.length ? Buffer.concat(chunks) : undefined
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body,
    redirect: 'manual',
  })
  const payload = Buffer.from(await upstream.arrayBuffer())
  response.writeHead(upstream.status, {
    'Content-Type': upstream.headers.get('content-type') || 'application/octet-stream',
    'Content-Length': payload.length,
    'Cache-Control': 'no-store',
  })
  response.end(payload)
}

function isCanonicalApi(pathname) {
  return pathname === '/api/pricing/site/preview'
    || pathname === '/api/pricing/site/preview-checkout'
    || pathname === '/api/public/video-analytics'
    || pathname.startsWith('/api/public-site/content/')
}

const server = createServer(async (request, response) => {
  try {
    const requestHost = String(request.headers.host || '').toLowerCase()
    const requestOrigin = request.headers.origin
    if (!allowedHosts.has(requestHost)
      || (requestOrigin && !allowedOrigins.has(requestOrigin.toLowerCase()))) {
      response.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({ detail: 'Preview accepts only same-origin loopback requests' }))
      return
    }
    const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`)
    if (url.pathname === '/' || url.pathname === '/preview/homepage-mobile/') {
      response.writeHead(302, { Location: '/preview/homepage-mobile' })
      response.end()
      return
    }
    if (url.pathname === '/preview/homepage-mobile') {
      await sendFile(response, join(homepageRoot, 'mobile.html'))
      return
    }
    if (url.pathname === '/site-footer.js') {
      await sendFile(response, join(staticRoot, 'site-footer.js'))
      return
    }
    if (url.pathname.startsWith('/preview/homepage-mobile/')) {
      const assetName = decodeURIComponent(url.pathname.slice('/preview/homepage-mobile/'.length))
      if (!homepageAssets.has(assetName)) {
        response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
        response.end('Preview asset not found')
        return
      }
      await sendFile(response, join(homepageRoot, assetName))
      return
    }
    if (isCanonicalApi(url.pathname)) {
      await proxyCanonicalApi(request, response, url)
      return
    }
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
    response.end('Not found')
  } catch (error) {
    response.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
    response.end(JSON.stringify({ detail: 'Preview upstream unavailable', error: error.message }))
  }
})

server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`Homepage preview: http://127.0.0.1:${port}/preview/homepage-mobile\n`)
})
