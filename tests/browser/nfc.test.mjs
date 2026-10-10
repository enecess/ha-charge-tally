import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {createNfcFixture} from './nfc-fixture.mjs';

async function createRule(page){
  await page.locator('[data-action="new"]').click();
  await page.locator('[data-field="tag"]').selectOption('t');
  await page.locator('[data-field="point"]').selectOption('p');
  await page.locator('[data-action="add-device"]').click();
  await page.locator('[data-field="device"]').selectOption('d1');
  await page.locator('[data-field="identity"]').selectOption('i');
  await page.locator('[data-field="default"]').selectOption('j');
  await page.locator('[data-action="save"]').click();
  await page.locator('dialog [data-action="confirm"]').click();
  await page.waitForFunction(()=>window.fixture.rules[0]?.applied);
}

test('NFC admin creates stable device/default mappings and preserves drafts on refresh',async t=>{
  const {page}=await createNfcFixture(t);
  await createRule(page);
  if(process.env.NFC_SCREENSHOT_DIR){
    await mkdir(process.env.NFC_SCREENSHOT_DIR,{recursive:true});
    await page.screenshot({path:process.env.NFC_SCREENSHOT_DIR+'/nfc-links.png',fullPage:true});
  }
  assert.deepEqual(await page.evaluate(()=>window.fixture.rules[0].applied.draft),{
    tag_id:'t',point_id:'p',device_bindings:[{device_id:'d1',identity_id:'i'}],default_identity_id:'j',
  });
  await page.locator('[data-action="edit"]').click();
  await page.locator('[data-field="default"]').selectOption('');
  await page.locator('[data-action="refresh"]').click();
  assert.equal(await page.locator('[data-field="default"]').inputValue(),'');
  assert.equal(await page.evaluate(()=>window.fixture.posts),1);
});

test('NFC editor handles lost responses, external changes, pause and explicit delete',async t=>{
  const {page}=await createNfcFixture(t);
  await page.evaluate(()=>{window.fixture.lost=true;});
  await page.locator('[data-action="new"]').click();
  await page.locator('[data-field="tag"]').selectOption('t');
  await page.locator('[data-field="point"]').selectOption('p');
  await page.locator('[data-field="default"]').selectOption('i');
  await page.locator('[data-action="save"]').click();
  await page.locator('dialog [data-action="confirm"]').click();
  await page.locator('[data-action="resume"]').click();
  await page.waitForFunction(()=>window.fixture.rules[0]?.applied);
  assert.equal(await page.evaluate(()=>window.fixture.posts),1);
  await page.evaluate(()=>{window.fixture.external=true;window.fixture.paused=true;window.fixture.configs.a.actions=[];});
  await page.locator('[data-action="refresh"]').click();
  await page.locator('[data-action="restore"]').click();
  await page.locator('[data-action="save"]').click();
  await page.locator('dialog [data-action="confirm"]').click();
  await page.waitForFunction(()=>window.fixture.posts===2);
  assert.equal(await page.evaluate(()=>window.fixture.paused),true);
  await page.locator('[data-action="delete"]').click();
  await page.locator('dialog [data-action="confirm"]').click();
  await page.waitForFunction(()=>window.fixture.rules.length===0);
});

test('NFC pending deletion with external changes can be cancelled and repaired explicitly',async t=>{
  const {page}=await createNfcFixture(t);
  await createRule(page);
  await page.evaluate(async()=>{
    const f=window.fixture,r=f.rules[0];
    await f.hass.callWS({type:'charge_tally/nfc/prepare',kind:'delete',rule_id:r.rule_id,operation_id:'delete'});
    r.deleting=true;f.external=true;f.configs.a.actions=[];
    f.catalog.devices=[];
  });
  await page.locator('[data-action="refresh"]').click();
  assert.equal(await page.locator('[data-action="discard"]').count(),1);
  await page.locator('[data-action="discard"]').click();
  await page.locator('dialog [data-action="confirm"]').click();
  await page.locator('[data-action="restore"]').click();
  await page.locator('[data-action="remove-device"]').click();
  await page.locator('[data-action="save"]').click();
  assert.match(await page.locator('dialog').innerText(),/Restore/);
  assert.equal(await page.evaluate(()=>window.fixture.posts),1);
  await page.locator('dialog [data-action="confirm"]').click();
  await page.waitForFunction(()=>window.fixture.posts===2);
  assert.deepEqual(await page.evaluate(()=>window.fixture.rules[0].applied.draft.device_bindings),[]);
});

test('NFC manager is readable in six languages at 390px and renders names as text',async t=>{
  const {page}=await createNfcFixture(t);
  await page.evaluate(()=>{window.fixture.catalog.tags[0].name='<script>window.injected=true</script>';});
  for(const [language,title] of [
    ['en','NFC identity links'],['zh-Hans','NFC 身份联动'],['de','NFC-Identitätsverknüpfungen'],
    ['fr','Associations d’identité NFC'],['pl','Powiązania tożsamości NFC'],['it','Collegamenti identità NFC'],
  ]){
    await page.evaluate(language=>{window.fixture.hass.language=language;window.fixture.panel.hass=window.fixture.hass;},language);
    await page.locator('[data-action="refresh"]').click();
    await page.locator('[data-action="new"]').click();
    assert.equal(await page.locator('h1').innerText(),title);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,language);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    if(process.env.NFC_SCREENSHOT_DIR){
      await mkdir(process.env.NFC_SCREENSHOT_DIR,{recursive:true});
      await page.screenshot({path:process.env.NFC_SCREENSHOT_DIR+'/nfc-'+language+'.png',fullPage:true});
    }
    await page.locator('[data-action="cancel"]').click();
  }
});

test('NFC live pause is shown without losing the edited identity and revocation clears access',async t=>{
  const {page}=await createNfcFixture(t);
  await createRule(page);
  await page.locator('[data-action="edit"]').click();
  await page.locator('[data-field="default"]').selectOption('');
  await page.locator('[data-field="default"]').focus();
  await page.evaluate(()=>{
    const f=window.fixture;
    f.hass.states={'automation.managed':{state:'off'}};
    f.panel.hass=f.hass;
  });
  assert.match(await page.locator('.status').innerText(),/Paused/);
  assert.equal(await page.locator('[data-field="default"]').inputValue(),'');
  assert.equal(await page.locator('[data-field="default"]').evaluate(el=>el===el.getRootNode().activeElement),true);
  await page.evaluate(()=>{window.fixture.hass.user.is_admin=false;window.fixture.panel.hass=window.fixture.hass;});
  assert.equal(await page.locator('article').count(),0);
  assert.equal(await page.locator('[data-action="new"]').isDisabled(),true);
});
