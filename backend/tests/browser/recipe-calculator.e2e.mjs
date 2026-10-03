import assert from 'node:assert/strict'
import { readFile, mkdir, mkdtemp, writeFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import vm from 'node:vm'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const html = await readFile(new URL('../../app/static/apps/recipes.html', import.meta.url), 'utf8')
const vectors = JSON.parse(await readFile(new URL('./recipe-calculator-vectors.json', import.meta.url), 'utf8'))
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1])
scripts.forEach(script => new vm.Script(script))
const sandbox = { window: {} }; vm.runInNewContext(scripts[0], sandbox)
const math = sandbox.window.EdabalansRecipeMath
const keys = Array.from(math.keys)
function sourceFromVector(row) {
  return { exact: { unit: 'per100_milli', ...Object.fromEntries(keys.map((k, i) => [k, { numerator: row[i + 2], denominator: '1' }])) } }
}
for (const vector of vectors) {
  const rows = vector.rows.map(row => ({ source: sourceFromVector(row), weight: row[1] }))
  const result = math.calculate(rows, vector.yield, vector.portion)
  for (const kind of ['all', 'per100', 'perPortion']) {
    assert.deepEqual(keys.map(k => math.format(result[kind][k], k).replace(',', '.')), vector.expected[kind], vector.name + ' ' + kind)
  }
}
const periodic = sourceFromVector(['', '', '100000', '0', '0', '0'])
periodic.exact.protein.denominator = '3'
const direct = sourceFromVector(['', '', '1000', '0', '0', '0'])
const nested = math.calculate([{ source: periodic, weight: '3' }, { source: direct, weight: '100' }], '103', '103')
assert.equal(math.compare(nested.values[0].protein, nested.values[1].protein), 0)
assert.deepEqual(Array.from(nested.ranks, row => row.protein), [1, 1])
assert.equal(math.format(nested.all.protein, 'protein'), '2,0')
const rankColumns = [['100000', '100000', '99999', '50000', '0', '25000'], ['300000', '0', '200000', '500000', '100000', '500000'], ['0', '500000', '200000', '200000', '100000', '400000'], ['200000', '0', '700000', '300000', '700000', '100000']]
const rankRows = rankColumns[0].map((_, i) => Object.fromEntries(keys.map((k, j) => [k, math.fraction(rankColumns[j][i], 100000n)])))
const ranking = math.ranks(rankRows)
for (const [i, expected] of [[0, [1, 1, 2, 3, null, null]], [1, [2, null, 3, 1, null, 1]], [2, [null, 1, 3, 3, null, 2]], [3, [3, null, 1, 2, 1, null]]]) {
  assert.deepEqual(Array.from(ranking, row => row[keys[i]]), expected)
}
assert.equal(math.weight('99999'), 99999n); assert.equal(math.weight('100000'), null)
assert.equal(math.nutrition('12,345', 100), 12345n); assert.equal(math.nutrition('1.0001', 100), null)

const outRoot = process.env.QA_OUT || join(tmpdir(), 'recipe-calculator-browser')
await mkdir(outRoot, { recursive: true }); const out = await mkdtemp(join(outRoot, 'run-'))
let serverProcess, url = process.env.RECIPE_TEST_URL
if (!url) {
  serverProcess = spawn(process.env.PYTHON_EXE || 'python', [new URL('./recipe-calculator-server.py', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1'), join(out, 'browser.sqlite')], { windowsHide: true, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } })
  url = await new Promise((resolve, reject) => {
    let buffer = ''; const timer = setTimeout(() => reject(Error('Synthetic server did not start')), 20000)
    serverProcess.stdout.on('data', chunk => { buffer += chunk; const match = buffer.match(/RECIPE_TEST_URL=(http:\/\/127\.0\.0\.1:\d+)/); if (match) { clearTimeout(timer); resolve(match[1]) } })
    serverProcess.on('exit', code => { clearTimeout(timer); reject(Error('Synthetic server exited: ' + code)) })
    serverProcess.stderr.on('data', chunk => process.stderr.write(chunk))
  })
}
assert.match(url, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/)
for (let attempt = 0; ; attempt++) {
  try { if ((await fetch(url + '/health')).ok) break } catch {}
  if (attempt >= 40) throw Error('Synthetic API not ready')
  await new Promise(resolve => setTimeout(resolve, 100))
}
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 360, height: 900 }, reducedMotion: 'reduce' })
const page = await context.newPage(), errors = [], checks = []
page.on('pageerror', error => errors.push(error.message))
await page.route(/^https:\/\/(telegram\.org|st\.max\.ru)\//, route => route.fulfill({ contentType: 'application/javascript', body: '' }))
async function request(path, data, method) {
  if (path === '/api/account-auth/login') {
    const response = await page.request.post(url + path, { data })
    assert.ok(response.ok(), await response.text()); return response.json()
  }
  const response = await page.evaluate(async ({ path, data, method }) => {
    const result = await fetch(path, { method: method || (data ? 'POST' : 'GET'), credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...(data ? { body: JSON.stringify(data) } : {}) })
    return { ok: result.ok, body: await result.json() }
  }, { path, data, method })
  assert.ok(response.ok, JSON.stringify(response.body)); assert.equal(response.body.ok, true); return response.body
}
async function setTitle(text) { const input=page.getByRole('textbox', { name: 'Название рецепта', exact: true }); if(!await input.isVisible()) await page.getByRole('button', { name: 'Редактировать название рецепта', exact:true }).click(); await input.fill(text); await input.press('Enter') }
async function status(text) { await page.locator('.recipe-status-text').filter({ hasText: text }).waitFor() }
async function capture(name) { await page.screenshot({ path: join(out, name + '.png'), fullPage: !await page.locator('.recipe-library').isVisible() }) }
async function responsiveState(name) {
  for (const width of [430, 768, 1440]) { await page.setViewportSize({ width, height: 900 }); await page.waitForTimeout(50); await geometry(width); await capture(name + '-' + width) }
  await page.setViewportSize({ width: 360, height: 900 })
}
async function fourWidthState(name) {
  await page.setViewportSize({ width: 360, height: 900 }); await page.waitForTimeout(50); await geometry(360); await capture(name + '-360')
  await responsiveState(name)
}
const caesarContributions = [
  ['2,3', '0,3', '4,5', '35'], ['45,0', '12,5', '0,0', '293'], ['1,6', '0,2', '5,6', '30'],
  ['2,8', '0,0', '1,3', '16'], ['1,4', '0,0', '0,7', '8'], ['1,5', '0,2', '1,0', '11'],
  ['5,3', '7,9', '33,0', '223'], ['0,0', '10,0', '5,4', '112'], ['9,3', '7,0', '0,0', '120'],
]
const caesarRanks = [
  [null, null, null, null], [1, 1, null, 1], [null, null, 2, null],
  [null, null, null, null], [null, null, null, null], [null, null, null, null],
  [3, 3, 1, 2], [null, 2, 3, null], [2, null, null, 3],
]
async function assertCaesarRows() {
  for (const [i, [name, weight]] of vectors[0].rows.entries()) {
    assert.equal(await row(i).locator('.recipe-name-cell .recipe-edit').innerText(), name, 'source name/order at ' + i)
    assert.equal(await row(i).locator('.recipe-weight-cell button').innerText(), weight)
    assert.deepEqual(await row(i).locator('.recipe-number[data-nutrient]').allTextContents(), caesarContributions[i], 'actual ingredient contribution at ' + i)
    for (const [j, key] of keys.entries()) {
      assert.equal(await row(i).locator('.recipe-number[data-nutrient=' + key + ']').getAttribute('data-rank'), caesarRanks[i][j] ? String(caesarRanks[i][j]) : null, 'independent live/saved rank at ' + i + '/' + key)
    }
  }
}
function row(index) { return page.locator('.recipe-row').nth(index) }
async function choose(index, name, weight) {
  if (!await row(index).isVisible()) await page.getByRole('button', { name: 'Добавить строчку', exact: true }).click()
  if (await row(index).locator('.recipe-name-cell .recipe-edit').isVisible()) await row(index).locator('.recipe-name-cell .recipe-edit').click()
  await row(index).getByRole('textbox', { name: 'Название продукта', exact: true }).fill(name)
  await row(index).getByRole('option').filter({ hasText: name }).first().click()
  await row(index).locator('.recipe-weight-cell button').click()
  await row(index).getByRole('textbox', { name: 'Вес ингредиента в граммах', exact: true }).fill(weight)
  await page.locator('.recipe-heading-title').click()
}
async function searchInputKeyboardCheck() {
  const input = row(0).getByRole('textbox', { name: 'Название продукта', exact: true })
  await input.press('ArrowDown')
  assert.equal(await row(0).getByRole('option').first().evaluate(n => n === document.activeElement), true)
  await page.keyboard.press('Escape')
  assert.equal(await input.evaluate(n => n === document.activeElement), true)
}
async function geometry(width) {
  const result = await page.evaluate(() => {
    const table = document.querySelector('.recipe-table'), dialog = document.querySelector('.recipe-library')
    const visible = element => element.getClientRects().length > 0
    const numbers = [...document.querySelectorAll('.recipe-number')].filter(visible)
    return {
      document: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
      table: [table.scrollWidth, table.clientWidth],
      drawer: dialog.open ? [dialog.scrollWidth, dialog.clientWidth] : null,
      clipped: numbers.filter(n => { const r = n.getBoundingClientRect(); return n.scrollWidth > n.clientWidth + 1 || r.left < -.5 || r.right > innerWidth + .5 }).map(n => n.textContent),
      namesClipped: [...document.querySelectorAll('.recipe-name-cell')].filter(visible).filter(n => n.scrollWidth > n.clientWidth + 1).map(n => n.textContent),
      rowHeights: [...document.querySelectorAll('.recipe-columns,.recipe-row,.recipe-total')].filter(visible).map(n => n.getBoundingClientRect().height),
      tableBounds: [table.getBoundingClientRect().width, table.getBoundingClientRect().height],
      nameFont: getComputedStyle(document.querySelector('.recipe-name-cell')).font,
    }
  })
  for (const key of ['document', 'table', 'drawer']) if (result[key]) assert.ok(result[key][0] <= result[key][1] + 1, key + ' overflow ' + width + ': ' + JSON.stringify(result))
  assert.deepEqual(result.clipped, [], 'all values visible at ' + width)
  assert.deepEqual(result.namesClipped, [], 'names wrap at ' + width)
  checks.push({ width, geometry: result })
}
async function newRecipe(accept = true) {
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click()
  const handler = dialog => accept ? dialog.accept() : dialog.dismiss()
  page.once('dialog', handler)
  await page.getByRole('button', { name: '+ Новый рецепт', exact: true }).click()
  page.off('dialog', handler)
}
async function openSaved(name) {
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click()
  await page.locator('.recipe-library').getByRole('button', { name, exact: true }).waitFor()
  await page.locator('.recipe-library').getByRole('button', { name, exact: true }).click()
  await page.locator('.recipe-library').waitFor({ state: 'hidden' })
}
try {
  await request('/api/account-auth/login', { email: 'recipe-browser@example.test', password: 'Test-Password-9' })
  await page.goto(url + '/recipes'); await page.locator('.recipe-heading-title').waitFor()
  const tutorial = page.locator('.recipe-tutorial')
  await tutorial.locator('.recipe-tutorial-progress').filter({ hasText: '1 из 6' }).waitFor()
  assert.equal(await tutorial.getByRole('button', { name: 'Закрыть', exact: true }).isVisible(), false)
  assert.equal(await tutorial.getByRole('button', { name: 'Пропустить', exact: true }).count(), 0)
  await page.keyboard.press('Escape'); assert.equal(await tutorial.isVisible(), true)
  await capture('tutorial-first-360'); await responsiveState('tutorial-first')
  for (let i = 0; i < 5; i++) await tutorial.getByRole('button', { name: 'Далее', exact: true }).click()
  await page.route('**/api/apps/recipes/tutorial', route => route.abort('failed'))
  await tutorial.getByRole('button', { name: 'Начать', exact: true }).click()
  await tutorial.locator('.recipe-tutorial-error').filter({ hasText: 'Нет связи' }).waitFor()
  assert.equal(await page.locator('main.recipe-shell').evaluate(n => n.inert), true)
  assert.equal((await request('/api/apps/recipes')).tutorialCompleted, false)
  await page.unroute('**/api/apps/recipes/tutorial')
  await page.evaluate(() => { window.recipeTutorialEvents = []; window.addEventListener('edabalans:app-completed', e => window.recipeTutorialEvents.push(e.detail)) })
  await tutorial.getByRole('button', { name: 'Начать', exact: true }).click(); await tutorial.waitFor({ state: 'hidden' })
  assert.deepEqual(await page.evaluate(() => window.recipeTutorialEvents), [{ app: 'recipes', completion: 'tutorial' }])
  assert.equal((await request('/api/apps/recipes')).tutorialCompleted, true)
  await page.reload(); await page.waitForFunction(() => !document.querySelector('main.recipe-shell').inert)
  assert.equal(await tutorial.isVisible(), false)
  await page.getByRole('button', { name: 'Как пользоваться', exact: true }).click(); await tutorial.waitFor()
  await tutorial.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await capture('mobile-360-empty'); await geometry(360)
  await responsiveState('empty')
  await page.getByRole('button', { name: 'Добавить строчку', exact: true }).click()
  assert.equal(await page.locator('.recipe-status-text').innerText(), 'Новый рецепт', 'a blank row does not claim a confirmed save')
  await page.locator('.recipe-heading-title').click()
  assert.equal(await page.locator('[data-total=all] .recipe-number').first().inputValue(), '')
  await row(0).locator('.recipe-name-cell .recipe-edit').click(); await row(0).getByRole('textbox', { name: 'Название продукта', exact: true }).fill('Салат')
  await row(0).getByRole('option').first().waitFor(); await capture('mobile-360-search'); await geometry(360)
  await searchInputKeyboardCheck()
  await responsiveState('search')
  await page.locator('.recipe-heading-title').click()
  await setTitle(vectors[0].name)
  await page.getByRole('textbox', { name: 'Вес готового блюда, г', exact: true }).fill('1050'); await page.locator('.recipe-notes').fill('Порядок приготовления\nhttps://edabalans.ru/recipes?original=caesar')
  await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).fill('525')
  for (const [i, [name, weight]] of vectors[0].rows.entries()) await choose(i, name, weight)
  await assertCaesarRows()
  for (const kind of ['all', 'per100', 'perPortion']) {
    assert.deepEqual(await page.locator(`[data-total=${kind}] .recipe-number[data-nutrient]`).allTextContents(), vectors[0].expected[kind].map(s => s.replace('.', ',')))
  }
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  const recipes = (await request('/api/apps/recipes')).recipes, caesar = recipes.find(r => r.title === vectors[0].name)
  assert.ok(caesar)
  const saved = (await request('/api/apps/recipes/' + caesar.id)).recipe
  assert.equal(saved.notes, 'Порядок приготовления\nhttps://edabalans.ru/recipes?original=caesar'); assert.equal(saved.ingredients.length, 9); assert.equal(saved.yield, 1050); assert.equal(saved.portion, 525)
  const projection = math.calculate(saved.ingredients.map(i => ({ source: i.source, weight: String(i.weight) })), String(saved.yield), String(saved.portion))
  for (const kind of ['all', 'per100', 'perPortion']) for (const k of keys) assert.equal(math.format(projection[kind][k], k).replace(',', '.'), saved.totals[kind][k])
  await assertCaesarRows()
  assert.equal(await page.locator('.recipe-heading-title').innerText(), vectors[0].name); assert.equal(await page.locator('.recipe-table-title').innerText(), 'Продукты')
  assert.equal(await page.locator('.recipe-notes-view a').getAttribute('href'), 'https://edabalans.ru/recipes?original=caesar')
  assert.equal(await page.locator('.finish-edit').count(), 0)
  assert.ok(await page.locator('.recipe-add-area').evaluate(n => n.previousElementSibling.className === 'recipe-rows' && n.nextElementSibling.className === 'recipe-totals'))
  for (const [i, ingredient] of saved.ingredients.entries()) for (const k of keys) {
    assert.equal(math.format(projection.values[i][k], k).replace(',', '.'), ingredient.total[k])
    assert.equal(projection.ranks[i][k], ingredient.ranks[k])
    assert.equal(await row(i).locator('.recipe-number[data-nutrient=' + k + ']').getAttribute('data-rank'), ingredient.ranks[k] ? String(ingredient.ranks[k]) : null)
  }
  await capture('mobile-360-caesar'); await page.locator('.recipe-table').screenshot({ path: join(out, 'table-360.png') }); await geometry(360)
  const snapshot = await page.evaluate(async () => {
    const clone = document.documentElement.cloneNode(true)
    const originals = document.querySelectorAll('input')
    clone.querySelectorAll('input').forEach((n, i) => n.setAttribute('value', originals[i].value))
    clone.querySelectorAll('script').forEach(n => n.remove())
    for (const link of clone.querySelectorAll('link[rel=stylesheet]')) {
      const style = document.createElement('style'); style.textContent = await (await fetch(link.href)).text(); link.replaceWith(style)
    }
    return '<!doctype html>\n' + clone.outerHTML
  })
  await writeFile(join(out, 'capture-caesar.html'), snapshot)
  for (const width of [430, 598, 599, 600, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 }); await page.waitForTimeout(50); await geometry(width)
    if ([430, 598, 599, 600, 768, 1280, 1440].includes(width)) await capture('caesar-' + width)
  }
  assert.ok(Math.abs((await page.locator('#recipes-app').boundingBox()).width - 720) < 1)
  await page.setViewportSize({ width: 360, height: 900 })
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click(); await page.getByRole('dialog', { name: 'Каталог рецептов' }).waitFor(); await page.waitForFunction(() => document.querySelector('.recipe-library-status').textContent === ''); await capture('mobile-360-library'); await geometry(360)
  await responsiveState('library')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  assert.equal(await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).evaluate(n => n === document.activeElement), true)
  await setTitle('Несохранённый Цезарь')
  await newRecipe(false); assert.equal(await page.locator('.recipe-title').inputValue(), 'Несохранённый Цезарь')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await newRecipe(true); assert.equal(await page.locator('.recipe-title').inputValue(), '')
  await openSaved(vectors[0].name); assert.equal(await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).inputValue(), '525')
  assert.equal(await page.locator('.recipe-title').inputValue(), vectors[0].name)
  assert.equal(await page.getByRole('textbox', { name: 'Вес готового блюда, г', exact: true }).inputValue(), '1050'); await assertCaesarRows()
  await row(0).locator('.recipe-weight-cell button').click(); await fourWidthState('weight-editor')
  await page.locator('.recipe-heading-title').click()
  // Delayed successful save updates the persisted base, while later typing remains untouched.
  let savedWrites = 0
  await page.route('**/api/apps/recipes/' + caesar.id, async route => {
    if (route.request().method() !== 'PUT') return route.continue()
    savedWrites++
    assert.deepEqual(route.request().postDataJSON().ingredients, saved.ingredients.map(i => ({ kind: i.source.kind, sourceId: i.source.id, weight: String(i.weight) })), 'reopened sources, weights and order survive the next save')
    const response = await route.fetch(); await new Promise(resolve => setTimeout(resolve, 350)); await route.fulfill({ response })
  })
  await setTitle('Сохранённый снимок')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохраняю')
  assert.equal(await page.getByRole('button', { name: 'Сохранить', exact: true }).isDisabled(), true)
  await page.getByRole('button', { name: 'Редактировать название рецепта', exact: true }).click()
  await page.getByRole('textbox', { name: 'Название рецепта', exact: true }).press('End')
  await page.getByRole('textbox', { name: 'Название рецепта', exact: true }).pressSequentially(' + новый ввод')
  await status('Изменено после сохранения')
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Сохранённый снимок + новый ввод'); assert.equal(savedWrites, 1)
  await page.unroute('**/api/apps/recipes/' + caesar.id)
  assert.equal((await request('/api/apps/recipes/' + caesar.id)).recipe.title, 'Сохранённый снимок')
  await page.route('**/api/apps/recipes/' + caesar.id, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Конфликт версии' }) }))
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('другой вкладке')
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Сохранённый снимок + новый ввод')
  await fourWidthState('save-conflict')
  await page.unroute('**/api/apps/recipes/' + caesar.id)
  await page.route('**/api/apps/recipes/' + caesar.id, route => route.abort('failed'))
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Нет связи')
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Сохранённый снимок + новый ввод'); await page.unroute('**/api/apps/recipes/' + caesar.id)
  await page.route('**/api/apps/recipes/' + caesar.id, route => route.fulfill({ status: 502, contentType: 'text/html', body: '<html>Bad Gateway</html>' }))
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Нет связи')
  assert.equal(await page.locator('.recipe-status-text').innerText(), 'Нет связи', 'a gateway failure keeps a concise message instead of a JSON parser error')
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Сохранённый снимок + новый ввод')
  await page.unroute('**/api/apps/recipes/' + caesar.id)
  await newRecipe(true)
  // Search completion must not overwrite a later term, including an aborted old request.
  let oldRequested
  await page.evaluate(() => { window.__RecipeTestAbortController = window.AbortController; window.AbortController = class extends window.AbortController { abort() {} } })
  const oldStarted = new Promise(resolve => { oldRequested = resolve })
  await page.route('**/api/apps/recipes/catalog?**', async route => {
    const q = new URL(route.request().url()).searchParams.get('q')
    if (q === 'старое') { oldRequested(); await new Promise(resolve => setTimeout(resolve, 450)); return route.fulfill({ json: { ok: true, items: [{ ...saved.ingredients[0].source, name: 'Старый результат' }] } }).catch(() => {}) }
    if (q === 'новое') return route.fulfill({ json: { ok: true, items: [{ ...saved.ingredients[1].source, name: 'Новый результат' }] } })
    return route.continue()
  })
  await row(0).locator('.recipe-name-cell .recipe-edit').click(); const searchInput = row(0).getByRole('textbox', { name: 'Название продукта', exact: true })
  await searchInput.fill('старое'); await oldStarted; await searchInput.fill('новое')
  await row(0).getByRole('option').filter({ hasText: 'Новый результат' }).waitFor(); await page.waitForTimeout(550)
  assert.equal(await row(0).getByRole('option').count(), 1); assert.equal(await searchInput.inputValue(), 'новое')
  assert.equal(await searchInput.evaluate(n => n === document.activeElement), true)
  await page.unroute('**/api/apps/recipes/catalog?**')
  await page.evaluate(() => { window.AbortController = window.__RecipeTestAbortController; delete window.__RecipeTestAbortController })
  await page.route('**/api/apps/recipes/catalog?**', route => route.abort('failed'))
  await searchInput.fill('нет связи'); await row(0).getByText('Нет связи', { exact: false }).waitFor(); assert.equal(await searchInput.inputValue(), 'нет связи')
  await page.unroute('**/api/apps/recipes/catalog?**')
  await searchInput.fill('Мой десятичный продукт'); await row(0).getByRole('button', { name: '+ Добавить свой продукт', exact: true }).click()
  const own = row(0).locator('.recipe-own-form')
  await own.locator('[name=protein]').fill('12,345'); await own.locator('[name=fat]').fill('2.5'); await own.locator('[name=carbohydrate]').fill('4,567'); await own.locator('[name=calories]').fill('100')
  await fourWidthState('own-product')
  await page.route('**/api/apps/recipes/products', route => route.request().method() === 'POST' ? route.abort('failed') : route.continue())
  await own.getByRole('button', { name: 'Добавить', exact: true }).click(); await own.locator('.own-error').filter({ hasText: 'Нет связи' }).waitFor()
  assert.equal(await own.locator('[name=protein]').inputValue(), '12,345')
  await fourWidthState('own-product-error')
  await page.unroute('**/api/apps/recipes/products')
  await own.getByRole('button', { name: 'Добавить', exact: true }).click(); await row(0).locator('.recipe-name-cell .recipe-edit').filter({ hasText: 'Мой десятичный продукт' }).waitFor()
  await row(0).locator('.recipe-weight-cell button').click(); await row(0).getByRole('textbox', { name: 'Вес ингредиента в граммах', exact: true }).fill('250'); await page.locator('.recipe-heading-title').click()
  assert.equal(await row(0).locator('.recipe-number[data-nutrient=protein]').innerText(), '30,9')
  await setTitle('Личный рецепт'); await page.getByRole('textbox', { name: 'Вес готового блюда, г', exact: true }).fill('500'); await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).fill('125')
  let createWrites = 0
  await page.route('**/api/apps/recipes', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    createWrites++; const response = await route.fetch(); await new Promise(resolve => setTimeout(resolve, 350)); await route.fulfill({ response })
  })
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохраняю')
  await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).fill('100'); await status('Изменено после сохранения')
  assert.equal(await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).inputValue(), '100')
  await page.unroute('**/api/apps/recipes')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  const personalMatches = (await request('/api/apps/recipes')).recipes.filter(r => r.title === 'Личный рецепт')
  assert.equal(personalMatches.length, 1, 'subsequent save uses returned identity/version after in-flight create edits'); assert.equal(createWrites, 1)
  const personal = personalMatches[0]
  assert.ok(personal)
  await newRecipe(); await openSaved('Личный рецепт'); assert.equal(await row(0).locator('.recipe-number[data-nutrient=protein]').innerText(), '30,9')
  const personalProduct = (await request('/api/apps/recipes/' + personal.id)).recipe.ingredients[0].source
  await request('/api/apps/recipes/products/' + personalProduct.id, { name: personalProduct.name, protein: '1', fat: '2.5', carbohydrate: '4.567', calories: '100' }, 'PUT')
  await row(0).locator('.recipe-name-cell .recipe-edit').click(); await row(0).getByRole('option').filter({ hasText: personalProduct.name }).click()
  assert.equal(await row(0).locator('.recipe-number[data-nutrient=protein]').innerText(), '2,5', 'selecting a refreshed source releases stale server display even with the same UUID/weight')
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click(); await page.getByRole('dialog').getByRole('button', { name: 'Скрыть продукт Мой десятичный продукт', exact: true }).waitFor()
  page.once('dialog', dialog => dialog.accept()); await page.getByRole('button', { name: 'Скрыть продукт Мой десятичный продукт', exact: true }).click()
  await page.getByRole('button', { name: 'Скрыть продукт Мой десятичный продукт', exact: true }).waitFor({ state: 'detached' }); await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).fill('100'); await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  // A saved recipe remains selectable as a source, and in-use deletion stays blocked.
  await newRecipe(); await choose(0, 'Личный рецепт', '500')
  await setTitle('Вложенный рецепт'); await page.getByRole('textbox', { name: 'Вес готового блюда, г', exact: true }).fill('600'); await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).fill('200')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click(); page.once('dialog', dialog => dialog.accept()); await page.getByRole('button', { name: 'Удалить рецепт Личный рецепт', exact: true }).click()
  await page.locator('.recipe-library-status').filter({ hasText: 'используется' }).waitFor(); await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  // Invalid free text cannot silently disappear from a save.
  await page.getByRole('button', { name: 'Добавить строчку', exact: true }).click(); await row(1).getByRole('textbox', { name: 'Название продукта', exact: true }).fill('Свободный текст')
  await page.locator('.recipe-heading-title').click(); await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Проверьте продукт')
  assert.equal(await row(1).locator('.recipe-name-cell .recipe-edit').innerText(), 'Свободный текст')
  await row(1).locator('.recipe-name-cell .recipe-edit').click(); await row(1).getByRole('button', { name: 'Удалить строку', exact: true }).click()
  const periodicProduct = (await request('/api/apps/recipes/products', { name: 'Точный белок', protein: '1', fat: '0', carbohydrate: '0', calories: '0' })).product
  const base = (await request('/api/apps/recipes', { title: 'Основа с выходом 3 г', yield: '3', portion: '3', ingredients: [{ kind: 'product', sourceId: periodicProduct.id, weight: '100' }] })).recipe
  const exactParent = (await request('/api/apps/recipes', { title: 'Точное вложение', yield: '103', portion: '103', ingredients: [{ kind: 'recipe', sourceId: base.id, weight: '3' }, { kind: 'product', sourceId: periodicProduct.id, weight: '100' }] })).recipe
  await openSaved(exactParent.title)
  assert.deepEqual(await page.locator('.recipe-row:not([hidden]) .recipe-number[data-nutrient=protein]').allTextContents(), ['1,0', '1,0'])
  assert.deepEqual(await page.locator('.recipe-row:not([hidden]) .recipe-number[data-nutrient=protein]').evaluateAll(nodes => nodes.map(n => n.dataset.rank)), ['1', '1'])
  assert.equal(await page.locator('[data-total=all] .recipe-number[data-nutrient=protein]').innerText(), '2,0')
  // Extreme accepted values invoke the same row-wide wrapping rule as long names.
  await newRecipe(true)
  const maximum = (await request('/api/apps/recipes/products', { name: 'Максимальный продукт с очень длинным названием без потери текста', protein: '100', fat: '100', carbohydrate: '100', calories: '1000' })).product
  await choose(0, maximum.name, '99999')
  await page.getByRole('textbox', { name: 'Вес готового блюда, г', exact: true }).fill('1'); await page.getByRole('textbox', { name: 'Вес порции, г', exact: true }).fill('1')
  for (const width of [360, 430, 768, 1440]) { await page.setViewportSize({ width, height: 900 }); await page.waitForTimeout(50); await geometry(width); if (width <= 430) assert.ok(await page.locator('.recipe-total.expanded').count()); await capture('extreme-' + width) }
  assert.equal(await page.locator('[data-total=per100] .recipe-number[data-nutrient=calories]').innerText(), '99999000')
  await page.setViewportSize({ width: 360, height: 900 }); await setTitle('Timeout черновик')
  let attempts = 0, refreshedLists = 0
  await page.route('**/api/apps/recipes', async route => { if (route.request().method() !== 'POST') { refreshedLists++; return route.continue() } attempts++; const response = await route.fetch(); await new Promise(resolve => setTimeout(resolve, 11000)); await route.fulfill({ response }).catch(() => {}) })
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await page.locator('.recipe-status-text').filter({ hasText: 'Нет ответа' }).waitFor({ timeout: 15000 })
  assert.equal(attempts, 1); assert.equal(await page.locator('.recipe-title').inputValue(), 'Timeout черновик')
  await page.waitForFunction(() => !document.querySelector('.save').disabled)
  assert.ok(refreshedLists >= 1, 'timeout refreshes the list before any manual retry')
  assert.ok((await request('/api/apps/recipes')).recipes.some(recipe => recipe.title === 'Timeout черновик'), 'committed create can be found after its response is lost')
  await page.unroute('**/api/apps/recipes')
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click(); page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: 'Удалить рецепт Вложенный рецепт', exact: true }).click()
  await page.getByRole('button', { name: 'Удалить рецепт Вложенный рецепт', exact: true }).waitFor({ state: 'detached' })
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Timeout черновик')

  // A trailing blank is not the hundredth ingredient: it must remain editable.
  await newRecipe(true)
  const ingredient = { kind: saved.ingredients[0].source.kind, sourceId: saved.ingredients[0].source.id, weight: '1' }
  const boundary = (await request('/api/apps/recipes', { title: 'Граница строк', yield: '100', portion: '100', ingredients: Array.from({ length: 99 }, () => ({ ...ingredient })) })).recipe
  await openSaved(boundary.title)
  assert.equal(await page.locator('.recipe-row:visible').count(), 99)
  await choose(99, saved.ingredients[0].source.name, '1')
  assert.equal(await page.locator('.recipe-row:visible').count(), 100)
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  assert.equal((await request('/api/apps/recipes/' + boundary.id)).recipe.ingredients.length, 100)
  await page.getByRole('button', { name: 'Добавить строчку', exact: true }).click(); await status('до 100 строк')

  // The last explicit selection wins even if an earlier GET finishes first.
  const openerA = (await request('/api/apps/recipes', { title: 'Открытие A', yield: '1', portion: '1', ingredients: [ingredient] })).recipe
  const openerB = (await request('/api/apps/recipes', { title: 'Открытие B', yield: '1', portion: '1', ingredients: [ingredient] })).recipe
  let releaseA, releaseB, startedA, startedB
  const waitingA = new Promise(resolve => { startedA = resolve }), waitingB = new Promise(resolve => { startedB = resolve })
  const gateA = new Promise(resolve => { releaseA = resolve }), gateB = new Promise(resolve => { releaseB = resolve })
  await page.route('**/api/apps/recipes/' + openerA.id, async route => { const response = await route.fetch(); startedA(); await gateA; await route.fulfill({ response }) })
  await page.route('**/api/apps/recipes/' + openerB.id, async route => { const response = await route.fetch(); startedB(); await gateB; await route.fulfill({ response }) })
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click()
  await page.getByRole('button', { name: openerA.title, exact: true }).click(); await waitingA
  await page.getByRole('button', { name: openerB.title, exact: true }).click(); await waitingB
  const receivedA = page.waitForResponse(response => response.url().endsWith('/api/apps/recipes/' + openerA.id))
  releaseA(); await receivedA; await page.waitForTimeout(50)
  assert.equal(await page.locator('.recipe-title').inputValue(), boundary.title)
  assert.equal(await page.locator('.recipe-library').isVisible(), true)
  releaseB(); await page.locator('.recipe-library').waitFor({ state: 'hidden' })
  assert.equal(await page.locator('.recipe-title').inputValue(), openerB.title)
  await page.unroute('**/api/apps/recipes/' + openerA.id); await page.unroute('**/api/apps/recipes/' + openerB.id)

  async function delayedDelete(recipe, change, beforeCommit = false) {
    let acknowledge, started
    const begun = new Promise(resolve => { started = resolve }), gate = new Promise(resolve => { acknowledge = resolve })
    await page.route('**/api/apps/recipes/' + recipe.id, async route => {
      if (route.request().method() !== 'DELETE') return route.continue()
      let response
      if (beforeCommit) { started(); await gate; response = await route.fetch() }
      else { response = await route.fetch(); started(); await gate }
      await route.fulfill({ response })
    })
    await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click(); page.once('dialog', dialog => dialog.accept())
    await page.getByRole('button', { name: 'Удалить рецепт ' + recipe.title, exact: true }).click(); await begun
    await change(); acknowledge()
    await page.waitForFunction(id => !document.querySelector('[data-delete-recipe="' + id + '"]'), recipe.id)
    await page.unroute('**/api/apps/recipes/' + recipe.id)
  }
  await delayedDelete(openerB, async () => {
    await page.getByRole('button', { name: '+ Новый рецепт', exact: true }).click()
    await setTitle('Новый независимый черновик')
  })
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Новый независимый черновик', 'late delete cannot clear a different screen')
  await newRecipe(true); await openSaved(openerA.title)
  await delayedDelete(openerA, async () => {
    await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await setTitle('Черновик после удаления')
  })
  await status('Текущий черновик можно сохранить как новый')
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Черновик после удаления')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  const replacement = (await request('/api/apps/recipes')).recipes.find(recipe => recipe.title === 'Черновик после удаления')
  assert.ok(replacement); assert.notEqual(replacement.id, openerA.id, 'a retained draft does not update a deleted identity')

  // Opening the target during DELETE must also detach the acknowledged deleted UUID.
  await newRecipe()
  const openerC = (await request('/api/apps/recipes', { title: 'Открытие во время удаления', yield: '1', portion: '1', ingredients: [ingredient] })).recipe
  await delayedDelete(openerC, async () => {
    await page.getByRole('button', { name: openerC.title, exact: true }).click(); await page.locator('.recipe-library').waitFor({ state: 'hidden' })
    await setTitle('Ввод во время удаления')
  }, true)
  await status('Текущий черновик можно сохранить как новый')
  assert.equal(await page.locator('.recipe-title').inputValue(), 'Ввод во время удаления')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  const reopenedReplacement = (await request('/api/apps/recipes')).recipes.find(recipe => recipe.title === 'Ввод во время удаления')
  assert.ok(reopenedReplacement); assert.notEqual(reopenedReplacement.id, openerC.id)

  // The reverse completion order cannot install an already-deleted identity either.
  await newRecipe()
  const staleOpen = (await request('/api/apps/recipes', { title: 'Позднее открытие удалённого', yield: '1', portion: '1', ingredients: [ingredient] })).recipe
  let deliverOpen, openStarted
  const openBegun = new Promise(resolve => { openStarted = resolve }), openGate = new Promise(resolve => { deliverOpen = resolve })
  await page.route('**/api/apps/recipes/' + staleOpen.id, async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch(); openStarted(); await openGate; await route.fulfill({ response })
  })
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click()
  await page.getByRole('button', { name: staleOpen.title, exact: true }).click(); await openBegun
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: 'Удалить рецепт ' + staleOpen.title, exact: true }).click()
  await page.getByRole('button', { name: 'Удалить рецепт ' + staleOpen.title, exact: true }).waitFor({ state: 'detached' })
  const staleResponse = page.waitForResponse(response => response.url().endsWith('/api/apps/recipes/' + staleOpen.id) && response.request().method() === 'GET')
  deliverOpen(); await staleResponse; await page.waitForTimeout(50)
  assert.equal(await page.locator('.recipe-title').inputValue(), '', 'stale GET cannot reinstall a deleted UUID')
  await page.unroute('**/api/apps/recipes/' + staleOpen.id)
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  // An original opens as a draft; saving creates a private copy and keeps the original intact.
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click()
  await page.locator('[data-original="synthetic"]').waitFor()
  assert.equal(await page.locator('[data-original="inactive"]').count(), 0)
  assert.equal(await page.locator('.recipe-library-originals [data-delete-recipe]').count(), 0)
  const original = (await request('/api/apps/recipes/originals/synthetic')).recipe
  await page.locator('[data-original="synthetic"]').click()
  await page.locator('.recipe-library').waitFor({ state: 'hidden' })
  assert.equal(await page.locator('.recipe-title').inputValue(), original.title)
  assert.equal(await page.getByRole('textbox', { name: 'Вес готового блюда, г', exact: true }).inputValue(), '75.5')
  assert.equal(await page.locator('.recipe-notes-view a').getAttribute('href'), 'https://edabalans.ru/lk?open=recipes:day-15-recipe-synthetic')
  await row(0).locator('.recipe-weight-cell button').click()
  const weightBox = row(0).getByRole('textbox', { name: 'Вес ингредиента в граммах', exact: true })
  await weightBox.fill(''); await weightBox.pressSequentially('6aб')
  assert.equal(await weightBox.inputValue(), '6')
  await weightBox.fill('6kg'); assert.equal(await weightBox.inputValue(), '6')
  await weightBox.fill('0'); await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await status('Проверьте продукт и вес')
  assert.equal(await row(0).getAttribute('data-invalid'), 'true', 'invalid weight remains visibly identifiable without extra hint lines')
  await capture('invalid-weight-360')
  await row(0).locator('.recipe-weight-cell button').click()
  await row(0).getByRole('textbox', { name: 'Вес ингредиента в граммах', exact: true }).fill('6')
  await page.locator('.recipe-heading-title').click()
  const portionBox = page.getByRole('textbox', { name: 'Вес порции, г', exact: true })
  await portionBox.fill('37,75г'); assert.equal(await portionBox.inputValue(), '37.75')
  await setTitle('Личная версия оригинала')
  await page.getByRole('button', { name: 'Редактировать примечания', exact: true }).click()
  await page.locator('.recipe-notes').fill('<img src=x onerror="window.__badNotes=true"> javascript:alert(1)\nhttps://edabalans.ru/recipes')
  await page.locator('.recipe-heading-title').click()
  assert.equal(await page.locator('.recipe-notes-view img').count(), 0)
  assert.equal(await page.locator('.recipe-notes-view a').count(), 1)
  assert.equal(await page.evaluate(() => window.__badNotes), undefined)
  let postStarted, releasePost
  const postBegun = new Promise(resolve => { postStarted = resolve }), postGate = new Promise(resolve => { releasePost = resolve })
  await page.route('**/api/apps/recipes', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const response = await route.fetch(); postStarted(); await postGate; await route.fulfill({ response })
  })
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await postBegun
  await setTitle('Личная версия оригинала + правки')
  releasePost(); await status('Изменено после сохранения'); await page.unroute('**/api/apps/recipes')
  const personalCopy = (await request('/api/apps/recipes')).recipes.find(r => r.title === 'Личная версия оригинала')
  assert.ok(personalCopy)
  const copied = (await request('/api/apps/recipes/' + personalCopy.id)).recipe
  assert.equal(copied.ingredients[0].source.kind, 'snapshot')
  assert.equal(copied.ingredients[0].total.protein, '2.0')
  assert.deepEqual((await request('/api/apps/recipes/originals/synthetic')).recipe, original)
  await page.route('**/api/apps/recipes/' + personalCopy.id, route => {
    if (route.request().method() === 'PUT') {
      assert.equal(route.request().postDataJSON().ingredients[0].kind, 'snapshot', 'a saved original draft adopts its immutable private source')
      assert.equal(route.request().postDataJSON().ingredients[0].sourceId, copied.ingredients[0].source.id)
    }
    return route.continue()
  })
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  await page.unroute('**/api/apps/recipes/' + personalCopy.id)
  assert.equal((await request('/api/apps/recipes/' + personalCopy.id)).recipe.title, 'Личная версия оригинала + правки')
  let putStarted, releasePut
  const putBegun = new Promise(resolve => { putStarted = resolve }), putGate = new Promise(resolve => { releasePut = resolve })
  await page.route('**/api/apps/recipes/' + personalCopy.id, async route => {
    if (route.request().method() !== 'PUT') return route.continue()
    const response = await route.fetch(); putStarted(); await putGate; await route.fulfill({ response })
  })
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await putBegun
  await row(0).locator('.recipe-weight-cell button').click()
  await row(0).getByRole('textbox', { name: 'Вес ингредиента в граммах', exact: true }).fill('9')
  releasePut(); await status('Изменено после сохранения'); await page.unroute('**/api/apps/recipes/' + personalCopy.id)
  assert.equal(await row(0).getByRole('textbox', { name: 'Вес ингредиента в граммах', exact: true }).inputValue(), '9', 'saved identity adoption preserves live editor input')
  await page.locator('.recipe-heading-title').click()
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click(); await status('Сохранено')
  const twiceSaved = (await request('/api/apps/recipes/' + personalCopy.id)).recipe
  assert.equal(twiceSaved.ingredients[0].weight, 9)
  assert.equal(twiceSaved.ingredients[0].total.protein, '3.0')
  assert.equal(twiceSaved.version, 4)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByRole('button', { name: 'Телефон', exact: true }).click()
  assert.equal((await page.locator('#recipes-app').boundingBox()).width, 360)
  await capture('desktop-phone-switch'); await geometry(1280)
  const phoneBounds = await page.locator('#recipes-app').boundingBox()
  await page.getByRole('button', { name: 'Каталог рецептов', exact: true }).click()
  const phoneCatalogue = await page.locator('.recipe-library').boundingBox()
  assert.equal(phoneCatalogue.width, phoneBounds.width)
  assert.ok(Math.abs(phoneCatalogue.x - phoneBounds.x) < 1)
  await capture('desktop-phone-catalogue')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByRole('button', { name: 'Как пользоваться', exact: true }).click()
  assert.equal((await page.locator('.recipe-tutorial').boundingBox()).width, 336)
  await capture('desktop-phone-tutorial')
  await page.locator('.tutorial-close').click()
  await page.getByRole('button', { name: 'ПК', exact: true }).click()
  assert.equal((await page.locator('#recipes-app').boundingBox()).width, 720)
  await page.setViewportSize({ width: 360, height: 900 }); await capture('original-personal-copy')
  assert.deepEqual(errors, [], 'no browser script failures')
  await writeFile(join(out, 'geometry.json'), JSON.stringify(checks, null, 2))
  console.log('Recipe unit/parity, real API journey, races/errors, geometry passed. Evidence: ' + out)
} catch (error) {
  await capture('failure'); console.error('Evidence: ' + out); throw error
} finally {
  await browser.close(); if (serverProcess) serverProcess.kill()
}
