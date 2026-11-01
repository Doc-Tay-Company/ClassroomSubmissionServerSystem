(function(){
  const toast = (message, kind='') => { const el=document.getElementById('toast'); if(!el)return; el.textContent=message; el.className='toast '+kind; window.clearTimeout(window.__toastTimer); window.__toastTimer=window.setTimeout(()=>el.className='toast hidden',4200); };
  window.cssToast=toast;
  window.cssRequest=async (url, options={})=>{
    const response=await fetch(url,{credentials:'same-origin',...options});
    const contentType=response.headers.get('content-type')||'';
    const body=contentType.includes('application/json')?await response.json():await response.text();
    if(!response.ok){const message=body && typeof body==='object'?(body.detail||body.message||JSON.stringify(body)):body; throw new Error(message||`HTTP ${response.status}`)}
    return body;
  };
  window.cssEscape=(value)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
})();
