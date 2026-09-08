const CITIES = [
  { name: 'Санкт-Петербург', latitude: 59.9343, longitude: 30.3351, timezone: 'Europe/Moscow' },
  { name: 'Москва', latitude: 55.7558, longitude: 37.6173, timezone: 'Europe/Moscow' },
  { name: 'Кейптаун', latitude: -33.9249, longitude: 18.4241, timezone: 'Africa/Johannesburg' },
  { name: 'Геленджик', latitude: 44.5609, longitude: 38.0767, timezone: 'Europe/Moscow' },
  { name: 'Кутаиси', latitude: 42.2679, longitude: 42.6946, timezone: 'Asia/Tbilisi' },
]

let LOCATION = CITIES[0]
let forecast
let selectedDate
let forecastRequest = 0
let historyRequest = 0
const fields = new Set(['air', 'feels', 'wind', 'precipitation', 'snow'])

const app = document.querySelector('#weather-app')
const dailyGrid = document.querySelector('#daily-grid')
const hourlyGrid = document.querySelector('#hourly-grid')
const cityList = document.querySelector('#city-list')
const cityTrigger = document.querySelector('#city-trigger')
const cityPanel = document.querySelector('#city-panel')
const mobileMenuButton = document.querySelector('#mobile-menu-button')
const settingsButton = document.querySelector('#settings-button')
const settingsPanel = document.querySelector('#settings-panel')
const updatedAt = document.querySelector('#updated-at')
const historyGrid = document.querySelector('#history-grid')
const historyStatus = document.querySelector('#history-status')
const historyStart = document.querySelector('#history-start')
const historyEnd = document.querySelector('#history-end')

function formatNumber(value, digits = 0) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(value)
}

function signedTemperature(value) {
  return `${value > 0 ? '+' : ''}${Math.round(value)}`
}

function precipitationText(value) {
  return value > 0 && value < 0.1 ? '< 0,1' : formatNumber(value, 1)
}

function weatherIcon(code, isDay = 1) {
  if (code >= 71) return { glyph: '❄︎', tone: 'snow' }
  if (code >= 51) return { glyph: '☂︎', tone: 'rain' }
  if (code >= 3) return { glyph: '☁︎', tone: 'cloud' }
  return isDay ? { glyph: '☀︎', tone: 'sun' } : { glyph: '☾', tone: 'moon' }
}

function iconMarkup(code, isDay = 1) {
  const icon = weatherIcon(code, isDay)
  return `<span class="weather-icon ${icon.tone}">${icon.glyph}</span>`
}

function localDate(date) {
  return new Date(`${date}T12:00:00`)
}

function dayParts(date) {
  const value = localDate(date)
  const weekday = new Intl.DateTimeFormat('ru-RU', { weekday: 'short' }).format(value).replace('.', '')
  const calendarDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(value)
  return {
    weekday: weekday[0].toUpperCase() + weekday.slice(1),
    calendarDate,
    weekend: value.getDay() === 0 || value.getDay() === 6,
  }
}

function hoursFor(date) {
  return forecast.hourly.time.map((time, index) => ({ time, index })).filter(({ time }) => time.startsWith(date))
}

function setPanel(panel, isOpen) {
  panel.hidden = !isOpen
  if (panel !== cityPanel) settingsButton.setAttribute('aria-expanded', String(isOpen))
  if (panel !== settingsPanel) cityTrigger.setAttribute('aria-expanded', String(isOpen))
}

function renderDaily() {
  const totals = forecast.daily.precipitation_sum
  const maxDaily = Math.max(...totals, 0.1)
  const rainSpace = Math.round(26 + Math.max(...totals.map((value) => Math.max(12, value / maxDaily * 58))))
  dailyGrid.style.setProperty('--rain-space', `${rainSpace}px`)

  dailyGrid.replaceChildren(...forecast.daily.time.map((date, index) => {
    const details = dayParts(date)
    const hours = hoursFor(date)
    const hourlyRain = hours.map(({ index: hourIndex }) => forecast.hourly.precipitation[hourIndex])
    const maxHourly = Math.max(...hourlyRain, 0.1)
    const dailyHeight = Math.max(3, totals[index] / maxDaily * (rainSpace - 23))
    const midpoint = hours[Math.min(12, hours.length - 1)]?.index ?? hours[0].index
    const button = document.createElement('button')
    button.className = 'day-button'
    button.type = 'button'
    button.dataset.date = date
    button.setAttribute('aria-pressed', String(date === selectedDate))
    button.setAttribute('aria-label', `${details.weekday}, ${details.calendarDate}: осадки ${precipitationText(totals[index])} мм`)
    button.innerHTML = `
      <span class="day-heading"><span><span class="weekday ${details.weekend ? 'weekend' : ''}">${details.weekday}</span><span class="calendar-date ${details.weekend ? 'weekend' : ''}">${details.calendarDate}</span></span>${iconMarkup(forecast.hourly.weather_code[midpoint], forecast.hourly.is_day[midpoint])}</span>
      <span class="temperatures"><span class="temperature max">${signedTemperature(forecast.daily.temperature_2m_max[index])}</span><span class="temperature min">${signedTemperature(forecast.daily.temperature_2m_min[index])}</span></span>
      <span class="rain-area"><span class="daily-total">${precipitationText(totals[index])}</span><span class="mini-rain" style="height:${dailyHeight}px">${hourlyRain.map((value) => `<i style="height:${Math.max(2, value / maxHourly * 100)}%"></i>`).join('')}</span></span>`
    button.addEventListener('click', () => selectDay(date))
    return button
  }))
}

function windArrow(degrees) {
  return `<span class="wind-arrow" style="--wind-turn:${Math.round(degrees) - 90}deg">➤</span>`
}

function createLabel(text, field) {
  const label = document.createElement('div')
  label.className = `field-label ${fields.has(field) ? '' : 'hidden-field'}`
  label.dataset.field = field
  label.textContent = text
  return label
}

function temperatureCells(field, className, hours, key) {
  const values = hours.map(({ index }) => forecast.hourly[key][index])
  const min = Math.min(...values)
  const range = Math.max(Math.max(...values) - min, 1)
  return hours.map(({ index }, position) => {
    const value = values[position]
    const cell = document.createElement('div')
    const offset = Math.round((Math.max(...values) - value) / range * 14)
    const hue = Math.round(70 - Math.min(42, Math.max(-8, value) * 1.4))
    cell.className = `cell ${className} ${fields.has(field) ? '' : 'hidden-field'}`
    cell.dataset.field = field
    cell.style.setProperty('--temp-offset', `${offset}px`)
    cell.style.setProperty('--temp-color', `hsl(${hue} 74% 85%)`)
    cell.innerHTML = `<span>${signedTemperature(value)}</span>`
    return cell
  })
}

function createCells(field, className, values, formatter) {
  return values.map((value, index) => {
    const cell = document.createElement('div')
    cell.className = `cell ${className} ${fields.has(field) ? '' : 'hidden-field'}`
    cell.dataset.field = field
    cell.innerHTML = formatter(value, index)
    return cell
  })
}

function renderHourly() {
  const hours = hoursFor(selectedDate)
  const precipitation = hours.map(({ index }) => forecast.hourly.precipitation[index])
  const maxRain = Math.max(...precipitation, 0.1)
  hourlyGrid.replaceChildren(
    ...hours.map(({ time, index }) => {
      const cell = document.createElement('div')
      cell.className = 'hour'
      cell.innerHTML = `<span class="hour-time">${time.slice(11)}</span>${iconMarkup(forecast.hourly.weather_code[index], forecast.hourly.is_day[index])}`
      return cell
    }),
    ...temperatureCells('air', 'temperature-cell', hours, 'temperature_2m'),
    ...temperatureCells('feels', 'feels-cell', hours, 'apparent_temperature'),
    ...createCells('wind', 'wind-cell', hours, ({ index }) => `<span class="wind-pair">${formatNumber(forecast.hourly.wind_speed_10m[index])} / ${formatNumber(forecast.hourly.wind_gusts_10m[index])}</span><span class="gust">${windArrow(forecast.hourly.wind_direction_10m[index])}</span>`),
    ...createCells('precipitation', 'precipitation-cell', hours, ({ index }) => `<i class="rain-fill" style="--rain-height:${Math.max(2, forecast.hourly.precipitation[index] / maxRain * 84)}%"></i><span>${precipitationText(forecast.hourly.precipitation[index])}</span>`),
    ...createCells('snow', 'snow-cell', hours, ({ index }) => formatNumber(forecast.hourly.snowfall[index], 1)),
  )
}

function selectDay(date) {
  selectedDate = date
  renderDaily()
  renderHourly()
}

function updateVisibility() {
  document.querySelectorAll('.field-label[data-field], .cell[data-field]').forEach((node) => {
    node.classList.toggle('hidden-field', !fields.has(node.dataset.field))
  })
}

function updateHeader() {
  cityTrigger.textContent = LOCATION.name
  document.title = `Погода в ${LOCATION.name}`
}

function renderCities() {
  cityList.replaceChildren(...CITIES.map((city) => {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = city.name
    button.setAttribute('aria-current', String(city.name === LOCATION.name))
    button.addEventListener('click', () => {
      LOCATION = city
      updateHeader()
      renderCities()
      setPanel(cityPanel, false)
      loadForecast()
      if (!document.querySelector('[data-view-panel="history"]').hidden) loadHistory()
    })
    return button
  }))
}

function switchView(view) {
  document.querySelectorAll('[data-view-panel]').forEach((panel) => { panel.hidden = panel.dataset.viewPanel !== view })
  document.querySelectorAll('.tab-button').forEach((button) => button.setAttribute('aria-current', String(button.dataset.view === view)))
  setPanel(cityPanel, false)
  setPanel(settingsPanel, false)
  mobileMenuButton.setAttribute('aria-expanded', 'false')
  if (view === 'history') loadHistory()
}

function isoDate(date) {
  return date.toISOString().slice(0, 10)
}

async function loadHistory() {
  if (!historyStart.value || !historyEnd.value) return
  const location = { ...LOCATION }
  const startDate = historyStart.value
  const endDate = historyEnd.value
  const requestId = ++historyRequest
  historyStatus.textContent = 'Загружаю дневник…'
  historyGrid.replaceChildren()
  const apiUrl = new URL('https://archive-api.open-meteo.com/v1/archive')
  apiUrl.search = new URLSearchParams({
    latitude: location.latitude,
    longitude: location.longitude,
    timezone: location.timezone,
    start_date: startDate,
    end_date: endDate,
    daily: 'temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,weather_code',
  }).toString()
  try {
    const response = await fetch(apiUrl)
    if (!response.ok) throw new Error(`Сервис погоды ответил: ${response.status}`)
    const data = await response.json()
    if (requestId !== historyRequest) return
    const maxRain = Math.max(...data.daily.precipitation_sum, 0.1)
    historyGrid.replaceChildren(...data.daily.time.map((date, index) => {
      const parts = dayParts(date)
      const row = document.createElement('article')
      row.className = 'history-day'
      row.innerHTML = `<span class="history-date">${parts.weekday}, ${parts.calendarDate}</span>${iconMarkup(data.daily.weather_code[index])}<span class="history-temp">${signedTemperature(data.daily.temperature_2m_max[index])} / ${signedTemperature(data.daily.temperature_2m_min[index])}</span><span class="history-rain"><i style="width:${Math.max(3, data.daily.precipitation_sum[index] / maxRain * 100)}%"></i><b>${precipitationText(data.daily.precipitation_sum[index])} мм</b></span>`
      return row
    }))
    historyStatus.textContent = `${location.name}: ${startDate} — ${endDate}`
  } catch (error) {
    if (requestId !== historyRequest) return
    historyStatus.textContent = `Не удалось загрузить дневник: ${error.message}`
  }
}

async function loadForecast() {
  const location = { ...LOCATION }
  const requestId = ++forecastRequest
  const apiUrl = new URL('https://api.open-meteo.com/v1/forecast')
  apiUrl.search = new URLSearchParams({
    latitude: location.latitude,
    longitude: location.longitude,
    timezone: location.timezone,
    forecast_days: '12',
    hourly: 'temperature_2m,apparent_temperature,precipitation,snowfall,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code,is_day',
    daily: 'temperature_2m_max,temperature_2m_min,precipitation_sum',
  }).toString()
  const response = await fetch(apiUrl)
  if (!response.ok) throw new Error(`Сервис погоды ответил: ${response.status}`)
  const nextForecast = await response.json()
  if (requestId !== forecastRequest) return
  forecast = nextForecast
  selectedDate = forecast.daily.time.includes(selectedDate) ? selectedDate : forecast.daily.time[0]
  renderDaily()
  renderHourly()
  updatedAt.textContent = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: location.timezone }).format(new Date())
  app.setAttribute('aria-busy', 'false')
}

cityTrigger.addEventListener('click', () => {
  setPanel(cityPanel, cityPanel.hidden)
  setPanel(settingsPanel, false)
})
settingsButton.addEventListener('click', () => {
  setPanel(settingsPanel, settingsPanel.hidden)
  setPanel(cityPanel, false)
})
mobileMenuButton.addEventListener('click', () => {
  const isOpen = cityPanel.hidden
  setPanel(cityPanel, isOpen)
  setPanel(settingsPanel, isOpen)
  mobileMenuButton.setAttribute('aria-expanded', String(isOpen))
})
document.querySelectorAll('[data-field]').forEach((input) => input.addEventListener('change', (event) => {
  event.target.checked ? fields.add(event.target.dataset.field) : fields.delete(event.target.dataset.field)
  updateVisibility()
}))
document.querySelectorAll('.tab-button').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)))
document.querySelector('#history-controls').addEventListener('submit', (event) => {
  event.preventDefault()
  loadHistory()
})
document.querySelector('#city-search').addEventListener('submit', async (event) => {
  event.preventDefault()
  const query = document.querySelector('#city-query').value.trim()
  if (!query) return
  const response = await fetch(`https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&name=${encodeURIComponent(query)}`)
  const result = await response.json()
  const city = result.results?.[0]
  if (!city) {
    updatedAt.textContent = 'Город не найден'
    return
  }
  LOCATION = { name: city.name, latitude: city.latitude, longitude: city.longitude, timezone: city.timezone || 'auto' }
  updateHeader()
  renderCities()
  setPanel(cityPanel, false)
  loadForecast()
})

const yesterday = new Date()
yesterday.setDate(yesterday.getDate() - 1)
const fortnightAgo = new Date(yesterday)
fortnightAgo.setDate(fortnightAgo.getDate() - 13)
historyStart.value = isoDate(fortnightAgo)
historyEnd.value = isoDate(yesterday)
updateHeader()
renderCities()
loadForecast().catch((error) => {
  app.replaceChildren(Object.assign(document.querySelector('#message-template').content.firstElementChild.cloneNode(true), { textContent: `Не удалось загрузить прогноз: ${error.message}. Проверь интернет и попробуй обновить страницу.` }))
  app.setAttribute('aria-busy', 'false')
})
setInterval(() => loadForecast().catch(() => { updatedAt.textContent = 'Не удалось обновить прогноз' }), 60_000)
