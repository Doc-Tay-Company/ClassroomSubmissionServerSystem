(function(){
  const toast = (message, kind='') => { const el=document.getElementById('toast'); if(!el)return; el.textContent=message; el.className='toast '+kind; window.clearTimeout(window.__toastTimer); window.__toastTimer=window.setTimeout(()=>el.className='toast hidden',4200); };
  window.cssToast=toast;
  window.cssRequest=async (url, options={})=>{
    let response;
    try{response=await fetch(url,{credentials:'same-origin',...options});}
    catch(error){if(error&&typeof error==='object')error.url=url;throw error;}
    const contentType=response.headers.get('content-type')||'';
    const body=contentType.includes('application/json')?await response.json():await response.text();
    if(!response.ok){const detail=body&&typeof body==='object'?body.detail:undefined;const message=body && typeof body==='object'?(detail||body.message||JSON.stringify(body)):body; const error=new Error(message||`HTTP ${response.status}`); error.status=response.status; error.detail=detail; error.body=body; error.code=body&&typeof body==='object'?body.code:undefined; error.error_category=body&&typeof body==='object'?body.error_category:undefined; error.url=url; throw error}
    return body;
  };
  window.cssEscape=(value)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
})();
