const CITIES = [{name:'Санкт-Петербург',latitude:59.9343,longitude:30.3351,timezone:'Europe/Moscow'},{name:'Москва',latitude:55.7558,longitude:37.6173,timezone:'Europe/Moscow'},{name:'Кейптаун',latitude:-33.9249,longitude:18.4241,timezone:'Africa/Johannesburg'},{name:'Геленджик',latitude:44.5609,longitude:38.0767,timezone:'Europe/Moscow'},{name:'Кутаиси',latitude:42.2679,longitude:42.6946,timezone:'Asia/Tbilisi'}]
let LOCATION = CITIES[0]

const app = document.querySelector('#weather-app')
const dailyGrid = document.querySelector('#daily-grid')
const hourlyGrid = document.querySelector('#hourly-grid')
const selectedDateLabel = document.querySelector('#selected-date-label')
const settingsButton = document.querySelector('#settings-button')
const settingsPanel = document.querySelector('#settings-panel')
const todayButton = document.querySelector('#today-button')
const updatedAt = document.querySelector('#updated-at')
const cityList = document.querySelector('#city-list')
const fields = new Set(['air', 'feels', 'wind', 'precipitation', 'snow'])
let forecast
let selectedDate

function formatNumber(value, digits = 0) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value)
}

function signedTemperature(value) { return `${value > 0 ? '+' : ''}${Math.round(value)}` }
function precipitationText(value) { return value > 0 && value < 0.1 ? '< 0,1' : formatNumber(value, 1) }

function iconFor(code, isDay = 1) {
  if (code >= 71) return '❄︎'
  if (code >= 51) return '☂︎'
  if (code >= 3) return '☁︎'
  return isDay ? '☀︎' : '☾'
}

function dayLabel(date) {
  return new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'short', timeZone: LOCATION.timezone }).format(new Date(`${date}T12:00:00+03:00`)).replace('.', '')
}

function dayParts(date) {
  const value = new Date(`${date}T12:00:00+03:00`)
  const weekday = new Intl.DateTimeFormat('ru-RU', { weekday: 'short', timeZone: LOCATION.timezone }).format(value).replace('.', '')
  const calendarDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: LOCATION.timezone }).format(value)
  return { weekday: weekday[0].toUpperCase() + weekday.slice(1), calendarDate, weekend: value.getDay() === 0 || value.getDay() === 6 }
}

function hoursFor(date) {
  return forecast.hourly.time.map((time, index) => ({ time, index })).filter(({ time }) => time.startsWith(date))
}

function dailyIndex(date) { return forecast.daily.time.indexOf(date) }

function renderDaily() {
  const maxDaily = Math.max(...forecast.daily.precipitation_sum, 1)
  dailyGrid.replaceChildren(...forecast.daily.time.map((date, index) => {
    const details = dayParts(date)
    const hours = hoursFor(date)
    const values = hours.map(({ index: hourIndex }) => forecast.hourly.precipitation[hourIndex])
    const maxHourly = Math.max(...values, 0.1)
    const dailyHeight = Math.max(3, forecast.daily.precipitation_sum[index] / maxDaily * 78)
    const button = document.createElement('button')
    button.className = 'day-button'
    button.type = 'button'
    button.dataset.date = date
    button.setAttribute('aria-pressed', String(date === selectedDate))
    button.setAttribute('aria-label', `${dayLabel(date)}: осадки ${precipitationText(forecast.daily.precipitation_sum[index])} мм`)
    button.innerHTML = `
      <span class="weekday ${details.weekend ? 'weekend' : ''}">${details.weekday}</span>
      <span class="calendar-date ${details.weekend ? 'weekend' : ''}">${details.calendarDate}</span>
      <span class="weather-icon">${iconFor(forecast.hourly.weather_code[hours[12]?.index ?? hours[0].index])}</span>
      <span class="temperatures"><span class="temperature max">${signedTemperature(forecast.daily.temperature_2m_max[index])}</span><span class="temperature min">${signedTemperature(forecast.daily.temperature_2m_min[index])}</span></span>
      <span class="daily-total">${precipitationText(forecast.daily.precipitation_sum[index])}</span>
      <span class="mini-rain" style="height:${dailyHeight}px">${values.map((value) => `<i style="height:${Math.max(2, value / maxHourly * 100)}%"></i>`).join('')}</span>`
    button.addEventListener('click', () => selectDay(date))
    return button
  }))
}

function windArrow(degrees) { return `↖${Math.round(degrees / 45) ? '' : ''}`.replace('↖', ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖'][Math.round(degrees / 45) % 8]) }

function createLabel(text, field) {
  const label = document.createElement('div')
  label.className = `field-label ${fields.has(field) ? '' : 'hidden-field'}`
  label.dataset.field = field
  label.textContent = text
  return label
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
      cell.innerHTML = `<span class="hour-time">${time.slice(11)}</span><span class="weather-icon">${iconFor(forecast.hourly.weather_code[index], forecast.hourly.is_day[index])}</span>`
      return cell
    }),
    createLabel('Температура воздуха, °C', 'air'),
    ...createCells('air', 'temperature-cell', hours, ({ index }) => signedTemperature(forecast.hourly.temperature_2m[index])),
    createLabel('Температура по ощущению, °C', 'feels'),
    ...createCells('feels', 'feels-cell', hours, ({ index }) => signedTemperature(forecast.hourly.apparent_temperature[index])),
    createLabel('Ветер и порывы, м/с', 'wind'),
    ...createCells('wind', 'wind-cell', hours, ({ index }) => `<span class="wind-pair">${formatNumber(forecast.hourly.wind_speed_10m[index])} / ${formatNumber(forecast.hourly.wind_gusts_10m[index])}</span><span class="gust">${windArrow(forecast.hourly.wind_direction_10m[index])}</span>`),
    createLabel('Осадки в жидком эквиваленте, мм', 'precipitation'),
    ...createCells('precipitation', 'precipitation-cell', hours, ({ index }) => `<i class="rain-fill" style="--rain-height:${Math.max(2, forecast.hourly.precipitation[index] / maxRain * 88)}%"></i><span>${precipitationText(forecast.hourly.precipitation[index])}</span>`),
    createLabel('Выпадающий снег, см', 'snow'),
    ...createCells('snow', 'snow-cell', hours, ({ index }) => formatNumber(forecast.hourly.snowfall[index], 1)),
  )
  selectedDateLabel.textContent = dayLabel(selectedDate)
}

function selectDay(date) {
  selectedDate = date
  renderDaily()
  renderHourly()
  const selected = dailyGrid.querySelector('[aria-pressed="true"]')
  selected?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
}

function updateVisibility() {
  document.querySelectorAll('.field-label[data-field], .cell[data-field]').forEach((node) => node.classList.toggle('hidden-field', !fields.has(node.dataset.field)))
}

async function loadForecast() {
  const apiUrl = new URL('https://api.open-meteo.com/v1/forecast')
  apiUrl.search = new URLSearchParams({...LOCATION,forecast_days:'10',hourly:'temperature_2m,apparent_temperature,precipitation,snowfall,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code,is_day',daily:'temperature_2m_max,temperature_2m_min,precipitation_sum'}).toString()
  const response = await fetch(apiUrl)
  if (!response.ok) throw new Error(`Сервис погоды ответил: ${response.status}`)
  forecast = await response.json()
  selectedDate = forecast.daily.time[0]
  renderDaily()
  renderHourly()
  updatedAt.textContent = `Обновлено ${new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: LOCATION.timezone }).format(new Date())}`
  app.setAttribute('aria-busy', 'false')
}

function renderCities(){cityList.replaceChildren(...CITIES.map((city)=>{const button=document.createElement('button');button.type='button';button.textContent=city.name;button.setAttribute('aria-current',String(city.name===LOCATION.name));button.onclick=()=>{LOCATION=city;document.querySelector('.eyebrow').textContent=city.name;document.title=`Погода в ${city.name}`;renderCities();loadForecast()};return button}))}

settingsButton.addEventListener('click', () => {
  const isOpen = !settingsPanel.hidden
  settingsPanel.hidden = isOpen
  settingsButton.setAttribute('aria-expanded', String(!isOpen))
})
document.querySelectorAll('[data-field]').forEach((input) => input.addEventListener('change', (event) => {
  event.target.checked ? fields.add(event.target.dataset.field) : fields.delete(event.target.dataset.field)
  updateVisibility()
}))
todayButton.addEventListener('click', () => selectDay(forecast.daily.time[0]))
document.querySelector('#city-search').addEventListener('submit',async(event)=>{event.preventDefault();const query=document.querySelector('#city-query').value.trim();if(!query)return;const response=await fetch(`https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&name=${encodeURIComponent(query)}`);const result=await response.json();const city=result.results?.[0];if(!city){updatedAt.textContent='Город не найден';return}LOCATION={name:city.name,latitude:city.latitude,longitude:city.longitude,timezone:city.timezone||'auto'};document.querySelector('.eyebrow').textContent=LOCATION.name;renderCities();loadForecast()})

renderCities()
loadForecast().catch((error) => {
  app.replaceChildren(Object.assign(document.querySelector('#message-template').content.firstElementChild.cloneNode(true), { textContent: `Не удалось загрузить прогноз: ${error.message}. Проверь интернет и попробуй обновить страницу.` }))
  app.setAttribute('aria-busy', 'false')
})
setInterval(() => loadForecast().catch(() => { updatedAt.textContent = 'Не удалось обновить прогноз' }), 60_000)
