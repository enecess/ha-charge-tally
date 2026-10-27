import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createCardFixture} from './card-fixture.mjs';

const button=page=>page.getByRole('button',{name:'Export PDF',exact:true});
async function openStatistics(page){await page.evaluate(()=>fixture.card.setExpanded('statistics',true));assert.equal(await page.locator('[data-export-pdf]').count(),1,'Statistics exposes PDF export');}
async function pdfResponse(page,index=0){await page.evaluate(index=>fixture.exports[index].resolve(new Response('%PDF-1.7\nclick snapshot',{headers:{'Content-Type':'application/pdf','Content-Disposition':'attachment; filename="charge-tally-20261027T120000Z.pdf"'}})),index);}
async function settle(page){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}

test('export_uses_applied_range_not_date_draft',async t=>{
  const {page}=await createCardFixture(t,{show_chart:false});await openStatistics(page);
  await page.evaluate(()=>fixture.card.setPeriod('custom'));
  assert.equal(await button(page).isDisabled(),true);
  const dates=page.locator('input[type=date]');
  await dates.nth(0).fill('2026-09-01');await dates.nth(1).fill('2026-09-02');
  await page.getByRole('button',{name:'Apply range',exact:true}).click();
  await dates.nth(0).fill('2026-09-10');await dates.nth(1).fill('');
  await button(page).click();
  assert.deepEqual(await page.evaluate(()=>fixture.exports[0].payload),{start:'2026-09-01T00:00:00.000Z',end:'2026-09-02T00:00:00.000Z',language:'en'});
  const downloaded=page.waitForEvent('download');await pdfResponse(page);const download=await downloaded;
  assert.equal(download.suggestedFilename(),'charge-tally-20261027T120000Z.pdf');
  assert.equal((await readFile(await download.path(),'utf8')),'%PDF-1.7\nclick snapshot');
  assert.deepEqual(await page.evaluate(()=>fixture.urls.revoked),await page.evaluate(()=>fixture.urls.created));
});

test('export_works_without_records_panel_and_beyond_page_one',async t=>{
  const {page}=await createCardFixture(t,{show_records:false});await openStatistics(page);
  await page.evaluate(()=>{fixture.card.setOffset(50);fixture.card.setPeriod('total');});
  await button(page).click();
  assert.deepEqual(await page.evaluate(()=>fixture.exports[0].payload),{calendar_period:'total',language:'en'});
  assert.equal(await page.locator('[data-section=records]').isVisible(),false);
  assert.equal(await page.evaluate(()=>fixture.exports[0].url),'/api/charge_tally/export.pdf');
});

test('double click sends once and filter changes and snapshots preserve the pending download',async t=>{
  const {page}=await createCardFixture(t);await openStatistics(page);
  await page.evaluate(()=>{fixture.card.setFilter('identity_id','i');fixture.card.hass={...fixture.hass,language:'de-DE'};});
  await page.getByRole('button',{name:'PDF exportieren',exact:true}).evaluate(node=>{node.click();node.click();});
  assert.equal(await page.getByRole('button',{name:'PDF wird exportiert…',exact:true}).isDisabled(),true);
  await page.evaluate(()=>{fixture.card.setFilter('identity_id','j');fixture.card.onSnapshot({...fixture.snapshot,generation:2});fixture.card.busy=true;});
  assert.equal(await page.evaluate(()=>fixture.exports.length),1);
  assert.deepEqual(await page.evaluate(()=>fixture.exports[0].payload),{identity_id:'i',calendar_period:'daily',language:'de-DE'});
  assert.equal(await page.evaluate(()=>fixture.exports[0].options.signal.aborted),false);
  const downloaded=page.waitForEvent('download');await pdfResponse(page);await downloaded;
  assert.equal(await page.evaluate(()=>fixture.card.busy),true);
  assert.equal(await page.getByRole('button',{name:'PDF exportieren',exact:true}).isEnabled(),true);
});

for(const exit of ['disconnected','removed','unloaded'])test(`${exit} aborts export and ignores late responses without leaking URLs`,async t=>{
  const {page}=await createCardFixture(t);await openStatistics(page);let downloads=0;page.on('download',()=>downloads++);
  await button(page).click();
  await page.evaluate(exit=>{
    if(exit==='removed')fixture.card.remove();
    else if(exit==='unloaded')fixture.card.onSnapshot(null);
    else{fixture.hass.connection.connected=false;fixture.listeners.get('disconnected')();}
  },exit);
  assert.equal(await page.evaluate(()=>fixture.exports[0].options.signal.aborted),true);
  assert.equal(await page.evaluate(()=>fixture.card.exportBusy),false);
  await pdfResponse(page);await settle(page);
  assert.equal(downloads,0);assert.deepEqual(await page.evaluate(()=>fixture.urls),{created:[],revoked:[]});
  if(exit!=='removed')assert.equal(await button(page).isDisabled(),true);
});

test('a pending export still downloads after switching to an unapplied custom range',async t=>{
  const {page}=await createCardFixture(t);await openStatistics(page);await button(page).click();
  await page.evaluate(()=>fixture.card.setPeriod('custom'));
  assert.deepEqual(await page.evaluate(()=>fixture.exports[0].payload),{calendar_period:'daily',language:'en'});
  const downloaded=page.waitForEvent('download',{timeout:1500});await pdfResponse(page);await downloaded;
  assert.equal(await button(page).isDisabled(),true);
});

test('a replacement export owns busy state when an aborted response arrives late',async t=>{
  const {page}=await createCardFixture(t);await openStatistics(page);await button(page).click();
  await page.evaluate(()=>{fixture.card.onSnapshot(null);fixture.card.onSnapshot(fixture.snapshot);});
  await button(page).click();await pdfResponse(page,0);await settle(page);
  assert.equal(await page.evaluate(()=>fixture.card.exportBusy),true);
  const downloaded=page.waitForEvent('download');await pdfResponse(page,1);await downloaded;
  assert.equal(await page.evaluate(()=>fixture.urls.created.length),1);
  assert.deepEqual(await page.evaluate(()=>fixture.urls.revoked),await page.evaluate(()=>fixture.urls.created));
});

test('export failure is localized and retry restores its button without changing other errors',async t=>{
  const {page}=await createCardFixture(t);await openStatistics(page);
  await page.evaluate(()=>{fixture.card.error={code:'range'};fixture.card.render();});
  await button(page).click();
  await page.evaluate(()=>fixture.exports[0].resolve(Response.json({error:{code:'export_missing_glyph',details:{field:'note',row:2,codepoints:['U+1F600']},message:'private server text'}},{status:422})));
  await page.getByRole('alert').filter({hasText:'Row 2, Note'}).waitFor();
  assert.match(await page.getByRole('alert').filter({hasText:'Row 2, Note'}).textContent(),/U\+1F600/);
  assert.equal(await page.evaluate(()=>fixture.card.error.code),'range');
  assert.equal(await button(page).isEnabled(),true);
  await button(page).click();
  await page.evaluate(()=>fixture.exports[1].resolve(Response.json({error:{code:'export_too_large'}},{status:413})));
  await page.getByRole('alert').filter({hasText:'shorter period'}).waitFor();
  await button(page).click();await page.evaluate(()=>fixture.exports[2].resolve(new Response('<html>private server text</html>')));
  await page.getByRole('alert').filter({hasText:'PDF export failed'}).waitFor();
  assert.doesNotMatch(await page.locator('charge-tally-card').textContent(),/private server text/);
});

test('export button stays visible and within a narrow screen in all six languages',async t=>{
  const {page}=await createCardFixture(t,{show_records:false});await page.setViewportSize({width:320,height:740});await openStatistics(page);
  for(const language of ['en','zh-Hans','de','fr','pl','it']){
    await page.evaluate(language=>{fixture.card.hass={...fixture.hass,language};},language);
    const bounds=await page.locator('[data-export-pdf]').boundingBox();
    assert.ok(bounds&&bounds.width>0&&bounds.x>=0&&bounds.x+bounds.width<=320,language);
    assert.equal(await page.locator('[data-export-pdf]').isVisible(),true);
  }
  await page.screenshot({path:'.superpowers/sdd/2026-10-27-currency-identity-pdf/task6-narrow-export.png',fullPage:true});
});
