import test from 'node:test';
import assert from 'node:assert/strict';
import {exportRequest,fetchReport,exportErrorMessage} from '../../custom_components/charge_tally/www/card-export.js';

test('export request freezes applied statistics filters without pagination',()=>{
  const filters={point_id:'p',identity_id:'i',offset:50,limit:25};
  const range={start:'2026-09-01T00:00:00Z',end:'2026-10-01T00:00:00Z'};
  const payload=exportRequest(filters,range,'de-DE');
  filters.identity_id='j';range.start='2026-09-20T00:00:00Z';
  assert.deepEqual(payload,{point_id:'p',identity_id:'i',start:'2026-09-01T00:00:00Z',end:'2026-10-01T00:00:00Z',language:'de-DE'});
  assert.deepEqual(exportRequest({}, {calendar_period:'monthly'},'zh-Hans'),{calendar_period:'monthly',language:'zh-Hans'});
  assert.throws(()=>exportRequest({},undefined,'en'));
  assert.throws(()=>exportRequest({},{start:'bad',end:'bad'},'en'));
});

test('authenticated report fetch preserves the binary response and safe filename',async()=>{
  const controller=new AbortController(),payload={calendar_period:'total',language:'en'};
  const hass={fetchWithAuth:async(path,options)=>{
    assert.equal(path,'/api/charge_tally/export.pdf');
    assert.equal(options.method,'POST');assert.deepEqual(options.headers,{'Content-Type':'application/json'});
    assert.equal(options.body,JSON.stringify(payload));assert.equal(options.signal,controller.signal);
    return new Response('%PDF-1.7\nreport',{headers:{'Content-Type':'application/pdf','Content-Disposition':'attachment; filename="charge-tally-20261027T120000Z.pdf"'}});
  }};
  const result=await fetchReport(hass,payload,controller.signal);
  assert.equal(await result.blob.text(),'%PDF-1.7\nreport');
  assert.equal(result.filename,'charge-tally-20261027T120000Z.pdf');
  for(const filename of ['../../unsafe.html','report.pdf','<script>.pdf']){
    const fetched=await fetchReport({fetchWithAuth:async()=>new Response('%PDF',{headers:{'Content-Type':'application/pdf','Content-Disposition':`attachment; filename="${filename}"`}})},payload);
    assert.equal(fetched.filename,'charge-tally-report.pdf');
  }
});

test('download handles API errors and non-PDF response',async()=>{
  for(const code of ['invalid_request','forbidden','export_unavailable','export_busy','export_too_large','export_missing_glyph','export_failed']){
    const hass={fetchWithAuth:async()=>Response.json({error:{code,message:'private server details'}},{status:422})};
    await assert.rejects(fetchReport(hass,{}),error=>{
      assert.equal(error.code,code);assert.doesNotMatch(exportErrorMessage(error,'de'),/private server details|error\./);
      assert.notEqual(exportErrorMessage(error,'de'),exportErrorMessage(error,'en'));return true;
    });
  }
  for(const response of [new Response('<html>secret</html>'),Response.json({error:{code:'<script>',message:'private'}} ,{status:500}),new Response('private',{status:401})]){
    await assert.rejects(fetchReport({fetchWithAuth:async()=>response},{}),error=>{
      assert.doesNotMatch(exportErrorMessage(error,'en'),/secret|private|<script>/);return true;
    });
  }
  await assert.rejects(fetchReport({fetchWithAuth:async()=>{throw new Error('private token');}},{}),error=>error.code==='export_failed');
  const aborted=Object.assign(new Error('aborted'),{name:'AbortError'});
  await assert.rejects(fetchReport({fetchWithAuth:async()=>{throw aborted;}},{}),error=>error===aborted);
});

test('missing glyph details locate controlled fields and rows without reflecting arbitrary text',()=>{
  const error={code:'export_missing_glyph',details:{field:'note',row:3,codepoints:['U+1F600']}};
  assert.match(exportErrorMessage(error,'en'),/3.*Note.*U\+1F600/);
  assert.match(exportErrorMessage(error,'zh-Hans'),/3.*备注.*U\+1F600/);
  assert.match(exportErrorMessage({...error,details:{field:'point',row:null,codepoints:['U+1F600']}},'en'),/Charging point.*U\+1F600/);
  for(const details of [{field:'<secret>',row:3,codepoints:['<script>']},{field:'note',row:'private',codepoints:['U+110000']},{field:'note',row:1,codepoints:['secret']},null]){
    const message=exportErrorMessage({...error,details},'en');
    assert.doesNotMatch(message,/<secret>|<script>|private|secret|U\+110000/);
    assert.match(message,/character/i);
  }
});
