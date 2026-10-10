export const styles = `
:host{display:block;color:var(--primary-text-color,#24323e);background:var(--primary-background-color,#f4f6f8);min-height:100vh;font:14px/1.5 var(--paper-font-body1_-_font-family,system-ui)}
*{box-sizing:border-box}main{max-width:1000px;margin:auto;padding:24px}h1{font-size:26px;margin:0 0 8px}h2{font-size:18px;margin:0 0 12px}
p{margin:8px 0;overflow-wrap:anywhere}.muted{color:var(--secondary-text-color,#657080)}.toolbar,.actions{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
button,a{font:inherit}button{border:1px solid var(--divider-color,#ccd4dc);border-radius:8px;padding:9px 14px;background:var(--card-background-color,white);color:inherit;cursor:pointer}
button.primary{background:var(--primary-color,#167a93);color:white;border-color:transparent}button:disabled{opacity:.5;cursor:default}a{color:var(--primary-color,#167a93);overflow-wrap:anywhere}
article,.editor{padding:20px;margin:16px 0;background:var(--card-background-color,white);border:1px solid var(--divider-color,#dce2e7);border-radius:12px}
.editor[hidden]{display:none}.grid,.binding{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.binding{margin-top:12px;padding-top:12px;border-top:1px solid var(--divider-color,#dce2e7)}
label{display:block;min-width:0}label span{display:block;margin:0 0 5px}select{font:inherit;color:inherit;background:var(--card-background-color,white);border:1px solid var(--divider-color,#ccd4dc);border-radius:6px;padding:10px;width:100%;min-width:0}
.status{display:flex;gap:8px;flex-wrap:wrap}.status span{padding:3px 9px;border-radius:16px;background:var(--secondary-background-color,#edf2f5)}
.error{color:var(--error-color,#b42318);white-space:pre-line}.summary{white-space:pre-line;overflow-wrap:anywhere}
dialog{color:inherit;background:var(--card-background-color,white);border:1px solid var(--divider-color,#ccd4dc);border-radius:12px;max-width:min(540px,calc(100vw - 32px));max-height:85vh;padding:24px}
dialog::backdrop{background:#0007}dialog .actions{justify-content:flex-end}button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--primary-color,#167a93);outline-offset:2px}
@media(max-width:500px){main{padding:16px}.grid{grid-template-columns:1fr}article,.editor{padding:16px}.binding{grid-template-columns:1fr}h1{font-size:23px}}
`;
