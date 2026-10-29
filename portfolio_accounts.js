'use strict';
// Account and position editor. Market lookup stays in the main HTML script.
const PRESET_ACCOUNTS = [
 {id:'account_kr',name:'일반 한국장 투자',type:'일반 증권',cash_currency:'KRW'},
 {id:'account_us',name:'일반 미국 투자',type:'일반 증권',cash_currency:'USD'},
 {id:'account_retirement_1',name:'퇴직연금 1',type:'퇴직연금',cash_currency:'KRW'},
 {id:'account_retirement_2',name:'퇴직연금 2',type:'퇴직연금',cash_currency:'KRW'},
 {id:'account_isa',name:'ISA',type:'ISA',cash_currency:'KRW'},
 {id:'account_irp_mirae',name:'IRP (미래)',type:'IRP',cash_currency:'KRW'},
 {id:'account_irp_samsung',name:'IRP (삼성)',type:'IRP',cash_currency:'KRW'},
 {id:'account_irp_yuanta',name:'IRP (유안타)',type:'IRP',cash_currency:'KRW'}
];
const REGION_LABELS={KR:'한국 자산',US:'미국 자산',OTHER:'기타 자산',UNKNOWN:'미분류'};
const STYLE_LABELS={growth:'성장',dividend:'배당',unknown:'미분류'};
const ASSET_LABELS={equity:'주식형',bond:'채권형',cash:'현금성',other:'기타',unknown:'미확인'};
let activeAccountId=null,editingHoldingId=null,pendingMarketCode=null,editingReceiptId=null;
function realDate(text){return typeof text==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(text)&&!Number.isNaN(Date.parse(text))&&new Date(text+'T00:00:00Z').toISOString().slice(0,10)===text}
function newAccount(preset){return {...preset,preset_key:preset.id,cash:null,cash_asof:null}}
function newPortfolio(){return {schema_version:2,document_id:uid(),revision:0,accounts:PRESET_ACCOUNTS.map(newAccount),holdings:[],snapshots:[],audit:[],dividend_receipts:[],fx:{usd_krw:null,as_of:null}}}

function validatePortfolio(input){
 if(!input||![1,2].includes(input.schema_version)||typeof input.document_id!=='string'||!Number.isInteger(input.revision)||input.revision<0)throw Error('지원하지 않는 JSON 문서·버전입니다.');
 const doc=structuredClone(input),legacy=doc.schema_version===1;
 for(const key of ['accounts','holdings','snapshots','audit'])if(!Array.isArray(doc[key]))throw Error(key+' 목록이 없습니다.');
 if(doc.accounts.length>1000||doc.holdings.length>20000||doc.snapshots.length>20000||doc.audit.length>50000)throw Error('입력 항목 수가 너무 많습니다.');
 const ids=new Set();
 for(const a of doc.accounts){
  if(!a||typeof a.id!=='string'||ids.has(a.id)||typeof a.name!=='string'||!a.name.trim()||a.name.length>80||typeof a.type!=='string'||!(a.cash===null||validNumber(a.cash)))throw Error('계좌 데이터가 올바르지 않습니다.');
  ids.add(a.id);if(legacy){a.cash_currency='KRW';a.cash_asof=null}
  if(!['KRW','USD'].includes(a.cash_currency)||!(a.cash_asof==null||realDate(a.cash_asof)))throw Error('계좌 현금의 통화·기준일을 확인하세요.');
 }
 const seen=new Set(),hids=new Set();
 for(const h of doc.holdings){
  if(!h||typeof h.id!=='string'||hids.has(h.id)||!ids.has(h.account_id)||typeof h.code!=='string'||!/^[A-Za-z0-9][A-Za-z0-9.^:-]{0,23}$/.test(h.code)||!validNumber(h.quantity,Number.MIN_VALUE)||!(h.cost===null||validNumber(h.cost))||typeof h.memo!=='string'||h.memo.length>300)throw Error('보유 종목의 계좌·수량·매입가를 확인하세요.');
  if(legacy){h.name=symbols.get(h.code)?.name||h.code;h.currency='KRW';h.region=symbols.has(h.code)&&symbols.get(h.code).instrument_type!=='ETF'?'KR':'UNKNOWN';h.style='unknown';h.price_mode=symbols.has(h.code)?'auto':'manual';h.manual_price=null;h.price_date=null}
  if(h.asset_class===undefined)h.asset_class=symbols.get(h.code)?.instrument_type==='ETF'?'unknown':'equity';
  if(!Object.hasOwn(ASSET_LABELS,h.asset_class))throw Error('종목의 자산 유형을 확인하세요.');
  if(typeof h.name!=='string'||!h.name.trim()||h.name.length>100||!['KRW','USD'].includes(h.currency)||!Object.hasOwn(REGION_LABELS,h.region)||!Object.hasOwn(STYLE_LABELS,h.style)||!['auto','manual'].includes(h.price_mode)||!(h.manual_price===null||validNumber(h.manual_price))||!(h.price_date===null||realDate(h.price_date)))throw Error('종목의 통화·분류·현재가를 확인하세요.');
  if(h.price_mode==='auto'&&h.currency!=='KRW')throw Error('국내 자동 시세의 통화는 KRW입니다.');
  validateDividend(h);
  const key=[h.account_id,h.code.toUpperCase(),h.currency].join(':');if(seen.has(key))throw Error('같은 계좌·종목·통화가 중복되었습니다.');seen.add(key);hids.add(h.id);
 }
 validateDividendReceipts(doc);
 const dates=new Set();
 for(const s of doc.snapshots){if(!s||!realDate(s.date)||dates.has(s.date)||!validNumber(s.value)||typeof s.recorded_at!=='string'||typeof s.status!=='string'||typeof s.price_range!=='string')throw Error('평가 기록이 올바르지 않습니다.');dates.add(s.date)}
 if(legacy)doc.fx={usd_krw:null,as_of:null};
 if(!doc.fx||!(doc.fx.usd_krw===null||validNumber(doc.fx.usd_krw,Number.MIN_VALUE))||!(doc.fx.as_of===null||realDate(doc.fx.as_of))||(doc.fx.usd_krw!==null&&doc.fx.as_of===null))throw Error('달러 환율과 기준일을 확인하세요.');
 // Remove the specifically requested account; preserve its values in audit history.
 const removedAccounts=doc.accounts.filter(a=>a.name.trim()==='미래에셋 IRP');
 if(removedAccounts.length){
  const removedIds=new Set(removedAccounts.map(a=>a.id));
  for(const account of removedAccounts)doc.audit.push({at:new Date().toISOString(),action:'사용자 요청 계좌 삭제 전 값',account:structuredClone(account),holdings:structuredClone(doc.holdings.filter(h=>h.account_id===account.id))});
  doc.accounts=doc.accounts.filter(a=>!removedIds.has(a.id));doc.holdings=doc.holdings.filter(h=>!removedIds.has(h.account_id));doc.revision++;
 }
 const ordered=[];
 for(const preset of PRESET_ACCOUNTS){let found=doc.accounts.find(a=>!ordered.includes(a)&&a.preset_key===preset.id)||doc.accounts.find(a=>!ordered.includes(a)&&a.name===preset.name);if(!found){found=newAccount(preset);if(ids.has(found.id))found.id=uid();ids.add(found.id)}found.preset_key=preset.id;if(preset.id==='account_irp_yuanta')found.name=preset.name;ordered.push(found)}
 // Keep the final preset (IRP 유안타) after any existing extra accounts.
 const extraAccounts=doc.accounts.filter(a=>!ordered.includes(a)),lastAccount=ordered.pop();
 doc.accounts=[...ordered,...extraAccounts,lastAccount];doc.schema_version=2;
 return doc;
}
try{
 const saved=localStorage.getItem('krx-portfolio-v1'),input=saved?JSON.parse(saved):null;
 portfolio=input?validatePortfolio(input):newPortfolio();
 if(input?.accounts?.some(a=>a.name.trim()==='미래에셋 IRP')){
  dirty=true;
  try{localStorage.setItem('krx-portfolio-v1',JSON.stringify(portfolio))}catch{}
  toast('미래에셋 IRP 계좌를 제거했습니다. 삭제 전 값과 평가 이력은 보관했습니다. JSON으로 내보내세요.');
 }else if(input?.schema_version===1){dirty=true;toast('기존 계좌·보유를 보존해 새 형식으로 불러왔습니다. 분류를 확인하고 JSON을 내보내세요.')}
}catch(error){portfolio=newPortfolio();toast('임시 복원 실패: '+error.message+' 원본 저장값은 보존했습니다. JSON을 불러올 수 있습니다.')}

function fxRate(currency){return currency==='KRW'?1:portfolio.fx.usd_krw}
function money(value,currency='KRW'){return value==null?'—':(currency==='USD'?'US$ ':'')+fmt(value,currency==='USD'?2:0)+(currency==='KRW'?' 원':'')}
function resolvedHolding(h){
 const source=symbols.get(h.code),price=h.price_mode==='auto'?(source?.price??null):h.manual_price;
 const day=h.price_mode==='auto'?(source?.date??null):h.price_date;
 const rate=fxRate(h.currency),nativeValue=price===null?null:price*h.quantity;
 const value=nativeValue===null?null:nativeValue===0?0:rate===null?null:nativeValue*rate;
 const pnl=price===null||h.cost===null?null:(price-h.cost)*h.quantity;
 return {name:h.name||source?.name||h.code,price,day,rate,nativeValue,value,pnl,
  pnlKRW:pnl===null||rate===null?null:pnl*rate,
  pnlPct:price===null||h.cost===null||h.cost===0?null:(price/h.cost-1)*100,
  costValue:h.cost===null||rate===null?null:h.cost*h.quantity*rate};
}
function marketDayPeriod(){
 const today=krDate(),quotes=[...symbols.values()];
 const days=quotes.map(s=>s.date).filter(day=>realDate(day)&&day<=today).sort();
 const day=days.at(-1)||null;
 const previousDays=quotes.filter(s=>s.date===day&&realDate(s.comparison_date)&&s.comparison_date<day).map(s=>s.comparison_date).sort();
 return {day,previousDay:previousDays.at(-1)||null};
}
function holdingDayChange(h,period){
 const unavailable=reason=>({pct:null,complete:false,reason});
 if(h.price_mode!=='auto')return unavailable('직접 입력 · 전일가 없음');
 const s=symbols.get(h.code);
 if(!s||!validNumber(s.price)||!validNumber(s.previous_price,Number.MIN_VALUE))return unavailable('현재가·전일가 미확인');
 if(!realDate(s.date)||!realDate(s.comparison_date)||s.comparison_date>=s.date||s.date>krDate())return unavailable('비교 가격일 미확인');
 const comparable=s.date===period.day&&s.comparison_date===period.previousDay;
 return {pct:(s.price/s.previous_price-1)*100,price:s.price,previous:s.previous_price,day:s.date,comparisonDate:s.comparison_date,complete:comparable,reason:comparable?'':'계좌 비교일과 다름'};
}
function accountDayChange(account,metrics,period){
 const unavailable=reason=>({pct:null,complete:false,reason});
 if(!metrics.hasKnown)return unavailable('미입력');
 if(!metrics.complete)return unavailable('현금·가격·환율 미확인');
 let current=metrics.cash,previous=metrics.cash;
 for(const h of metrics.holdings){
  const change=holdingDayChange(h,period),rate=fxRate(h.currency);
  if(!change.complete||rate===null)return unavailable((h.name||h.code)+' · '+(change.reason||'환율 미확인'));
  current+=change.price*h.quantity*rate;previous+=change.previous*h.quantity*rate;
 }
 return {pct:previous>0?(current/previous-1)*100:null,current,previous,complete:true,day:period.day,comparisonDate:period.previousDay,reason:previous===0?'계좌 총액 0':!metrics.holdings.length?'현금만 · 가격 변동 0':''};
}
function aggregateDayChanges(rows,period){
 if(!rows.length)return {pct:null,complete:false,reason:'미입력'};
 if(rows.some(row=>!row.dayChange.complete))return {pct:null,complete:false,reason:'일부 계좌의 전일 비교 불가'};
 const current=rows.reduce((sum,row)=>sum+row.dayChange.current,0),previous=rows.reduce((sum,row)=>sum+row.dayChange.previous,0);
 return {pct:previous>0?(current/previous-1)*100:null,current,previous,complete:true,day:period.day,comparisonDate:period.previousDay,reason:previous===0?'합계 총액 0':''};
}
function dailyChangeCell(change){
 let caption=change.reason||'';
 if(change.pct!==null&&change.day&&change.comparisonDate)caption=(change.day===krDate()?'오늘':'저장 가격일')+' '+change.day+' ← '+change.comparisonDate+(change.reason?' · '+change.reason:'');
 return `<b class="${colorClass(change.pct)}">${percent(change.pct)}</b><div class="data-date" title="${esc(caption)}">${esc(caption)}</div>`;
}

// Display/aggregation policy: bond-type holdings contribute to dividends.
// Keep the original saved style and asset type intact.
function compositionStyle(h){
 if(h.asset_class==='bond')return 'dividend';
 return (h.asset_class||'equity')==='equity'?h.style:null;
}
function accountMetrics(account){
 const holdings=portfolio.holdings.filter(h=>h.account_id===account.id);
 const rate=fxRate(account.cash_currency),cash=account.cash===null?null:account.cash===0?0:rate===null?null:account.cash*rate;
 let total=cash??0,missing=cash===null?1:0,pnl=0,knownCost=0,pnlMissing=0,styleExcluded=0;
 const buckets={KR:0,US:0,OTHER:0,UNKNOWN:0,growth:0,dividend:0,unknown:0},dates=[];
 for(const h of holdings){const r=resolvedHolding(h);if(r.value===null)missing++;else{total+=r.value;buckets[h.region]+=r.value;const style=compositionStyle(h);if(style!==null){buckets[style]+=r.value}else styleExcluded+=r.value}if(r.pnlKRW===null||r.costValue===null)pnlMissing++;else{pnl+=r.pnlKRW;knownCost+=r.costValue}if(r.day)dates.push(r.day)}
 const complete=missing===0,hasKnown=cash!==null||holdings.some(h=>resolvedHolding(h).value!==null);
 const share=key=>complete&&total>0?buckets[key]/total*100:null;
 return {holdings,total,missing,complete,hasKnown,cash,buckets,styleExcluded,dates:[...new Set(dates)].sort(),share,
  pnl:holdings.length&&pnlMissing===0?pnl:null,pnlPct:holdings.length&&pnlMissing===0&&knownCost>0?pnl/knownCost*100:null};
}
function valuation(){const all=portfolio.accounts.map(accountMetrics);return {total:all.reduce((n,x)=>n+x.total,0),missing:all.reduce((n,x)=>n+x.missing,0),hasKnown:all.some(x=>x.hasKnown),dates:[...new Set(all.flatMap(x=>x.dates))].sort()}}
function ratioCell(value){return value===null?'<span class="muted">—</span>':`<div class="ratio"><b>${fmt(value,1)}%</b><span><i style="width:${Math.max(0,Math.min(100,value))}%"></i></span></div>`}
function renderSaveState(){const entered=portfolio.holdings.length||(portfolio.dividend_receipts||[]).length||portfolio.accounts.some(a=>a.cash!==null);$('saveState').textContent=dirty?'파일 내보내기 필요':entered?'개인 데이터 불러옴':portfolio.accounts.length+'개 계좌 · 입력 대기';$('fileState').textContent='문서 형식 v2 · 리비전 '+portfolio.revision+' · '+(exportedAt?'최근 내보내기 요청 '+exportedAt:'이 실행에서 파일 내보내기 없음');if(typeof renderPortfolioStorageState==='function')renderPortfolioStorageState()}
function amountAndShare(value,share,partial=false){
 if(value===null)return '<span class="muted">미입력 (—)</span>';
 return `<span class="amount-share"><b>${money(value)}</b> <span class="muted">(${share===null?'—':fmt(share,1)+'%'})</span></span>${partial?'<div class="data-date">확인분</div>':''}`;
}
function compositionSummary(){
 const rows=portfolio.accounts.map(account=>({account,metrics:accountMetrics(account)}));
 const period=marketDayPeriod();
 for(const row of rows)row.dayChange=accountDayChange(row.account,row.metrics,period);
 const included=rows.filter(row=>row.metrics.hasKnown),excludedCount=rows.length-included.length;
 const total=included.reduce((sum,row)=>sum+row.metrics.total,0),missing=included.reduce((sum,row)=>sum+row.metrics.missing,0);
 const hasKnown=included.length>0,cashKnown=included.some(row=>row.metrics.cash!==null),cashMissing=included.some(row=>row.metrics.cash===null);
 const cash=cashKnown?included.reduce((sum,row)=>sum+(row.metrics.cash??0),0):null;
 const buckets={KR:0,US:0,growth:0,dividend:0};
 for(const row of included)for(const key of Object.keys(buckets))buckets[key]+=row.metrics.buckets[key];
 const positionsMissing=included.some(row=>row.metrics.holdings.some(h=>resolvedHolding(h).value===null));
 return {rows,total,missing,hasKnown,cash,cashMissing,buckets,positionsMissing,period,dayChange:aggregateDayChanges(included,period),includedCount:included.length,excludedCount,share:value=>missing===0&&total>0&&value!==null?value/total*100:null};
}
function summaryRow(account,m,overall,dayChange){
 const status=!m.hasKnown?'미입력':m.missing?'부분 평가 · 미확인 '+m.missing+'건':'등록 범위 평가';
 const positionsMissing=m.holdings.some(h=>resolvedHolding(h).value===null);
 const cashShare=m.complete&&m.total>0&&m.cash!==null?m.cash/m.total*100:null;
 return `<tr class="account-row" data-account="${esc(account.id)}" tabindex="0" aria-label="${esc(account.name)} 상세 보기"><td class="name-cell"><b>${esc(account.name)}</b><small>${esc(account.type)} · ${m.holdings.length}종목</small></td><td class="num">${amountAndShare(m.hasKnown?m.total:null,overall.share(m.total))}<div class="data-date">${esc(status)}</div></td><td class="num">${dailyChangeCell(dayChange)}</td><td class="num">${amountAndShare(m.cash,cashShare)}</td>${['KR','US','growth','dividend'].map(key=>`<td class="num">${amountAndShare(m.hasKnown?m.buckets[key]:null,m.share(key),positionsMissing&&m.hasKnown)}</td>`).join('')}<td><button class="mini-action" data-open-account="${esc(account.id)}">상세 →</button></td></tr>`;
}
function compositionTotalRow(overall){
 const status=(overall.missing?'부분 합계 · 미확인 '+overall.missing+'건':'입력된 '+overall.includedCount+'개 계좌 기준')+(overall.excludedCount?' · 미입력 '+overall.excludedCount+'개 제외':'');
 return `<tr class="account-total-row"><th scope="row" class="name-cell"><b>전체 합계</b><small>${esc(status)}</small></th><td class="num">${amountAndShare(overall.hasKnown?overall.total:null,overall.share(overall.total),overall.hasKnown&&overall.missing>0)}</td><td class="num">${dailyChangeCell(overall.dayChange)}</td><td class="num">${amountAndShare(overall.cash,overall.share(overall.cash),overall.cash!==null&&overall.cashMissing)}</td>${['KR','US','growth','dividend'].map(key=>`<td class="num">${amountAndShare(overall.hasKnown?overall.buckets[key]:null,overall.share(overall.buckets[key]),overall.hasKnown&&overall.positionsMissing)}</td>`).join('')}<td></td></tr>`;
}

// Summary cards use the same included accounts and current-price period as the table.
function holdingGroupSummary(holdings,period,hasKnown){
 let current=0,previous=0,known=0,missing=0,comparable=holdings.length>0,reason=holdings.length?'':'보유 없음';
 for(const h of holdings){
  const r=resolvedHolding(h),change=holdingDayChange(h,period);
  if(r.value===null){missing++;comparable=false;reason='가격·환율 미확인'}else{current+=r.value;known++}
  if(!change.complete||r.rate===null){comparable=false;reason=change.reason||'환율 미확인'}else previous+=change.previous*h.quantity*r.rate;
 }
 const value=hasKnown&&(known>0||holdings.length===0)?current:null;
 return {value,missing,count:holdings.length,dayChange:{pct:comparable&&previous>0?(current/previous-1)*100:null,complete:comparable,current,previous,day:period.day,comparisonDate:period.previousDay,reason:reason||(previous===0?'전일 평가액 0':'')}};
}
function overviewBreakdown(overall){
 const holdings=overall.rows.filter(row=>row.metrics.hasKnown).flatMap(row=>row.metrics.holdings);
 const classified=holdings.filter(h=>compositionStyle(h)!==null);
 const groups={};
 for(const style of ['growth','dividend']){
  const selected=classified.filter(h=>compositionStyle(h)===style);
  groups[style]=holdingGroupSummary(selected,overall.period,overall.hasKnown);
  for(const region of ['KR','US'])groups[style+'_'+region]=holdingGroupSummary(selected.filter(h=>h.region===region),overall.period,overall.hasKnown);
 }
 return groups;
}
function overviewRatioPair(label,leftLabel,left,rightLabel,right,cashShare=undefined){
 const text=value=>value===null?'—':fmt(value,1)+'%';
 const width=value=>value===null?0:Math.max(0,Math.min(100,value));
 const entries=[{label:leftLabel,value:left},{label:rightLabel,value:right}];
 if(cashShare!==undefined)entries.push({label:'현금',value:cashShare,kind:'cash'});
 return `<div class="overview-ratio-row"><div class="overview-ratio-heading">${esc(label)}</div><div class="overview-ratio-values${entries.length===3?' with-cash':''}">${entries.map(entry=>`<span class="${entry.kind||''}">${esc(entry.label)} <b>${text(entry.value)}</b></span>`).join('')}</div><div class="overview-ratio-track" aria-hidden="true">${entries.map(entry=>`<i class="${entry.kind||''}" style="width:${width(entry.value)}%"></i>`).join('')}</div></div>`;
}
function renderOverviewCards(overall){
 const change=overall.dayChange,groups=overviewBreakdown(overall);
 $('portfolioValue').textContent=overall.hasKnown?money(overall.total):'미입력';
 $('portfolioCoverage').textContent=(overall.missing?'확인된 금액만 · 미확인 '+overall.missing+'건':'입력된 '+overall.includedCount+'개 계좌 기준')+(overall.excludedCount?' · 미입력 '+overall.excludedCount+'개 제외':'');
 $('portfolioDayPct').textContent=percent(change.pct);$('portfolioDayPct').className=colorClass(change.pct);
 const delta=change.complete?change.current-change.previous:null;
 $('portfolioDayAmount').textContent=delta===null?'—':(delta>0?'+':delta<0?'−':'')+money(Math.abs(delta));
 $('portfolioDayAmount').className=colorClass(delta);
 $('portfolioDayPeriod').textContent=change.complete&&change.day&&change.comparisonDate?(change.day===krDate()?'오늘':'저장 가격일')+' '+change.day+' ← '+change.comparisonDate:change.reason||'비교 가격일 없음';
 $('overviewMatrix').innerHTML=['growth','dividend'].map(style=>`<tr><th scope="row">${style==='growth'?'성장주':'배당주'}</th>${['KR','US'].map(region=>{const group=groups[style+'_'+region];return `<td><b class="matrix-amount">${group.value===null?'미입력':money(group.value)}</b><span class="matrix-change ${colorClass(group.dayChange.pct)}" title="${esc(group.dayChange.reason||'현재 수량·환율 고정, 전일 가격 대비')}">${percent(group.dayChange.pct)}</span>${group.missing?'<small>확인분 · 미확인 '+group.missing+'건</small>':''}</td>`}).join('')}</tr>`).join('');
 const inside=(style,region)=>groups[style].value>0&&groups[style].missing===0&&groups[style+'_'+region].value!==null?groups[style+'_'+region].value/groups[style].value*100:null;
 $('overviewRatios').innerHTML=overviewRatioPair('총액 대비 · 성장 / 배당 / 현금','성장주',overall.share(overall.buckets.growth),'배당주',overall.share(overall.buckets.dividend),overall.share(overall.cash))+overviewRatioPair('총액 대비 · 한국 / 미국 / 현금','한국',overall.share(overall.buckets.KR),'미국',overall.share(overall.buckets.US),overall.share(overall.cash))+overviewRatioPair('성장주 내 지역 비중','한국',inside('growth','KR'),'미국',inside('growth','US'))+overviewRatioPair('배당주 내 지역 비중','한국',inside('dividend','KR'),'미국',inside('dividend','US'));
 $('accountCount').textContent=portfolio.accounts.length;$('holdingCount').textContent=portfolio.holdings.length;$('snapshotCount').textContent=portfolio.snapshots.length;
 $('overviewIncludedCount').textContent=overall.includedCount;
}

function renderPortfolio(){
 const composition=compositionSummary();renderOverviewCards(composition);
 $('accountRows').innerHTML=composition.rows.map(row=>summaryRow(row.account,row.metrics,composition,row.dayChange)).join('');
 $('accountTotals').innerHTML=compositionTotalRow(composition);
 const select=$('holdingAccount'),old=select.value;select.innerHTML=portfolio.accounts.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');if(portfolio.accounts.some(a=>a.id===old))select.value=old;if(activeAccountId&&activeView==='account'){select.value=activeAccountId;select.disabled=true}else select.disabled=false;

 if(document.activeElement!==$('fxRate'))$('fxRate').value=portfolio.fx.usd_krw??'';
 if(document.activeElement!==$('fxDate'))$('fxDate').value=portfolio.fx.as_of||krDate();
 $('fxStatus').textContent=portfolio.fx.usd_krw===null?'달러 환율 미입력 · USD 자산의 원화 합계·비중은 산출하지 않습니다.':'USD 1 = '+fmt(portfolio.fx.usd_krw,4)+' KRW · 기준일 '+portfolio.fx.as_of;
 $('portfolioNote').textContent='계좌 총액 = 현금 + 종목 평가액. 모든 금액은 원화 환산입니다. 계좌 총액의 괄호는 전체 자산 대비 비중, 현금·한국 자산·미국 자산·성장/배당의 괄호는 해당 계좌 총액(현금 포함) 대비 비중입니다. 전체 합계 행과 계좌 총액 비중은 금액이 확인된 계좌만 합산하며 아예 미입력인 계좌는 계산에서 제외합니다. 한국/미국 자산은 지정한 투자 지역의 모든 보유 자산을 포함합니다. 채권·혼합형·현금성 ETF도 해당 지역에 합산하며 직접 입력 현금은 별도입니다. 채권형 자산은 배당 금액에 포함합니다. 현금성·기타·유형 미확인은 성장/배당 금액에서 제외합니다. 국가별 항목과 성장/배당 항목은 중복 합산하지 않습니다. 현금·기타 국가·미분류 등에 따라 각 분류의 합계는 100%보다 작을 수 있습니다. 포함된 계좌에 미확인 금액이 남아 있으면 확인분만 합산하고 비중을 보류합니다. 전일 대비는 현재 보유수량·현금·환율을 고정한 시세 평가액 변화이며, 입출금·매매·분배금과 환율 변동을 반영한 실제 일간 수익률은 아닙니다. 같은 가격일·직전 저장 거래일의 가격이 모두 있는 계좌만 계산합니다.';
 $('holdingRows').innerHTML=renderHoldingRows(portfolio.holdings,true);renderSnapshots();renderDividends();renderDividendReceiptHistory();if(activeAccountId)renderAccountDetail();
}
function renderHoldingRows(holdings,withAccount=false){const accounts=new Map(portfolio.accounts.map(a=>[a.id,a])),period=marketDayPeriod();return holdings.map(h=>{const r=resolvedHolding(h),style=compositionStyle(h)??h.style;return `<tr>${withAccount?`<td>${esc(accounts.get(h.account_id)?.name||'미확인')}</td>`:''}<td class="name-cell"><b>${esc(r.name)}</b><small>${esc(h.code)} · ${esc(h.currency)}</small>${h.memo?`<small>${esc(h.memo)}</small>`:''}</td><td><span class="badge">${ASSET_LABELS[h.asset_class||'equity']}</span></td><td class="num">${money(h.cost,h.currency)}</td><td class="num">${fmt(h.quantity,6)}</td><td class="num">${money(r.price,h.currency)}<div class="data-date">${esc(r.day||'기준일 미입력')} · ${h.price_mode==='auto'?'국내 자동':'직접 입력'}</div></td><td class="num">${dailyChangeCell(holdingDayChange(h,period))}</td><td class="num">${money(r.value)}${h.currency==='USD'?`<div class="data-date">${money(r.nativeValue,'USD')}</div>`:''}</td><td class="num ${colorClass(r.pnl)}">${money(r.pnl,h.currency)}${h.currency==='USD'&&r.pnlKRW!==null?`<div class="data-date">${money(r.pnlKRW)}</div>`:''}</td><td class="num ${colorClass(r.pnlPct)}">${percent(r.pnlPct)}</td><td><span class="badge">${REGION_LABELS[h.region]}</span></td><td><span class="badge ${style==='growth'?'growth':style==='dividend'?'dividend':''}">${STYLE_LABELS[style]}</span></td><td class="actions-cell"><button data-edit-position="${esc(h.id)}">수정</button> <button class="danger" data-delete-position="${esc(h.id)}">삭제</button></td></tr>`}).join('')||`<tr><td colspan="${withAccount?13:12}" class="empty">등록된 보유 종목이 없습니다. ${withAccount?'계좌 행을 눌러 상세 페이지에서 종목을 추가하세요.':'아래 입력 폼에서 종목을 추가하세요.'}</td></tr>`}
function renderAccountDetail(){const a=portfolio.accounts.find(a=>a.id===activeAccountId);if(!a)return;const m=accountMetrics(a);$('detailTitle').textContent=a.name;$('detailType').textContent=a.type+' · '+m.holdings.length+'개 보유 종목';$('detailTotal').textContent=m.hasKnown?money(m.total):'미입력';$('detailCashValue').textContent=money(a.cash,a.cash_currency);$('detailProfit').textContent=money(m.pnl);$('detailProfit').className=colorClass(m.pnl);$('detailProfitPct').textContent=percent(m.pnlPct);$('detailProfitPct').className=colorClass(m.pnlPct);$('detailRatios').innerHTML=[['한국 자산',m.share('KR')],['미국 자산',m.share('US')],['성장주',m.share('growth')],['배당주',m.share('dividend')]].map(([label,value])=>`<div class="allocation-item"><span>${label}</span>${ratioCell(value)}</div>`).join('');
 $('detailHoldingsRows').innerHTML=renderHoldingRows(m.holdings);
 $('detailNote').textContent=(m.missing?'현금·가격·환율 미확인 '+m.missing+'건. 확인된 금액만 합산하며 비중은 보류합니다. ':'')+'가격 범위: '+(m.dates.length?m.dates[0]+' ~ '+m.dates.at(-1):'없음')+'. 손익은 (현재가−평균매입가)×수량, 손익률은 현재가/평균매입가−1입니다. 배당·세금·수수료·매입시점 환율 차이는 제외합니다.';
 $('detailCash').value=a.cash??'';$('detailCashCurrency').value=a.cash_currency;
 const unresolvedRegion=m.buckets.UNKNOWN+m.buckets.OTHER,unresolvedStyle=m.buckets.unknown;
 $('detailClassification').textContent='기타·지역 미분류 평가액 '+money(unresolvedRegion)+' · 성장/배당 미분류 평가액 '+money(unresolvedStyle)+' · 스타일 집계 제외(현금성·기타/유형 미확인) '+money(m.styleExcluded)+' · 국가별 자산에는 채권·혼합형·현금성 ETF도 포함합니다. 채권형 자산은 배당으로 집계합니다. 현금성·기타·유형 미확인은 성장/배당 금액에서 제외하며 분류별로 중복 합산하지 않습니다. 국내 상장 미국 ETF도 투자대상을 미국으로 지정할 수 있습니다.';
}
function switchView(view){activeView=view;for(const el of document.querySelectorAll('.view'))el.hidden=el.id!=='view-'+view;for(const btn of document.querySelectorAll('.nav'))btn.classList.toggle('active',btn.dataset.view===(view==='account'?'portfolio':view));if(view==='account'){$('holdingAccount').value=activeAccountId;$('holdingAccount').disabled=true;renderAccountDetail()}else $('holdingAccount').disabled=false;if(view==='market')renderPriceChart();if(view==='files'){renderSnapshots();renderDividendReceiptHistory()}if(view==='dividends')renderDividends()}
function openAccount(id){if(!portfolio.accounts.some(a=>a.id===id))return;activeAccountId=id;cancelHoldingEdit();switchView('account');if(pendingMarketCode){$('holdingCode').value=pendingMarketCode;pendingMarketCode=null;suggestSymbol();$('holdingEditor').scrollIntoView({block:'start',behavior:'smooth'})}else $('detailTitle').scrollIntoView({block:'start',behavior:'smooth'})}
$('accountRows').onclick=e=>{const row=e.target.closest('[data-account]');if(row)openAccount(row.dataset.account)};
$('accountRows').onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-account]')){e.preventDefault();openAccount(e.target.dataset.account)}};
$('backToAccounts').onclick=()=>{cancelHoldingEdit();switchView('portfolio')};
function saveCash(id,value,currency,asof){const a=portfolio.accounts.find(a=>a.id===id);if(!a)return;const cash=value.trim()===''?null:Number(value);if(cash!==null&&!validNumber(cash))return toast('0 이상의 현금 금액을 입력하세요.');if(!['KRW','USD'].includes(currency)||!realDate(asof))return toast('현금 통화·기준일을 확인하세요.');portfolio.audit.push({at:new Date().toISOString(),action:'현금 수정 전 값',account:structuredClone(a)});a.cash=cash;a.cash_currency=currency;a.cash_asof=asof;persist('계좌 현금 수정');toast('현금 잔고를 저장했습니다.')}
$('detailCashForm').onsubmit=e=>{e.preventDefault();saveCash(activeAccountId,$('detailCash').value,$('detailCashCurrency').value,krDate())};
$('fxForm').onsubmit=e=>{e.preventDefault();const raw=$('fxRate').value,rate=raw===''?null:Number(raw),asof=$('fxDate').value;if(rate!==null&&(!validNumber(rate,Number.MIN_VALUE)||!realDate(asof)))return toast('양수 환율과 기준일을 입력하세요.');portfolio.audit.push({at:new Date().toISOString(),action:'환율 수정 전 값',fx:structuredClone(portfolio.fx)});portfolio.fx={usd_krw:rate,as_of:rate===null?null:asof};persist('달러 환율 수정');toast('계좌 합계에 적용할 환율을 저장했습니다.')};
function updatePriceFields(){const manual=$('holdingPriceMode').value==='manual';$('manualPriceFields').hidden=!manual;$('holdingCurrency').disabled=!manual;if(!manual)$('holdingCurrency').value='KRW'}
function suggestSymbol(){const code=$('holdingCode').value.trim().toUpperCase(),s=symbols.get(code);if(s){$('holdingName').value=s.name;if(!editingHoldingId){const etf=s.instrument_type==='ETF';$('holdingRegion').value=etf?'UNKNOWN':'KR';$('holdingAssetClass').value=etf?'unknown':'equity';$('holdingStyle').value='unknown';$('holdingPriceMode').value='auto';$('holdingCurrency').value='KRW'}}else if(!editingHoldingId&&code){$('holdingPriceMode').value='manual'}updatePriceFields()}
$('holdingCode').oninput=suggestSymbol;$('holdingCode').onchange=suggestSymbol;$('holdingPriceMode').onchange=updatePriceFields;
function cancelHoldingEdit(){editingHoldingId=null;$('holdingForm').reset();$('holdingPriceDate').value=krDate();$('holdingSubmit').textContent='보유 종목 추가';$('cancelHoldingEdit').hidden=true;if(activeView==='account')$('holdingAccount').value=activeAccountId;updatePriceFields()}
function editHolding(id){const h=portfolio.holdings.find(h=>h.id===id);if(!h)return;pendingMarketCode=null;activeAccountId=h.account_id;switchView('account');editingHoldingId=id;$('holdingAccount').value=h.account_id;$('holdingCode').value=h.code;$('holdingName').value=h.name;$('holdingQuantity').value=h.quantity;$('holdingCost').value=h.cost??'';$('holdingCurrency').value=h.currency;$('holdingRegion').value=h.region;$('holdingAssetClass').value=h.asset_class||'equity';$('holdingStyle').value=h.style;$('holdingPriceMode').value=h.price_mode;$('holdingCurrentPrice').value=h.manual_price??'';$('holdingPriceDate').value=h.price_date||krDate();$('holdingMemo').value=h.memo;$('holdingDividendDay').value=h.dividend?.monthly_day??'';$('holdingDividendAmount').value=h.dividend?.amount_per_share??'';$('holdingSubmit').textContent='종목 정보 저장';$('cancelHoldingEdit').hidden=false;updatePriceFields();$('holdingEditor').scrollIntoView({block:'start',behavior:'smooth'})}
$('cancelHoldingEdit').onclick=cancelHoldingEdit;
$('holdingForm').onsubmit=e=>{e.preventDefault();if(activeView!=='account'||!portfolio.accounts.some(a=>a.id===activeAccountId))return toast('계좌 상세에서 종목을 입력하세요.');const account_id=activeView==='account'?activeAccountId:$('holdingAccount').value,code=$('holdingCode').value.trim().toUpperCase(),quantity=Number($('holdingQuantity').value),cost=$('holdingCost').value===''?null:Number($('holdingCost').value),mode=$('holdingPriceMode').value,currency=mode==='auto'?'KRW':$('holdingCurrency').value,manual_price=$('holdingCurrentPrice').value===''?null:Number($('holdingCurrentPrice').value),price_date=mode==='manual'?$('holdingPriceDate').value:null;
 if(!/^[A-Z0-9][A-Z0-9.^:-]{0,23}$/.test(code))return toast('종목코드 또는 티커를 확인하세요.');if(!validNumber(quantity,Number.MIN_VALUE)||(cost!==null&&!validNumber(cost)))return toast('수량·평균 매입가를 확인하세요.');if(mode==='auto'&&!symbols.has(code))return toast('국내 목록에 없는 종목은 직접 입력 시세를 선택하세요.');if(mode==='manual'&&((manual_price!==null&&!validNumber(manual_price))||!realDate(price_date)))return toast('현재가·가격 기준일을 확인하세요.');
 if(portfolio.holdings.some(h=>h.id!==editingHoldingId&&h.account_id===account_id&&h.code.toUpperCase()===code&&h.currency===currency))return toast('같은 계좌·종목·통화가 이미 있습니다. 기존 행을 수정하세요.');
 const rawDividend=$('holdingDividendAmount').value,dividendAmount=rawDividend.trim()===''?null:Number(rawDividend),dividendDay=$('holdingDividendDay').value;
 const dividend={monthly_day:dividendAmount===0||dividendDay===''?null:Number(dividendDay),amount_per_share:dividendAmount};
 try{validateDividend({quantity,dividend})}catch(error){return toast(error.message)}
 const old=portfolio.holdings.find(h=>h.id===editingHoldingId),name=$('holdingName').value.trim()||symbols.get(code)?.name||code;
 const h={id:old?.id||uid(),account_id,code,name,currency,quantity,cost,region:$('holdingRegion').value,style:$('holdingStyle').value,asset_class:$('holdingAssetClass').value,price_mode:mode,manual_price:mode==='manual'?manual_price:null,price_date,memo:$('holdingMemo').value,dividend};
 if(old){portfolio.audit.push({at:new Date().toISOString(),action:'종목 수정 전 값',holding:structuredClone(old)});portfolio.holdings=portfolio.holdings.map(x=>x.id===old.id?h:x)}else portfolio.holdings.push(h);cancelHoldingEdit();persist(old?'종목 정보 수정':'보유 종목 추가');toast(old?'종목 정보를 저장했습니다.':'보유 종목을 추가했습니다.');
};
function holdingTableAction(e){const edit=e.target.closest('[data-edit-position]'),del=e.target.closest('[data-delete-position]');if(edit)return editHolding(edit.dataset.editPosition);if(del){if(!confirm('현재 보유 목록에서 제거할까요? 이전 값과 평가 기록은 유지합니다.'))return;const h=portfolio.holdings.find(h=>h.id===del.dataset.deletePosition);portfolio.audit.push({at:new Date().toISOString(),action:'보유 삭제 전 값',holding:structuredClone(h)});portfolio.holdings=portfolio.holdings.filter(x=>x.id!==h.id);if(editingHoldingId===h.id)cancelHoldingEdit();persist('현재 보유 제거')}}
$('holdingRows').onclick=holdingTableAction;$('detailHoldingsRows').onclick=holdingTableAction;
$('marketRows').onclick=e=>{const add=e.target.closest('[data-add]');if(add){pendingMarketCode=add.dataset.add;cancelHoldingEdit();switchView('portfolio');toast('종목을 추가할 계좌 행을 선택하세요. 선택한 계좌 상세에 종목을 넣어드립니다.');$('accountRows').scrollIntoView({block:'start',behavior:'smooth'});return}const row=e.target.closest('[data-code]');if(row)selectStock(row.dataset.code)};
function renderSnapshots(){const points=portfolio.snapshots.slice().sort((a,b)=>a.date.localeCompare(b.date));$('snapshotRows').innerHTML=points.slice().reverse().map(s=>`<tr><td>${esc(s.date)}</td><td class="num">${money(s.value)}</td><td>${esc(s.status)}</td><td>${esc(s.price_range)}</td><td class="data-date">${esc(s.recorded_at)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">저장한 평가 기록이 없습니다.</td></tr>';if(activeView==='files')drawChart('snapshotChart','snapshotTip',aggregate(points.map(s=>[s.date,s.value]),$('snapshotFrequency').value),'계좌 대시보드에서 오늘 평가 기록을 저장하세요.')}
$('capture').onclick=()=>{const v=valuation();if(!v.hasKnown)return toast('현금 또는 보유 종목을 먼저 입력하세요.');const day=krDate(),old=portfolio.snapshots.find(s=>s.date===day);if(old&&!confirm('오늘 기록을 정정할까요? 이전 값은 보존합니다.'))return;if(v.missing&&!confirm('미확인 '+v.missing+'건을 제외한 부분 평가액을 기록할까요?'))return;if(old)portfolio.audit.push({at:new Date().toISOString(),action:'평가 기록 정정 전 값',snapshot:structuredClone(old)});portfolio.snapshots=portfolio.snapshots.filter(s=>s.date!==day);portfolio.snapshots.push({date:day,value:v.total,status:v.missing?'부분 평가 · 미확인 '+v.missing+'건':'등록 범위 평가',price_range:v.dates.length?v.dates[0]+' ~ '+v.dates.at(-1):'현금만',recorded_at:new Date().toISOString(),accounts:structuredClone(portfolio.accounts),holdings:structuredClone(portfolio.holdings),fx:structuredClone(portfolio.fx),prices:portfolio.holdings.map(h=>({id:h.id,...resolvedHolding(h)}))});persist('일별 평가 기록 확정');toast('평가 기록을 저장했습니다. 연결된 일별 기록 폴더로 자동 저장합니다.')};
$('snapshotFrequency').onchange=renderSnapshots;
$('exportCSV').onclick=()=>{const accounts=new Map(portfolio.accounts.map(a=>[a.id,a.name])),rows=[['account','code','name','currency','average_cost','quantity','current_price','price_date','value_krw','pnl_native','pnl_pct','region','style','asset_class','memo'],...portfolio.holdings.map(h=>{const r=resolvedHolding(h);return [accounts.get(h.account_id),h.code,h.name,h.currency,h.cost,h.quantity,r.price,r.day,r.value,r.pnl,r.pnlPct,REGION_LABELS[h.region],STYLE_LABELS[compositionStyle(h)??h.style],ASSET_LABELS[h.asset_class||'equity'],h.memo]})];download('\ufeff'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n'),'krx_holdings_'+krDate()+'.csv','text/csv;charset=utf-8')};
function validateDividend(h){
 if(h.dividend===undefined)return;
 const d=h.dividend;
 if(!d||typeof d!=='object'||Array.isArray(d)||!(d.monthly_day===null||Number.isInteger(d.monthly_day)&&d.monthly_day>=1&&d.monthly_day<=31)||!(d.amount_per_share===null||validNumber(d.amount_per_share)))throw Error('예상 배당일·배당액을 확인하세요.');
 if(d.amount_per_share>0&&(d.monthly_day===null||!Number.isFinite(d.amount_per_share*h.quantity)))throw Error('배당액이 있으면 매월 1~31일의 일정을 입력하세요. 금액·수량도 확인하세요.');
}
function expectedDividendDate(month,day){
 if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)||!realDate(month+'-01')||!Number.isInteger(day)||day<1||day>31)return null;
 const first=new Date(month+'-01T00:00:00Z');first.setUTCMonth(first.getUTCMonth()+1);first.setUTCDate(0);
 return month+'-'+String(Math.min(day,first.getUTCDate())).padStart(2,'0');
}
function dividendAmountText(value,currency){
 if(value===null)return '미입력';
 const text=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:8}).format(value);
 return currency==='USD'?'US$ '+text:text+' 원';
}
function dividendTotals(rows){
 const amounts={KRW:0,USD:0};for(const row of rows)if(row.amount!==null)amounts[row.holding.currency]+=row.amount;
 const missingFx=amounts.USD>0&&portfolio.fx.usd_krw===null;
 return {amounts,missingFx,krw:missingFx?null:amounts.KRW+amounts.USD*(portfolio.fx.usd_krw??0)};
}
function dividendForecast(month,accountId=''){
 const accounts=new Map(portfolio.accounts.map(a=>[a.id,a]));
 const rows=portfolio.holdings.filter(h=>!accountId||h.account_id===accountId).filter(h=>{
  const amount=h.dividend?.amount_per_share;
  return amount===0?false:amount>0||h.style==='dividend';
 }).map(h=>{
  const perShare=h.dividend?.amount_per_share??null,day=h.dividend?.monthly_day??null;
  const amount=perShare===null?null:perShare*h.quantity;
  return {holding:h,account:accounts.get(h.account_id),perShare,day,amount,date:expectedDividendDate(month,day)};
 });
 const configured=rows.filter(row=>row.amount!==null&&row.amount>0&&row.date);
 const grouped=new Map();
 for(const row of configured){if(!grouped.has(row.date))grouped.set(row.date,[]);grouped.get(row.date).push(row)}
 const schedules=[...grouped].sort(([a],[b])=>a.localeCompare(b)).map(([date,items])=>({date,rows:items,...dividendTotals(items)}));
 return {rows,configured,schedules,pending:rows.length-configured.length,...dividendTotals(configured)};
}
function dividendConvertedText(totals){return totals.missingFx?'<span class="muted">환율 미입력</span>':money(totals.krw)}
function dividendAccountGroups(forecast){
 const configured=new Set(forecast.configured);
 return portfolio.accounts.map(account=>{
  const rows=forecast.rows.filter(row=>row.holding.account_id===account.id).slice().sort((a,b)=>(a.day??32)-(b.day??32)||(a.holding.name||a.holding.code).localeCompare(b.holding.name||b.holding.code,'ko'));
  const entered=rows.filter(row=>configured.has(row));
  return {account,rows,configured:entered,pending:rows.length-entered.length,...dividendTotals(entered)};
 }).filter(group=>group.rows.length>0);
}
function dividendHoldingRow(row){
 const h=row.holding,converted=dividendTotals([row]);
 const schedule=row.day?'매월 '+row.day+'일':'일정 미입력';
 return `<tr><td class="name-cell"><b>${esc(h.name||h.code)}</b><small>${esc(h.code)} · ${esc(h.currency)}</small></td><td class="num">${fmt(h.quantity,6)}</td><td>${schedule}${row.date?'<div class="data-date">'+esc(row.date)+'</div>':''}</td><td class="num">${dividendAmountText(row.perShare,h.currency)}</td><td class="num">${dividendAmountText(row.amount,h.currency)}</td><td class="num">${row.amount===null?'미입력':dividendConvertedText(converted)}</td><td><button class="mini-action" data-edit-dividend="${esc(h.id)}">배당 정보 수정</button></td></tr>`;
}
function dividendAccountHoldings(forecast,month){
 return dividendAccountGroups(forecast).map(group=>{
  const pendingOnly=!group.configured.length&&group.pending>0;
  const native=pendingOnly?'미입력':'<b>'+dividendAmountText(group.amounts.KRW,'KRW')+'</b><div class="data-date">'+dividendAmountText(group.amounts.USD,'USD')+'</div>';
  const converted=pendingOnly?'미입력':dividendConvertedText(group);
  return `<tr class="dividend-account-group" data-dividend-account="${esc(group.account.id)}"><th colspan="7" scope="row"><b>${esc(group.account.name)}</b><span>${esc(month)} · ${group.rows.length}개 보유행</span></th></tr>`+group.rows.map(dividendHoldingRow).join('')+`<tr class="dividend-account-total"><th colspan="4" scope="row">${esc(group.account.name)} · ${esc(month)} 예상 배당 합계<small>일정·금액 입력분 ${group.configured.length}개 · 세전</small></th><td class="num">${native}</td><td class="num"><b>${converted}</b></td><td class="data-date">${group.pending?'미입력 '+group.pending+'개 제외':'입력 완료'}</td></tr>`;
 }).join('')||'<tr><td colspan="7" class="empty">등록된 배당 종목이 없습니다. 계좌 상세에서 예상 배당액과 일정을 입력하세요. 예상액 0인 종목은 제외됩니다.</td></tr>';
}
function dividendAccountSchedule(forecast){
 const dates=forecast.schedules.map(group=>group.date);
 const groups=dividendAccountGroups(forecast).map(group=>({...group,cells:dates.map(date=>{
  const rows=group.configured.filter(row=>row.date===date);
  return {date,rows,...dividendTotals(rows)};
 })}));
 return {dates,groups,hasPending:forecast.pending>0};
}
function dividendMatrixAmount(totals,pendingOnly=false){
 if(pendingOnly)return '<span class="muted">미입력</span>';
 const native=totals.amounts.USD>0?'<span class="data-date">'+(totals.amounts.KRW>0?dividendAmountText(totals.amounts.KRW,'KRW')+' · ':'')+dividendAmountText(totals.amounts.USD,'USD')+'</span>':'';
 return dividendConvertedText(totals)+native;
}
function dividendAccountScheduleTable(forecast){
 const matrix=dividendAccountSchedule(forecast),columns=matrix.dates.length+2+(matrix.hasPending?1:0);
 const head='<tr><th scope="col">계좌</th>'+matrix.dates.map(date=>`<th scope="col" class="num" title="${esc(date)}">${Number(date.slice(-2))}일</th>`).join('')+(matrix.hasPending?'<th scope="col" class="num">미입력</th>':'')+'<th scope="col" class="num">월 합계</th></tr>';
 const rows=matrix.groups.map(group=>`<tr><th scope="row">${esc(group.account.name)}</th>`+group.cells.map(cell=>`<td class="num">${cell.rows.length?dividendMatrixAmount(cell):'<span class="muted" title="예정 배당 없음">—</span>'}</td>`).join('')+(matrix.hasPending?`<td class="num data-date">${group.pending?group.pending+'건':'—'}</td>`:'')+`<td class="num dividend-matrix-total"><b>${dividendMatrixAmount(group,!group.configured.length&&group.pending>0)}</b>${group.pending&&group.configured.length?'<div class="data-date">입력분</div>':''}</td></tr>`).join('')||`<tr><td colspan="${columns}" class="empty">계좌 상세에서 예상 배당액과 일정을 입력하세요.</td></tr>`;
 const foot='<tr><th scope="row">전체 합계</th>'+forecast.schedules.map(group=>`<td class="num">${dividendMatrixAmount(group)}</td>`).join('')+(matrix.hasPending?`<td class="num data-date">${forecast.pending}건</td>`:'')+`<td class="num dividend-matrix-total"><b>${dividendMatrixAmount(forecast,!forecast.configured.length&&forecast.pending>0)}</b>${forecast.pending&&forecast.configured.length?'<div class="data-date">입력분</div>':''}</td></tr>`;
 return {head,rows,foot};
}
function renderDividends(){
 const monthInput=$('dividendMonth'),filter=$('dividendAccountFilter'),oldAccount=filter.value;
 if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthInput.value)||!realDate(monthInput.value+'-01'))monthInput.value=krDate().slice(0,7);
 filter.innerHTML='<option value="">전체 계좌</option>'+portfolio.accounts.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');
 filter.value=portfolio.accounts.some(a=>a.id===oldAccount)?oldAccount:'';
 const forecast=dividendForecast(monthInput.value,filter.value);
 const matrix=dividendAccountScheduleTable(forecast);
 $('dividendMatrixMonth').textContent=monthInput.value+' · 세전 · 원화 환산';
 $('dividendMatrixHead').innerHTML=matrix.head;$('dividendMatrixRows').innerHTML=matrix.rows;$('dividendMatrixTotals').innerHTML=matrix.foot;
 $('dividendMonthlyTotal').textContent=forecast.missingFx?'환율 미입력':!forecast.configured.length&&forecast.pending?'예상액 미입력':money(forecast.krw);
 $('dividendNativeTotal').textContent='KRW '+dividendAmountText(forecast.amounts.KRW,'KRW')+' · '+dividendAmountText(forecast.amounts.USD,'USD');
 $('dividendHoldingCount').textContent=forecast.rows.length;$('dividendScheduleCount').textContent=forecast.schedules.length;$('dividendPendingCount').textContent=forecast.pending;
 $('dividendSummaryNote').textContent=monthInput.value+' · 합계는 일정과 금액이 입력된 '+forecast.configured.length+'개 보유행의 세전 예상액입니다.'+(forecast.pending?' 미입력 '+forecast.pending+'개 보유행은 금액 합계에서 제외했습니다.':'')+(forecast.missingFx?' 달러 금액을 원화로 더하려면 왼쪽 환율을 입력하세요.':'');
 $('dividendScheduleRows').innerHTML=forecast.schedules.map(group=>`<tr><td><b>${esc(group.date)}</b></td><td class="num">${group.rows.length}</td><td class="num">${dividendAmountText(group.amounts.KRW,'KRW')}</td><td class="num">${dividendAmountText(group.amounts.USD,'USD')}</td><td class="num"><b>${dividendConvertedText(group)}</b></td></tr>`).join('')||'<tr><td colspan="5" class="empty">일정과 예상 배당액을 입력하면 날짜별 합계가 표시됩니다.</td></tr>';
 $('dividendScheduleTotals').innerHTML=`<tr class="account-total-row"><th scope="row">월 예상 합계 · 입력분</th><td class="num">${forecast.configured.length}</td><td class="num">${dividendAmountText(forecast.amounts.KRW,'KRW')}</td><td class="num">${dividendAmountText(forecast.amounts.USD,'USD')}</td><td class="num"><b>${!forecast.configured.length&&forecast.pending?'미입력':dividendConvertedText(forecast)}</b></td></tr>`;
 $('dividendHoldingRows').innerHTML=dividendAccountHoldings(forecast,monthInput.value);
 renderDividendReceipts();
}
$('dividendMonth').onchange=renderDividends;$('dividendAccountFilter').onchange=renderDividends;
$('dividendHoldingRows').onclick=e=>{const button=e.target.closest('[data-edit-dividend]');if(button){editHolding(button.dataset.editDividend);$('holdingDividendAmount').focus()}};

// Actual receipts are independent of current holdings and expected dividends.
function validateDividendReceipts(doc){
 if(doc.dividend_receipts===undefined)return;
 if(!Array.isArray(doc.dividend_receipts)||doc.dividend_receipts.length>100000)throw Error('실제 배당 수령 기록 목록을 확인하세요.');
 const ids=new Set(),text=(v,max)=>typeof v==='string'&&v.trim().length>0&&v.length<=max;
 for(const r of doc.dividend_receipts){
  if(!r||!text(r.id,100)||ids.has(r.id)||!text(r.account_id,100)||!text(r.account_name,80)||!text(r.name,100)||typeof r.code!=='string'||!/^[A-Za-z0-9][A-Za-z0-9.^:-]{0,23}$/.test(r.code)||!realDate(r.received_on)||!['KRW','USD'].includes(r.currency)||!validNumber(r.amount)||r.amount>1e15||!(r.usd_krw===null||validNumber(r.usd_krw,Number.MIN_VALUE)&&r.usd_krw<=1e7)||r.currency==='KRW'&&r.usd_krw!==null||typeof r.memo!=='string'||r.memo.length>300||!text(r.created_at,40)||!text(r.updated_at,40)||Number.isNaN(Date.parse(r.created_at))||Number.isNaN(Date.parse(r.updated_at)))throw Error('배당 수령 기록의 계좌·종목·날짜·금액·환율을 확인하세요.');
  ids.add(r.id);
 }
 // Monthly summaries are a derived cache. Rebuild only when changing/exporting receipts.
 if(doc.dividend_monthly_summary!==undefined&&(!Array.isArray(doc.dividend_monthly_summary)||doc.dividend_monthly_summary.length>100000))throw Error('월별 배당 집계 목록을 확인하세요.');
}
function receiptTotals(receipts){
 const amounts={KRW:0,USD:0};let known=0,missing=0;
 for(const r of receipts){amounts[r.currency]+=r.amount;if(r.currency==='KRW')known+=r.amount;else if(r.amount===0)continue;else if(r.usd_krw===null)missing++;else known+=r.amount*r.usd_krw}
 return {amounts,krw_total:missing?null:known,known_krw:known,missing_fx_count:missing};
}
function previousReceiptMonth(month){const date=new Date(month+'-01T00:00:00Z');date.setUTCMonth(date.getUTCMonth()-1);return date.toISOString().slice(0,7)}
function monthlyDividendReceipts(receipts){
 const grouped=new Map();
 for(const r of receipts){const month=r.received_on.slice(0,7);if(!grouped.has(month))grouped.set(month,[]);grouped.get(month).push(r)}
 const rows=[...grouped].sort(([a],[b])=>a.localeCompare(b)).map(([month,items])=>{
  const byAccount=new Map();for(const r of items){if(!byAccount.has(r.account_id))byAccount.set(r.account_id,[]);byAccount.get(r.account_id).push(r)}
  const accounts=[...byAccount].sort(([a],[b])=>a.localeCompare(b)).map(([account_id,records])=>({account_id,account_name:records[0].account_name,receipt_count:records.length,...receiptTotals(records)}));
  return {month,receipt_count:items.length,...receiptTotals(items),accounts,change_krw:null,change_pct:null,change_status:'전월 미기록'};
 });
 const lookup=new Map(rows.map(row=>[row.month,row]));
 for(const row of rows){const previous=lookup.get(previousReceiptMonth(row.month));if(!previous)continue;
  if(row.krw_total===null||previous.krw_total===null){row.change_status='환율 미입력';continue}
  row.change_krw=row.krw_total-previous.krw_total;row.change_pct=previous.krw_total>0?row.change_krw/previous.krw_total*100:null;row.change_status=previous.krw_total===0?'전월 0원':'';
 }
 return rows;
}
function receiptExportDocument(doc){return doc.dividend_receipts===undefined?{...doc}:{...doc,dividend_monthly_summary:monthlyDividendReceipts(doc.dividend_receipts)}}
function persistDividendReceipts(reason){portfolio.dividend_monthly_summary=monthlyDividendReceipts(portfolio.dividend_receipts||[]);persist(reason)}
function receiptAccountOptions(selected='',includeHistorical=false){
 const accounts=portfolio.accounts.map(a=>({id:a.id,name:a.name}));
 if(includeHistorical)for(const r of portfolio.dividend_receipts||[])if(!accounts.some(a=>a.id===r.account_id))accounts.push({id:r.account_id,name:r.account_name+' · 기록 계좌'});
 return accounts.map(a=>`<option value="${esc(a.id)}"${a.id===selected?' selected':''}>${esc(a.name)}</option>`).join('');
}
function refreshReceiptHoldingOptions(){
 const select=$('receiptHolding'),old=select.value;
 select.innerHTML='<option value="">종목 선택 또는 직접 입력</option>'+portfolio.holdings.filter(h=>h.account_id===$('receiptAccount').value).map(h=>`<option value="${esc(h.id)}">${esc(h.name||h.code)} · ${esc(h.code)}</option>`).join('');
 if([...portfolio.holdings].some(h=>h.id===old&&h.account_id===$('receiptAccount').value))select.value=old;
}
function updateReceiptCurrency(){const usd=$('receiptCurrency').value==='USD';$('receiptFxField').hidden=!usd;$('receiptFx').disabled=!usd}
function resetDividendReceiptForm(){
 editingReceiptId=null;$('receiptForm').reset();$('receiptAccount').innerHTML=receiptAccountOptions();$('receiptDate').value=krDate();$('receiptDate').max=krDate();$('receiptCurrency').value='KRW';$('receiptSubmit').textContent='수령 내역 저장';$('cancelReceiptEdit').hidden=true;refreshReceiptHoldingOptions();updateReceiptCurrency();
}
function renderDividendReceipts(){
 const select=$('receiptAccount'),old=select.value;
 select.innerHTML=receiptAccountOptions(old,editingReceiptId!==null);if(!select.value&&portfolio.accounts.length)select.value=portfolio.accounts[0].id;
 if(!$('receiptDate').value){$('receiptDate').value=krDate();$('receiptDate').max=krDate()}
 refreshReceiptHoldingOptions();updateReceiptCurrency();
 const month=$('receiptListMonth');if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month.value))month.value=krDate().slice(0,7);
 const filter=$('receiptListAccount'),oldFilter=filter.value;filter.innerHTML='<option value="">전체 계좌</option>'+receiptAccountOptions(oldFilter,true);filter.value=oldFilter;
 const rows=(portfolio.dividend_receipts||[]).filter(r=>r.received_on.startsWith(month.value)&&(!filter.value||r.account_id===filter.value)).slice().sort((a,b)=>b.received_on.localeCompare(a.received_on)||a.account_name.localeCompare(b.account_name,'ko')||a.name.localeCompare(b.name,'ko'));
 $('receiptRows').innerHTML=rows.map(r=>`<tr><td>${esc(r.received_on)}</td><td>${esc(r.account_name)}</td><td class="name-cell"><b>${esc(r.name)}</b><small>${esc(r.code)}</small></td><td class="num">${dividendAmountText(r.amount,r.currency)}</td><td class="num">${r.currency==='USD'?(r.usd_krw===null?'미입력':fmt(r.usd_krw,4)):'—'}</td><td class="num">${money(receiptTotals([r]).krw_total)}</td><td>${esc(r.memo)}</td><td class="actions-cell"><button type="button" data-edit-receipt="${esc(r.id)}">수정</button> <button type="button" class="danger" data-delete-receipt="${esc(r.id)}">삭제</button></td></tr>`).join('')||'<tr><td colspan="8" class="empty">이 월에 기록된 실제 배당 수령 내역이 없습니다.</td></tr>';
 const totals=receiptTotals(rows);$('receiptListSummary').textContent=month.value+' · '+rows.length+'건 · KRW '+dividendAmountText(totals.amounts.KRW,'KRW')+' · '+dividendAmountText(totals.amounts.USD,'USD')+' · 원화 환산 '+(totals.krw_total===null?'환율 미입력 '+totals.missing_fx_count+'건':money(totals.krw_total));
}
function renderDividendReceiptHistory(){
 const account=$('receiptHistoryAccount'),old=account.value;account.innerHTML='<option value="">전체 계좌</option>'+receiptAccountOptions(old,true);account.value=old;
 const receipts=(portfolio.dividend_receipts||[]).filter(r=>!account.value||r.account_id===account.value);
 const year=$('receiptHistoryYear').value;
 const rows=monthlyDividendReceipts(receipts).filter(row=>!year||row.month.startsWith(year+'-')).reverse();
 $('receiptMonthlyRows').innerHTML=rows.map(row=>`<tr><td><b>${esc(row.month)}</b></td><td class="num">${row.receipt_count}</td><td class="num">${dividendAmountText(row.amounts.KRW,'KRW')}</td><td class="num">${dividendAmountText(row.amounts.USD,'USD')}</td><td class="num">${row.krw_total===null?'환율 미입력 '+row.missing_fx_count+'건':money(row.krw_total)}</td><td class="num ${colorClass(row.change_krw)}">${row.change_krw===null?'—':(row.change_krw>0?'+':row.change_krw<0?'−':'')+money(Math.abs(row.change_krw))}</td><td class="num ${colorClass(row.change_pct)}">${percent(row.change_pct)}${row.change_status?'<div class="data-date">'+esc(row.change_status)+'</div>':''}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">배당주 관리 하단에서 실제 수령 내역을 저장하면 월별 기록이 표시됩니다.</td></tr>';
 $('receiptMonthlyNote').textContent='실제 입금일 기준 · 건별 저장 환율 사용 · '+rows.length+'개 월 표시. 전월 기록이나 환율이 없으면 변화량을 보류합니다. 전월 0원은 변화율을 산출하지 않습니다. 미기록 월은 0원으로 간주하지 않습니다.';
}
function submitDividendReceipt(e){
 e.preventDefault();
 const old=(portfolio.dividend_receipts||[]).find(r=>r.id===editingReceiptId),account=portfolio.accounts.find(a=>a.id===$('receiptAccount').value);
 if(editingReceiptId&&!old)return toast('수정할 수령 기록이 없습니다. 다시 선택하세요.');
 if(!account&&!(old&&old.account_id===$('receiptAccount').value))return toast('계좌를 선택하세요.');
 const received_on=$('receiptDate').value,rawAmount=$('receiptAmount').value,rawFx=$('receiptFx').value,currency=$('receiptCurrency').value,now=new Date().toISOString();
 if(!realDate(received_on)||received_on>krDate()||rawAmount.trim()==='')return toast('실제 수령일과 입금액을 입력하세요. 미래 수령일은 기록할 수 없습니다.');
 const record={id:old?.id||uid(),account_id:account?.id||old.account_id,account_name:account?.name||old.account_name,code:$('receiptCode').value.trim().toUpperCase(),name:$('receiptName').value.trim(),currency,amount:Number(rawAmount),received_on,usd_krw:currency==='USD'&&rawFx.trim()!==''?Number(rawFx):null,memo:$('receiptMemo').value.trim(),created_at:old?.created_at||now,updated_at:now};
 try{validateDividendReceipts({dividend_receipts:[record]})}catch(error){return toast(error.message)}
 if((portfolio.dividend_receipts||[]).some(r=>r.id!==record.id&&r.account_id===record.account_id&&r.code===record.code&&r.received_on===received_on&&r.currency===currency&&r.amount===record.amount)&&!confirm('같은 계좌·종목·수령일·금액의 기록이 있습니다. 별도 지급 건으로 추가할까요?'))return;
 const records=portfolio.dividend_receipts||[];
 if(!old&&records.length>=100000)return toast('수령 기록은 최대 100,000건까지 저장할 수 있습니다.');
 if(old)portfolio.audit.push({at:now,action:'배당 수령 수정 전 값',receipt:structuredClone(old)});
 portfolio.dividend_receipts=old?records.map(r=>r.id===old.id?record:r):[...records,record];
 $('receiptListMonth').value=received_on.slice(0,7);resetDividendReceiptForm();persistDividendReceipts(old?'배당 수령 수정':'배당 수령 추가');toast('실제 배당 수령 내역을 저장했습니다. 기록·파일에서 월별 변화를 확인하세요.');
}
function editDividendReceipt(id){
 const r=(portfolio.dividend_receipts||[]).find(item=>item.id===id);if(!r)return;
 switchView('dividends');editingReceiptId=id;$('receiptAccount').innerHTML=receiptAccountOptions(r.account_id,true);$('receiptAccount').value=r.account_id;refreshReceiptHoldingOptions();$('receiptHolding').value='';
 for(const [field,value] of Object.entries({receiptDate:r.received_on,receiptCode:r.code,receiptName:r.name,receiptCurrency:r.currency,receiptAmount:r.amount,receiptFx:r.usd_krw??'',receiptMemo:r.memo}))$(field).value=value;
 updateReceiptCurrency();$('receiptSubmit').textContent='수령 기록 수정';$('cancelReceiptEdit').hidden=false;$('receiptForm').scrollIntoView({block:'start',behavior:'smooth'});
}
function deleteDividendReceipt(id){
 const old=(portfolio.dividend_receipts||[]).find(r=>r.id===id);if(!old||!confirm('이 수령 기록을 삭제할까요? 삭제 전 값은 변경 이력과 직전 JSON에 보관됩니다.'))return;
 portfolio.audit.push({at:new Date().toISOString(),action:'배당 수령 삭제 전 값',receipt:structuredClone(old)});portfolio.dividend_receipts=portfolio.dividend_receipts.filter(r=>r.id!==id);if(editingReceiptId===id)resetDividendReceiptForm();persistDividendReceipts('배당 수령 삭제');
}
function exportDividendReceiptCSV(monthly=false){
 const doc=portfolio.dividend_receipts||[];
 const rows=monthly?[['month','receipt_count','krw_received','usd_received','total_krw_at_recorded_fx','missing_fx_count','change_krw','change_pct','change_status'],...monthlyDividendReceipts(doc).map(r=>[r.month,r.receipt_count,r.amounts.KRW,r.amounts.USD,r.krw_total,r.missing_fx_count,r.change_krw,r.change_pct,r.change_status])]:[['received_on','account','code','name','currency','received_amount','recorded_usd_krw','received_krw','memo'],...doc.slice().sort((a,b)=>a.received_on.localeCompare(b.received_on)).map(r=>[r.received_on,r.account_name,r.code,r.name,r.currency,r.amount,r.usd_krw,receiptTotals([r]).krw_total,r.memo])];
 download('\ufeff'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n'),(monthly?'dividend_monthly_':'dividend_receipts_')+krDate()+'.csv','text/csv;charset=utf-8');
}
$('receiptForm').onsubmit=submitDividendReceipt;$('cancelReceiptEdit').onclick=resetDividendReceiptForm;
$('receiptAccount').onchange=()=>{$('receiptHolding').value='';refreshReceiptHoldingOptions()};
$('receiptHolding').onchange=()=>{const h=portfolio.holdings.find(h=>h.id===$('receiptHolding').value&&h.account_id===$('receiptAccount').value);if(!h)return;$('receiptCode').value=h.code;$('receiptName').value=h.name;$('receiptCurrency').value=h.currency;$('receiptFx').value='';updateReceiptCurrency()};
$('receiptCurrency').onchange=()=>{$('receiptFx').value='';updateReceiptCurrency()};
$('receiptRows').onclick=e=>{const edit=e.target.closest('[data-edit-receipt]'),del=e.target.closest('[data-delete-receipt]');if(edit)editDividendReceipt(edit.dataset.editReceipt);else if(del)deleteDividendReceipt(del.dataset.deleteReceipt)};
$('receiptListMonth').onchange=renderDividendReceipts;$('receiptListAccount').onchange=renderDividendReceipts;
$('receiptHistoryAccount').onchange=renderDividendReceiptHistory;$('receiptHistoryYear').oninput=renderDividendReceiptHistory;
$('exportReceiptCSV').onclick=()=>exportDividendReceiptCSV(false);$('exportReceiptMonthlyCSV').onclick=()=>exportDividendReceiptCSV(true);
$('receiptRetrySave').onclick=()=>$('retryPortfolioSave').onclick();$('receiptExportJSON').onclick=()=>exportJSON();

init();switchView('portfolio');updatePriceFields();
