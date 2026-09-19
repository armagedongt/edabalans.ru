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
let selectedHour
let forecastRequest = 0
let historyRequest = 0
let mapMode = 'precipitation'
let mapPlaybackTimer
let weatherMap
let weatherLayer
let mapLocationKey
const mapForecasts = new Map()
const fields = new Set(['air', 'feels', 'precipitation', 'snow'])

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
const mapElement = document.querySelector('#leaflet-map')
const mapStatus = document.querySelector('#map-status')
const mapTime = document.querySelector('#map-time')
const mapPrevious = document.querySelector('#map-previous')
const mapPlay = document.querySelector('#map-play')
const mapNext = document.querySelector('#map-next')
const mapHourRange = document.querySelector('#map-hour-range')
const mapHourOutput = document.querySelector('#map-hour-output')

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
  return `<span class="wind-arrow" aria-hidden="true" style="--wind-turn:${Math.round(degrees) - 90}deg"></span>`
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
      const cell = document.createElement('button')
      cell.className = 'hour'
      cell.type = 'button'
      cell.setAttribute('aria-pressed', String(time === selectedHour))
      cell.setAttribute('aria-label', `Показать карту на ${time.slice(11)}`)
      cell.innerHTML = `<span class="hour-time">${time.slice(11)}</span>${iconMarkup(forecast.hourly.weather_code[index], forecast.hourly.is_day[index])}`
      cell.addEventListener('click', () => selectHour(time))
      return cell
    }),
    ...temperatureCells('air', 'temperature-cell', hours, 'temperature_2m'),
    ...temperatureCells('feels', 'feels-cell', hours, 'apparent_temperature'),
    ...createCells('precipitation', 'precipitation-cell', hours, ({ index }) => `<i class="rain-fill" style="--rain-height:${Math.max(2, forecast.hourly.precipitation[index] / maxRain * 84)}%"></i><span>${precipitationText(forecast.hourly.precipitation[index])}</span>`),
    ...createCells('snow', 'snow-cell', hours, ({ index }) => formatNumber(forecast.hourly.snowfall[index], 1)),
  )
  updateMapControls()
}

function selectDay(date) {
  pauseMapPlayback()
  selectedDate = date
  selectedHour = hoursFor(selectedDate)[0]?.time
  renderDaily()
  renderHourly()
  renderWeatherMap()
}

function selectHour(time) {
  selectedHour = time
  renderHourly()
  renderWeatherMap()
}

function updateMapControls() {
  const hours = selectedDate ? hoursFor(selectedDate) : []
  const hourIndex = Math.max(0, hours.findIndex(({ time }) => time === selectedHour))
  const isSingleHour = hours.length <= 1
  mapHourRange.max = String(Math.max(0, hours.length - 1))
  mapHourRange.value = String(hourIndex)
  mapHourRange.disabled = isSingleHour
  mapPlay.disabled = isSingleHour
  mapHourOutput.textContent = hours[hourIndex]?.time.slice(11) || '—'
  mapPrevious.disabled = isSingleHour || hourIndex === 0
  mapNext.disabled = isSingleHour || hourIndex === hours.length - 1
}

function pauseMapPlayback() {
  if (mapPlaybackTimer) window.clearInterval(mapPlaybackTimer)
  mapPlaybackTimer = undefined
  mapPlay.textContent = '▶'
  mapPlay.setAttribute('aria-pressed', 'false')
  mapPlay.setAttribute('aria-label', 'Воспроизвести изменения по часам')
}

function stepMapHour(direction) {
  if (!forecast || !selectedDate) return true
  const hours = hoursFor(selectedDate)
  const currentIndex = hours.findIndex(({ time }) => time === selectedHour)
  const nextIndex = Math.min(hours.length - 1, Math.max(0, currentIndex + direction))
  if (nextIndex !== currentIndex) selectHour(hours[nextIndex].time)
  return nextIndex === hours.length - 1
}

function toggleMapPlayback() {
  if (mapPlay.disabled) return
  if (mapPlaybackTimer) {
    pauseMapPlayback()
    return
  }
  if (stepMapHour(0)) selectHour(hoursFor(selectedDate)[0].time)
  mapPlaybackTimer = window.setInterval(() => {
    if (stepMapHour(1)) pauseMapPlayback()
  }, 850)
  mapPlay.textContent = '❚❚'
  mapPlay.setAttribute('aria-pressed', 'true')
  mapPlay.setAttribute('aria-label', 'Остановить воспроизведение')
}

function mapPoints() {
  const points = []
  const latitudeStep = 0.24
  const longitudeStep = latitudeStep / Math.max(Math.cos(LOCATION.latitude * Math.PI / 180), 0.35)
  for (let row = -2; row <= 2; row += 1) {
    for (let column = -2; column <= 2; column += 1) {
      points.push({
        latitude: Number((LOCATION.latitude - row * latitudeStep).toFixed(4)),
        longitude: Number((LOCATION.longitude + column * longitudeStep).toFixed(4)),
        row: row + 2,
        column: column + 2,
      })
    }
  }
  return points
}

function ensureWeatherMap() {
  if (weatherMap) return
  if (!window.L) throw new Error('не загрузилась географическая подложка')
  weatherMap = window.L.map(mapElement, { zoomControl: true, attributionControl: true, preferCanvas: true })
  window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(weatherMap)
  weatherLayer = window.L.layerGroup().addTo(weatherMap)
}

function mapDayKey() {
  return `${LOCATION.latitude}:${LOCATION.longitude}:${selectedDate}`
}

async function mapForecastForSelectedDay() {
  const key = mapDayKey()
  const cached = mapForecasts.get(key)
  if (cached?.data && Date.now() - cached.loadedAt < 60_000) return cached.data
  if (cached?.promise) return cached.promise

  const points = mapPoints()
  const request = new URL('https://api.open-meteo.com/v1/forecast')
  request.search = new URLSearchParams({
    latitude: points.map((point) => point.latitude).join(','),
    longitude: points.map((point) => point.longitude).join(','),
    timezone: LOCATION.timezone,
    wind_speed_unit: 'ms',
    start_date: selectedDate,
    end_date: selectedDate,
    hourly: 'precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m',
  }).toString()
  const promise = fetch(request)
    .then((response) => {
      if (!response.ok) throw new Error(`Сервис погоды ответил: ${response.status}`)
      return response.json()
    })
    .then((payload) => {
      const data = Array.isArray(payload) ? payload : [payload]
      mapForecasts.set(key, { data, loadedAt: Date.now() })
      return data
    })

  mapForecasts.set(key, { promise })
  try {
    return await promise
  } catch (error) {
    mapForecasts.delete(key)
    throw error
  }
}

function addWeatherPoint(point, data, hourIndex, maximumPrecipitation) {
  const hourly = data.hourly
  const precipitation = hourly.precipitation[hourIndex]
  const wind = hourly.wind_speed_10m[hourIndex]
  const gust = hourly.wind_gusts_10m[hourIndex]
  const direction = hourly.wind_direction_10m[hourIndex]
  if (mapMode === 'wind') {
    const icon = window.L.divIcon({
      className: 'weather-wind-icon',
      iconSize: [62, 44],
      iconAnchor: [31, 22],
      html: `<span class="wind-arrow" aria-hidden="true" style="--wind-turn:${Math.round(direction) - 90}deg"></span><b>${formatNumber(wind, 1)} м/с</b><small>${formatNumber(wind * 3.6)} км/ч · порывы ${formatNumber(gust, 1)}</small>`,
    })
    window.L.marker([point.latitude, point.longitude], { icon, interactive: false }).addTo(weatherLayer)
    return
  }
  if (precipitation <= 0) return
  const intensity = Math.min(1, precipitation / maximumPrecipitation)
  window.L.circleMarker([point.latitude, point.longitude], {
    radius: 7 + intensity * 15,
    color: '#157dbb',
    weight: 1,
    fillColor: '#37a5e6',
    fillOpacity: .24 + intensity * .46,
    interactive: false,
  }).bindTooltip(`${precipitationText(precipitation)} мм`, {
    permanent: true,
    direction: 'center',
    className: 'weather-rain-label',
  }).addTo(weatherLayer)
}

async function renderWeatherMap() {
  if (!selectedHour) return
  const requestHour = selectedHour
  const requestLocation = `${LOCATION.latitude}:${LOCATION.longitude}`
  mapStatus.hidden = false
  mapStatus.textContent = 'Загружаю карту прогноза…'
  const parts = dayParts(selectedDate)
  mapTime.textContent = `${parts.weekday}, ${parts.calendarDate} · ${selectedHour.slice(11)}`
  try {
    const data = await mapForecastForSelectedDay()
    if (requestHour !== selectedHour || requestLocation !== `${LOCATION.latitude}:${LOCATION.longitude}`) return
    const hourIndex = data[0]?.hourly.time.indexOf(selectedHour)
    if (hourIndex === undefined || hourIndex < 0) throw new Error('не найден выбранный час')
    ensureWeatherMap()
    const locationKey = `${LOCATION.latitude}:${LOCATION.longitude}`
    if (mapLocationKey !== locationKey) {
      weatherMap.setView([LOCATION.latitude, LOCATION.longitude], 9, { animate: false })
      mapLocationKey = locationKey
    }
    weatherLayer.clearLayers()
    const points = mapPoints()
    const maximumPrecipitation = Math.max(...data.map((item) => item.hourly.precipitation[hourIndex]), 0.1)
    points.forEach((point, index) => addWeatherPoint(point, data[index], hourIndex, maximumPrecipitation))
    window.L.circleMarker([LOCATION.latitude, LOCATION.longitude], {
      radius: 7,
      color: '#087eea',
      weight: 2,
      fillColor: '#fff',
      fillOpacity: 1,
      interactive: false,
    }).bindTooltip(LOCATION.name, { permanent: true, direction: 'bottom', className: 'weather-city-label' }).addTo(weatherLayer)
    window.requestAnimationFrame(() => weatherMap.invalidateSize())
    mapStatus.hidden = true
  } catch (error) {
    if (requestHour !== selectedHour || requestLocation !== `${LOCATION.latitude}:${LOCATION.longitude}`) return
    if (weatherLayer) weatherLayer.clearLayers()
    mapStatus.textContent = `Не удалось загрузить карту: ${error.message}`
  }
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
      pauseMapPlayback()
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
    wind_speed_unit: 'ms',
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
    wind_speed_unit: 'ms',
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
  selectedHour = forecast.hourly.time.includes(selectedHour) && selectedHour.startsWith(selectedDate)
    ? selectedHour
    : hoursFor(selectedDate)[0]?.time
  renderDaily()
  renderHourly()
  renderWeatherMap()
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
document.querySelectorAll('.map-tab').forEach((button) => button.addEventListener('click', () => {
  mapMode = button.dataset.mapMode
  document.querySelectorAll('.map-tab').forEach((tab) => tab.setAttribute('aria-pressed', String(tab === button)))
  renderWeatherMap()
}))
mapPrevious.addEventListener('click', () => {
  pauseMapPlayback()
  stepMapHour(-1)
})
mapNext.addEventListener('click', () => {
  pauseMapPlayback()
  stepMapHour(1)
})
mapPlay.addEventListener('click', toggleMapPlayback)
mapHourRange.addEventListener('input', () => {
  pauseMapPlayback()
  const hour = hoursFor(selectedDate)[Number(mapHourRange.value)]
  if (hour) selectHour(hour.time)
})
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
