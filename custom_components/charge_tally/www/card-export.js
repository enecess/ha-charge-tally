import {queryRequest} from './card-state.js?v=0.1.2-11';
import {tr} from './card-i18n.js?v=0.1.2-11';

const codes=new Set(['invalid_request','forbidden','export_unavailable','export_busy','export_too_large','export_missing_glyph','export_failed']);
const reportFields=new Set(['title','period','currency','generated','times','energy','cost','ordinal','names','status_note']);
export function exportRequest(filters,range,language='en'){
  const {type,...request}=queryRequest(filters,range);
  return {...request,language};
}
export async function fetchReport(hass,payload,signal){
  try{
    const response=await hass.fetchWithAuth('/api/charge_tally/export.pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal});
    if(!response.ok){
      const error=await response.json().then(body=>body?.error).catch(()=>null);
      const code=codes.has(error?.code)?error.code:response.status===401||response.status===403?'forbidden':'export_failed';
      throw {code,...(code==='export_missing_glyph'?{details:error?.details}:{})};
    }
    if(response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()!=='application/pdf')throw {code:'export_failed'};
    const filename=response.headers.get('Content-Disposition')?.match(/(?:^|;)\s*filename="(charge-tally-\d{8}T\d{6}Z\.pdf)"(?:;|$)/)?.[1]||'charge-tally-report.pdf';
    return {blob:await response.blob(),filename};
  }catch(error){
    if(error?.name==='AbortError')throw error;
    throw {code:codes.has(error?.code)?error.code:'export_failed',...(error?.code==='export_missing_glyph'?{details:error.details}:{})};
  }
}
export function exportErrorMessage(error,language='en'){
  const code=codes.has(error?.code)?error.code:'export_failed';
  const generic=tr('export.error.'+code,language);
  if(code!=='export_missing_glyph')return generic;
  const details=error?.details;
  const field=['identity','point','note'].includes(details?.field)?tr(details.field,language):reportFields.has(details?.field)?tr('exportReportText',language):null;
  const codepoints=details?.codepoints;
  if(!field||!Array.isArray(codepoints)||!codepoints.length||!codepoints.every(value=>typeof value==='string'&&/^U\+[0-9A-F]{4,6}$/.test(value)&&parseInt(value.slice(2),16)<=0x10ffff))return generic;
  const location=Number.isInteger(details.row)&&details.row>0&&details.row<=5000?tr('exportGlyphRow',language,{row:details.row,field}):field;
  return tr('exportGlyphDetails',language,{location,codepoints:codepoints.join(', ')});
}
