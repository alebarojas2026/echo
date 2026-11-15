export interface ChainState {seq:number;verified:boolean|'checking';witnesses_ok?:number;witnesses?:number}
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0
export function readChain(state: unknown): ChainState | null {
  const value=(state as {chain?:ChainState}|null)?.chain
  return value && count(value.seq) && [true,false,'checking'].includes(value.verified) ? value : null
}
export function chainLine(chain: ChainState, stale: boolean, bad: number | null) {
  if (stale) return {text:'Sealed record · waiting for board',fault:false}
  const witnesses = !count(chain.witnesses) ? 'witnesses unavailable' : chain.witnesses===0 ? '0 witnesses'
    : !count(chain.witnesses_ok) || chain.witnesses_ok>chain.witnesses ? 'witnesses unavailable'
    : chain.witnesses_ok===chain.witnesses ? `${chain.witnesses} ${chain.witnesses===1?'witness':'witnesses'}` : `${chain.witnesses_ok} of ${chain.witnesses} witnesses`
  const verified = chain.verified===false ? count(bad) && bad>0 && bad<=chain.seq ? `record ${bad} failed verification` : 'verification failed'
    : chain.seq===0 ? 'no records yet' : chain.verified===true ? 'verified' : 'checking'
  return {text:`Sealed record · ${verified} · ${witnesses}`,fault:chain.verified===false}
}
