import type {StateMsg} from '../room/contract'
import {chainLine,readChain,type ChainState} from './chain-status'
import './chain-status.css'

export function mountPanel(root:HTMLElement) {
  root.className='sealed-record';root.dataset.testid='sealed-record';root.hidden=true
  const privacy=root.closest('.judge')?.querySelector(':scope > .judge-privacy')
  privacy?.after(root)
  const arrival=document.createElement('p');arrival.className='sealed-record';arrival.dataset.testid='sealed-record-arrival';arrival.hidden=true
  let chain:ChainState|null=null,stale=true,bad:number|null=null,request:AbortController|null=null,next=0,disposed=false
  const paint=()=>{
    if (!arrival.isConnected) document.querySelector('.hud-arrival > header')?.after(arrival)
    for (const view of [root,arrival]) {
      view.hidden=!chain
      if (!chain) {view.textContent='';delete view.dataset.seq;continue}
      const line=chainLine(chain,stale,bad)
      view.textContent=line.text;view.dataset.tone=line.fault?'fault':'';view.dataset.seq=String(chain.seq)
    }
  }
  const clear=()=>{request?.abort();request=null;bad=null;next=0}
  const poll=async()=>{
    if (request || bad!==null || performance.now()<next || disposed) return
    const controller=request=new AbortController(),timeout=setTimeout(()=>controller.abort(),2000)
    next=performance.now()+3000
    try {
      const response=await fetch('/chain',{cache:'no-store',signal:controller.signal})
      const value=response.ok?await response.json():null
      if (request!==controller || controller.signal.aborted || disposed) return
      if (value?.verified===false && Number.isSafeInteger(value.first_bad_seq) && value.first_bad_seq>0 && chain && value.first_bad_seq<=chain.seq) bad=value.first_bad_seq
      paint()
    } catch { /* The state still says verification failed while the detail is unavailable. */ }
    finally {clearTimeout(timeout);if(request===controller)request=null}
  }
  return {
    update(state:StateMsg|null,isStale:boolean){
      const value=readChain(state)
      if (!value || isStale || value.verified!==false || chain && value.seq<chain.seq) clear()
      chain=value;stale=isStale;paint()
      if (chain?.verified===false && !stale) void poll()
    },
    reset(){clear();chain=null;paint()},
    dispose(){disposed=true;clear();root.remove();arrival.remove()},
  }
}
