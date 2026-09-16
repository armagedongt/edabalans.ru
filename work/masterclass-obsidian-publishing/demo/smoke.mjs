// Optional browser smoke. NODE_PATH must point to an existing Playwright runtime.
import {createRequire} from 'node:module';
import {mkdirSync, writeFileSync} from 'node:fs';
const {chromium} = createRequire(import.meta.url)('playwright');
const out = process.argv[2];
if (!out) throw new Error('Pass a new evidence output directory');
mkdirSync(out); // Refuse overwriting earlier evidence.
const url = 'http://127.0.0.1:8794/material?course_day=1&course_material=local-day-01-md-formatting';
const browser = await chromium.launch();
const reports = [];
try {
  for (const width of [360, 430, 768, 1440]) {
    const context = await browser.newContext({viewport:{width,height:1000}, permissions:['clipboard-read','clipboard-write']});
    const page = await context.newPage();
    await page.goto(url);
    await page.locator('.article-actions').first().waitFor();
    await page.locator('.article-spoiler summary').click();
    if (!await page.locator('.article-spoiler').evaluate(el=>el.open)) throw new Error('Spoiler did not open');
    await page.locator('.article-spoiler').screenshot({path:`${out}/spoiler-open-${width}.png`});
    const expected = await page.locator('.article-copy-block pre code').textContent();
    await page.locator('.article-copy-button').click();
    await page.locator('.article-copy-button').filter({hasText:/^Скопировано$/}).waitFor();
    const copied = await page.evaluate(()=>navigator.clipboard.readText());
    if (copied.replace(/\r\n/g,'\n') !== expected) throw new Error('Wrong copied content: '+JSON.stringify({expected,copied}));
    const state = await page.evaluate(()=>{
      const root=document.querySelector('#article');
      const strike=root.querySelector('del');
      const code=root.querySelector('.article-copy-block pre');
      const button=root.querySelector('.article-copy-button');
      const td=root.querySelector('td');
      const positive=root.querySelector('.article-task:not(.article-task-negative)');
      const negative=root.querySelector('.article-task-negative');
      return {
        width:innerWidth,documentWidth:document.documentElement.scrollWidth,
        strikeColor:getComputedStyle(strike).color,textColor:getComputedStyle(strike.parentElement).color,
        strikeOpacity:getComputedStyle(strike).opacity,
        positive:getComputedStyle(positive,'::before').content,negative:getComputedStyle(negative,'::before').content,
        inputs:root.querySelectorAll('input').length,
        tableCellDisplay:getComputedStyle(td).display,label:td.dataset.label,
        actionsRowDirection:getComputedStyle(root.querySelector('.article-actions-row')).flexDirection,
        actionsStackDirection:getComputedStyle(root.querySelector('.article-actions-stack')).flexDirection,
        actionsStackAlign:getComputedStyle(root.querySelector('.article-actions-stack')).alignItems,
        actionsCenterDirection:getComputedStyle(root.querySelector('.article-actions-center')).flexDirection,
        actionsCenterAlign:getComputedStyle(root.querySelector('.article-actions-center')).alignItems,
        positiveText:positive.textContent,negativeText:negative.textContent,
        copyGap:button.getBoundingClientRect().top-code.getBoundingClientRect().bottom,
      };
    });
    if(state.documentWidth!==width || state.strikeColor!==state.textColor || state.strikeOpacity!=='1' || state.inputs!==0 || state.copyGap<15) throw new Error(JSON.stringify(state));
    if((width<=620 ? 'block':'table-cell')!==state.tableCellDisplay) throw new Error('Wrong table mode');
    if(state.positive!=='"✓"' || state.negative!=='"×"' || !state.positiveText.includes('Работаем с повседневными привычками.') || !state.negativeText.includes('Не назначаем лекарства.')) throw new Error('Reversed status mapping');
    if(state.actionsRowDirection!==(width<=620?'column':'row') || state.actionsStackDirection!=='column' || state.actionsStackAlign!=='flex-start' || state.actionsCenterDirection!=='column' || state.actionsCenterAlign!=='center') throw new Error('Wrong CTA placement');
    await page.locator('.article-data-table').screenshot({path:`${out}/table-${width}.png`});
    await page.locator('.article-copy-block').screenshot({path:`${out}/copy-${width}.png`});
    await page.locator('.article-actions-row').screenshot({path:`${out}/actions-${width}.png`});
    await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied')}}}));
    await page.locator('.article-copy-button').click();
    await page.locator('.article-copy-button').filter({hasText:/^Не скопировано — попробуйте ещё раз$/}).waitFor();
    await page.locator('.article-copy-block').screenshot({path:`${out}/copy-denied-${width}.png`});
    const deniedGap=await page.locator('.article-copy-block').evaluate(el=>el.querySelector('button').getBoundingClientRect().top-el.querySelector('pre').getBoundingClientRect().bottom);
    if(deniedGap<15)throw new Error('Failure button overlaps code');
    reports.push({...state,clipboardExact:true,deniedGap});
    await context.close();
  }
  writeFileSync(`${out}/smoke.json`,JSON.stringify(reports,null,2));
  console.log(JSON.stringify(reports));
} finally {await browser.close();}
