(async function(){
  const tabId=Math.random().toString(36).slice(2);const tabKey='css-exam-tabs';const updateTabs=()=>{let tabs={};try{tabs=JSON.parse(localStorage.getItem(tabKey)||'{}');}catch(_){};const now=Date.now();tabs[tabId]=now;Object.keys(tabs).forEach(id=>{if(now-tabs[id]>20000)delete tabs[id];});try{localStorage.setItem(tabKey,JSON.stringify(tabs));}catch(_){}return Object.keys(tabs).length;};
  const sendTelemetry=async()=>{const form=new URLSearchParams({visibility:document.visibilityState,focused:String(document.hasFocus()),tab_count:String(updateTabs()),browser:navigator.userAgent});try{await window.cssRequest('/api/student/telemetry',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:form});}catch(_){}};
  const heartbeat=async()=>{try{await sendTelemetry();const status=await window.cssRequest('/api/student/status');const box=document.getElementById('student-notifications');if(box&&status.notifications?.length){box.className='alert alert-info';box.innerHTML=status.notifications.map(x=>`<div><strong>Thông báo</strong>: ${window.cssEscape(x.message)}</div>`).join('');}}catch(_){}};
  document.addEventListener('visibilitychange',sendTelemetry);window.addEventListener('focus',sendTelemetry);window.addEventListener('blur',sendTelemetry);window.addEventListener('storage',sendTelemetry);
  heartbeat();setInterval(heartbeat,15000);
  const start=document.getElementById('start-exam');
  if(start){start.addEventListener('click',async()=>{
    start.disabled=true; const password=document.getElementById('exam-password')?.value||'';
    const form=new FormData();form.append('exam_password',password);
    try{await window.cssRequest('/api/student/start',{method:'POST',body:form});window.location.reload();}
    catch(e){window.cssToast(e.message,'error');start.disabled=false;}
  });}
  const countdown=document.getElementById('countdown');
  if(countdown){
    let remaining=Number(countdown.dataset.remaining||0);
    const draw=()=>{const m=Math.floor(remaining/60),s=remaining%60;countdown.textContent=`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;if(remaining<=300)countdown.style.color='#b33232';if(remaining<=0)countdown.textContent='Hết giờ';};draw();
    // Display is informational only; the server remains authoritative on submission.
    setInterval(()=>{if(remaining>0)remaining--;draw();},1000);
    setInterval(async()=>{try{const s=await window.cssRequest('/api/student/status');if(s.remaining_seconds!==null){remaining=s.remaining_seconds;draw();}}catch(_){}},5000);
  }
  const form=document.getElementById('submission-form');
  if(form){form.addEventListener('submit',async(event)=>{event.preventDefault();const file=document.getElementById('submission-file').files[0];if(!file)return;const button=form.querySelector('button');button.disabled=true;const data=new FormData();data.append('file',file);
    try{const result=await window.cssRequest('/api/student/submit',{method:'POST',body:data});const box=document.getElementById('submission-result');box.classList.remove('hidden');box.textContent=`Đã nhận bài: ${result.submission.filename} (${result.submission.size_bytes} bytes).`;window.cssToast('Nộp bài thành công.','success');}
    catch(e){window.cssToast(e.message,'error');}finally{button.disabled=false;}
  });}
})();
