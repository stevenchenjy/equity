import { useEffect, useRef, useState } from 'react';

export function uiUpdateAction(loaded:string|null, deployed:unknown, dirty:boolean, pending:boolean) {
  if (!loaded || typeof deployed!=='string' || !/^\/assets\/[^/]+\.js$/.test(deployed) || loaded===deployed) return 'none';
  return dirty||pending ? 'wait' : 'reload';
}

function unresolvedRequest() {
  try {
    return Boolean(localStorage.getItem('equity-dashboard-submission-v1') || localStorage.getItem('equity-dashboard-review-request-v1'));
  } catch { return true; }
}

// Reload idle tabs after deployment; never discard a draft or uncertain submit.
export function useUiVersion(dirty:boolean) {
  const [available,setAvailable]=useState(false);
  const currentDirty=useRef(dirty);
  currentDirty.current=dirty;
  useEffect(()=>{
    const loaded=document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.getAttribute('src')??null;
    let active=true;
    const check=async()=>{
      try {
        const r=await fetch('/api/ui-version',{cache:'no-store'});
        if(!r.ok)return;
        const v=await r.json();
        if(!active)return;
        const action=uiUpdateAction(loaded,v.entry_script,currentDirty.current,unresolvedRequest());
        setAvailable(action==='wait');
        if(action==='reload')window.location.reload();
      } catch { /* The existing connection status owns network errors. */ }
    };
    void check();
    const timer=window.setInterval(()=>void check(),30000);
    window.addEventListener('focus',check);
    return()=>{active=false;window.clearInterval(timer);window.removeEventListener('focus',check)};
  },[dirty]);
  return available;
}
