import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const out = process.env.QA_OUT;
assert(out, 'QA_OUT must name a fresh external evidence directory');
await mkdir(out, {recursive: true});

const staticRoot = new URL('../../app/static/', import.meta.url);
const accountFragment = await readFile(new URL('apps/account.html', staticRoot), 'utf8');
const accountCss = await readFile(new URL('account-visual.css', staticRoot), 'utf8');
const accountThemeCss = await readFile(new URL('account-theme.css', staticRoot), 'utf8');
const masterclassCss = await readFile(new URL('masterclass.css', staticRoot), 'utf8');
const programCardCss = await readFile(new URL('public-program-card.css', staticRoot), 'utf8');
const programCardJs = await readFile(new URL('public-program-card.js', staticRoot), 'utf8');
const masterclassJs = await readFile(new URL('masterclass.js', staticRoot), 'utf8');
const manropeFont = (await readFile(new URL('blog/fonts/manrope-cyrillic.woff2', staticRoot))).toString('base64');
const manropeFace = `@font-face{font-family:Manrope;src:url(data:font/woff2;base64,${manropeFont}) format('woff2');font-weight:400 900;font-style:normal;font-display:block}`;

const cleanFragment = accountFragment
  .replace(/<link\b[^>]*>/g, '')
  .replace(/<script\b[^>]*\bsrc=[^>]*><\/script>/g, '');

const accountData = {
  email: 'sergey@example.test',
  state: 'ready',
  legal: {required: false, documents: []},
  courses: [
    {code: 'masterclass', title: 'Мастер-класс по изменению питания и пищевых привычек', summary: '20 дней последовательной программы.', tariff: 'С консультацией', app: 'masterclass-course', owned: true, ready: true, maintenance: false},
    {code: 'calories', title: 'Мини-курс «Калорийный»', summary: 'Практика энергетического баланса.', app: 'calories-course', owned: false, ready: true, maintenance: false, product_code: 'calories'},
  ],
  applications: [
    {code: 'dqs', title: 'Diet Quality Score', summary: 'Оценка качества питания.', app: 'dqs', owned: true, ready: true, maintenance: false, can_resend_link: true},
  ],
};

const offerData = {
  expires_at: null,
  owned_products: [{name: 'Мастер-класс по изменению питания и пищевых привычек', tariff: 'С консультацией'}],
  offers: [
    {code: 'single:recipes', composition: 'single', title: 'Система рецептов', description: 'Как научиться собирать здоровые тарелки быстро, просто и вкусно.', long_description: '', items: ['recipes'], details: [], standard_price: 3900, price: 2900, saving: 1000, saving_percent: 26},
    {code: 'single:calories', composition: 'single', title: 'Мини-курс «Калорийный»', description: 'Как разобраться с калориями без вечной бухгалтерии.', long_description: '', items: ['calories'], details: [], standard_price: 3900, price: 2900, saving: 1000, saving_percent: 26},
    {code: 'single:consultation', composition: 'single', title: 'Индивидуальная консультация', description: 'Разбор дневника питания и понятный следующий шаг.', long_description: '', items: ['consultation'], details: [], standard_price: 8900, price: 7900, saving: 1000, saving_percent: 11},
  ],
  product_presentations: {
    recipes: {name: 'Система рецептов', description: '', canonical_html: '<p>Не отдельная «правильная кухня», а понятный способ собирать еду под обычную жизнь.</p><blockquote><p>Подсказка для обычного дня.</p></blockquote><h2>Что будет внутри</h2><h3>Конструктор блюд</h3><p>Разберём продукты, сочетания и удобные заготовки.</p><h3>Готовая еда</h3><p>Научимся выбирать подходящие варианты в магазине и доставке.</p>'},
    calories: {name: 'Мини-курс «Калорийный»', description: 'Практический курс.', features: [], program: []},
    consultation: {name: 'Индивидуальная консультация', description: 'Разбор вашей ситуации.', features: [], program: []},
  },
  product_offer_actions: {
    recipes: [{composition: 'single', offer_code: 'single:recipes', title: 'Система рецептов', standard_price: 3900, price: 2900, saving: 1000, saving_percent: 26}],
    calories: [], consultation: [],
  },
};

const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});

async function captureAccount() {
  const page = await context.newPage();
  const setup = `<script>
    window.EdabalansIdentity={email:'sergey@example.test',source:'native'};
    window.EdabalansAccountPayload=${JSON.stringify(accountData)};
    window.EdabalansAppHost='http://fixture.test';
    window.EdabalansEmbed={waitUntilReady:function(){},load:function(){return Promise.resolve();}};
    window.fetch=function(url,options){
      var path=String(url), body=options&&options.body?JSON.parse(options.body):{};
      var payload={};
      if(path.indexOf('/messengers?')>=0) payload={linked:{telegram:{linked:true,preferred:true},max:{linked:false,preferred:false}},preferred_platform:'telegram'};
      else if(path.indexOf('/messenger-links')>=0) payload={platform:body.platform,deep_link:'https://example.test/'+body.platform};
      else if(path.indexOf('/account-offers')>=0) payload={focusable_product_codes:['calories']};
      return Promise.resolve(new Response(JSON.stringify(payload),{status:200,headers:{'Content-Type':'application/json'}}));
    };
  </script>`;
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>${manropeFace}${accountCss}</style><style>${accountThemeCss}</style>${setup}${cleanFragment}`, {waitUntil: 'domcontentloaded'});
  await page.locator('.account-messengers-summary').waitFor();
  await page.evaluate(() => document.fonts.ready);
  assert(await page.evaluate(() => document.fonts.check('16px Manrope')), 'Manrope fixture font is unavailable');
  for (const width of [360, 430, 768, 1440]) {
    await page.setViewportSize({width, height: 1000});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `account overflow at ${width}`);
    const lineDisplay = await page.locator('.account-messengers-line').evaluate(el => getComputedStyle(el).display);
    assert.equal(lineDisplay === 'none', width <= 760, `messenger detail visibility at ${width}`);
    if (width <= 430) {
      const summaryBox = await page.locator('.account-messengers-summary').boundingBox();
      const headBox = await page.locator('.account-head').boundingBox();
      assert(summaryBox && summaryBox.height <= 44, `mobile messenger row is too tall at ${width}`);
      assert(headBox && headBox.height <= 175, `mobile account header is too tall at ${width}`);
    } else {
      const [titleBox, sessionBox] = await Promise.all([
        page.locator('.account-title-row h1').boundingBox(),
        page.locator('.account-session').boundingBox(),
      ]);
      assert(titleBox && sessionBox && sessionBox.y < titleBox.y + titleBox.height && sessionBox.y + sessionBox.height > titleBox.y, `desktop title and session are not on one row at ${width}`);
    }
    if (width === 768) {
      const columns = await page.locator('.application-grid').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length);
      assert.equal(columns, 1, 'application cards must use one readable column at 768px');
    }
    await page.screenshot({path: `${out}/account-${width}.png`, fullPage: true});
  }
  await page.setViewportSize({width: 360, height: 1000});
  await page.locator('.account-messengers-summary').click();
  await page.locator('.messenger-editor').waitFor();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path: `${out}/account-messengers-open-360.png`, fullPage: true});
  await page.evaluate(() => { document.documentElement.dataset.accountTheme = 'dark'; });
  await page.screenshot({path: `${out}/account-messengers-open-dark-360.png`, fullPage: true});
  await page.close();
}

async function captureOffers() {
  const page = await context.newPage();
  const setup = `<script>
    window.EdabalansAppContext={app:'masterclass-offers',accountOffer:true,accountUrl:'/lk'};
    window.EdabalansIdentity={email:'sergey@example.test',source:'native'};
    window.fetch=function(){return Promise.resolve(new Response(${JSON.stringify(JSON.stringify(offerData))},{status:200,headers:{'Content-Type':'application/json'}}));};
  </script>`;
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>${manropeFace}</style><style id="edabalans-masterclass-css">${masterclassCss}</style><style>${programCardCss}</style><style>${accountThemeCss}</style><div id="masterclass-offers-app"></div>${setup}<script>${programCardJs}</script><script>${masterclassJs}</script>`, {waitUntil: 'domcontentloaded'});
  await page.locator('.mc-offer-card').first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  assert(await page.evaluate(() => document.fonts.check('16px Manrope')), 'Manrope fixture font is unavailable');
  for (const width of [360, 430, 768, 1440]) {
    await page.setViewportSize({width, height: 1000});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `offers overflow at ${width}`);
    assert((await page.locator('.mc-offer-card').first().evaluate(el => getComputedStyle(el).fontFamily)).startsWith('Manrope'));
    await page.screenshot({path: `${out}/offers-${width}.png`, fullPage: true});
  }
  await page.evaluate(() => { document.documentElement.dataset.accountTheme = 'dark'; });
  await page.setViewportSize({width: 360, height: 1000});
  assert.equal(await page.locator('.mc.mc-offer-page>h1').evaluate(el => getComputedStyle(el).color), 'rgb(237, 241, 245)');
  await page.screenshot({path: `${out}/offers-dark-360.png`, fullPage: true});
  await page.evaluate(() => { document.documentElement.dataset.accountTheme = 'light'; });
  await page.locator('[data-product-info="recipes"]').click();
  await page.locator('.edb-program-card__section').first().waitFor();
  for (const width of [360, 1440]) {
    await page.setViewportSize({width, height: 1000});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `offer details overflow at ${width}`);
    await page.screenshot({path: `${out}/offer-recipes-${width}.png`, fullPage: true});
  }
  await page.evaluate(() => { document.documentElement.dataset.accountTheme = 'dark'; });
  await page.setViewportSize({width: 360, height: 1000});
  assert.equal(await page.locator('.edb-program-card>blockquote').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(38, 52, 66)');
  assert.equal(await page.locator('.edb-program-card>blockquote p').evaluate(el => getComputedStyle(el).color), 'rgb(189, 199, 209)');
  await page.screenshot({path: `${out}/offer-recipes-dark-360.png`, fullPage: true});
  await page.close();
}

async function checkCourseOfferCheckout() {
  const page = await context.newPage();
  const setup = `<script>
    window.EdabalansAppContext={app:'masterclass-offers',accountOffer:false,placement:'day-1-offer',placementToken:'signed-course-placement-token'};
    window.EdabalansIdentity={email:'sergey@example.test',source:'native'};
    window.__checkoutRequests=[];
    HTMLFormElement.prototype.submit=function(){window.__submittedPayment={action:this.action,fields:Object.fromEntries(new FormData(this))};};
    window.fetch=function(url,options){
      if(options&&options.method==='POST'){
        window.__checkoutRequests.push({url:String(url),body:JSON.parse(options.body)});
        return Promise.resolve(new Response(JSON.stringify({payment_form:{action:'https://auth.robokassa.ru/Merchant/Index.aspx',method:'POST',fields:{MerchantLogin:'test',InvId:'123'}}}),{status:200,headers:{'Content-Type':'application/json'}}));
      }
      return Promise.resolve(new Response(${JSON.stringify(JSON.stringify(offerData))},{status:200,headers:{'Content-Type':'application/json'}}));
    };
  </script>`;
  await page.setContent(`<!doctype html><meta charset="utf-8"><style id="edabalans-masterclass-css">${masterclassCss}</style><div id="masterclass-offers-app"></div>${setup}<script>${masterclassJs}</script>`, {waitUntil: 'domcontentloaded'});
  await page.locator('[data-offer="single:recipes"]').click();
  await page.locator('.mc-native-checkout__dialog').waitFor();
  await page.locator('.mc-native-checkout__dialog input[type="checkbox"]').check();
  await page.locator('.mc-native-checkout__submit').click();
  await page.waitForFunction(() => Boolean(window.__submittedPayment));
  const result = await page.evaluate(() => ({requests:window.__checkoutRequests,payment:window.__submittedPayment}));
  assert.equal(result.requests.length, 1);
  assert(result.requests[0].url.endsWith('/api/payments/robokassa/course-offers/checkout'));
  assert.deepEqual(result.requests[0].body, {
    offer_code:'single:recipes',placement:'day-1-offer',placement_token:'signed-course-placement-token'
  });
  assert.equal(result.payment.fields.InvId, '123');
  await page.close();
}

await captureAccount();
await captureOffers();
await checkCourseOfferCheckout();
await browser.close();
