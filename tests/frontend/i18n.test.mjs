import test from 'node:test';
import assert from 'node:assert/strict';
import {cp,mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {tr} from '../../custom_components/charge_tally/www/card-i18n.js';
import {errorMessage,formatCost,formatDecimal} from '../../custom_components/charge_tally/www/card-state.js';

test('regional HA languages select localized card text', () => {
  for (const [language,expected] of [['de-DE','Ladepunkt'],['fr-CA','Point de recharge'],['pl-PL','Punkt ładowania'],['it','Punto di ricarica'],['it-IT','Punto di ricarica'],['it-CH','Punto di ricarica']]) {
    assert.equal(tr('point',language),expected);
  }
  assert.equal(tr('point','DE_de'),'Ladepunkt');
  assert.equal(tr('point','IT_it'),'Punto di ricarica');
  assert.equal(tr('point','zh-CN'),'充电点');
  assert.equal(tr('point','en-GB'),'Charging point');
});
test('compact record issues and native section titles follow every supported language',()=>{
  for(const [language,title,unknown,seconds]of [['en','Fee details','Cost to be added','Missing energy data · about 5 s'],['zh-Hans','费用明细','费用待补充','电量数据缺失约 5 秒'],['de','Kostendetails','Kosten ergänzen','Fehlende Energiedaten · etwa 5 s'],['fr','Détail des coûts','Coût à compléter','Données d’énergie manquantes · environ 5 s'],['pl','Szczegóły opłat','Koszt do uzupełnienia','Brak danych energii · około 5 s'],['it','Dettaglio dei costi','Costo da completare','Dati energetici mancanti · circa 5 s']]){
    assert.equal(tr('feeDetails',language),title);
    assert.equal(tr('amountMissing',language),unknown);
    assert.equal(tr('dataGap',language,{seconds:5}),seconds);
  }
});

test('unsupported or invalid languages and unknown keys have safe fallbacks', () => {
  for (const language of ['es-MX','',null,'invalid_locale_!']) assert.equal(tr('point',language),'Charging point');
  for (const key of ['future_quality','constructor','__proto__']) assert.equal(tr(key,'de'),key);
  assert.equal(formatDecimal('1234.5','invalid_locale_!'),'1,234.5');
});

test('errors are localized and unknown server messages are not rendered', () => {
  assert.match(errorMessage({code:'range'},'de-AT'),/Ende.*Beginn/);
  assert.match(errorMessage({code:'range'},'fr'),/fin.*début/);
  assert.match(errorMessage({code:'range'},'pl'),/koniec|zakończenia/i);
  assert.match(errorMessage({code:'range'},'it'),/fine.*inizio/);
  for (const language of ['de','fr','pl','it']) {
    assert.notEqual(errorMessage({code:'stale_preview'},language),errorMessage({code:'stale_preview'},'en'));
    const unknown=errorMessage({code:'<script>',message:'sensitive server details'},language);
    assert.doesNotMatch(unknown,/<script>|sensitive server details/);
    assert.notEqual(unknown,errorMessage({},'en'));
  }
});

test('incomplete cost keeps localized decimal precision without explanatory text', () => {
  const value={known_cost:'-1234.565000000000000001',cost_complete:false};
  const before=structuredClone(value);
  assert.equal(formatCost(value,'EUR','de'),'EUR -1.234,57');
  assert.equal(formatCost(value,'EUR','fr'),'EUR -1 234,57');
  assert.equal(formatCost(value,'PLN','pl'),'PLN -1234,57');
  assert.equal(formatCost(value,'EUR','it-IT'),'EUR -1234,57');
  assert.equal(formatCost({...value,cost_complete:true},'EUR','de'),'EUR -1.234,57');
  assert.deepEqual(value,before);
});

test('all card catalogs preserve keys, nonempty messages and template placeholders', async () => {
  const base=new URL('../../custom_components/charge_tally/www/locales/',import.meta.url);
  const en=(await import(new URL('en.js',base))).default;
  const placeholders=text=>[...text.matchAll(/\{(\w+)\}/g)].map(match=>match[1]).sort();
  for (const language of ['zh-Hans','de','fr','pl','it']) {
    const catalog=(await import(new URL(language+'.js',base))).default;
    assert.deepEqual(Object.keys(catalog).sort(),Object.keys(en).sort(),language);
    for (const [key,value] of Object.entries(catalog)) {
      assert.equal(typeof value,'string',`${language}:${key}`);
      assert.ok(value.trim(),`${language}:${key}`);
      assert.deepEqual(placeholders(value),placeholders(en[key]),`${language}:${key}`);
    }
  }
});

test('a missing translated key falls back to English in an installed module graph', async t => {
  const dir=await mkdtemp(join(tmpdir(),'charge-tally-i18n-'));
  t.after(()=>rm(dir,{recursive:true,force:true}));
  await cp(new URL('../../custom_components/charge_tally/www/',import.meta.url),dir,{recursive:true});
  const path=join(dir,'locales','de.js');
  const original=await readFile(path,'utf8');
  const partial=original.replace(/^\s*"point":.*\n/m,'');
  assert.notEqual(partial,original);
  await writeFile(path,partial);
  const isolated=await import(pathToFileURL(join(dir,'card-i18n.js')));
  assert.equal(isolated.tr('point','de'),'Charging point');
  assert.equal(isolated.tr('title','de'),'Titel');
});

test('interpolated values remain literal text and unresolved placeholders stay visible', () => {
  assert.equal(tr('error.configString','en',{field:'<img>$&{value}'}),'<img>$&{value} must be a string');
  assert.equal(tr('error.configString','en'),'{field} must be a string');
});
