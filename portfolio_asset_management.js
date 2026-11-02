'use strict';
const ASSET_REGIONS={KR:'한국',US:'미국',GLOBAL:'글로벌',OTHER:'기타',UNKNOWN:'미분류'};
const ASSET_CATEGORIES={broad_index:'시장대표지수형',thematic:'섹터·테마형',factor:'배당·팩터형',bond:'채권형',mixed:'주식·채권혼합형',individual:'개별종목',cash_like:'현금성',other:'기타',unknown:'미분류'};
const ASSET_MANAGEMENT={active:'액티브',passive:'패시브',unknown:'운용방식 미확인'};
const ASSET_HEDGE={hedged:'환헤지',unhedged:'환노출',unknown:'환헤지 미확인'};
const ASSET_STRATEGIES={covered_call:'커버드콜',leverage:'레버리지',inverse:'인버스'};
let assetEditingKey=null;
function assetInstrumentKey(h){return h.currency+':'+h.code.toUpperCase()}
function suggestAssetClassification(h){
 const name=h.name||'',symbol=symbols.get(h.code),etf=symbol?.instrument_type==='ETF';
 let category='unknown';
 if(/혼합/.test(name)||h.asset_class==='mixed')category='mixed';
 else if(h.asset_class==='bond'||etf&&/국채|채권/.test(name))category='bond';
 else if(h.asset_class==='cash')category='cash_like';
 else if(symbol&&!etf)category='individual';
 else if(etf){
  if(/머니마켓|SOFR|CD금리|초단기/.test(name))category='cash_like';
  else if(/고배당|배당성장|배당다우|플러스배당/.test(name))category='factor';
  else if(/AI|반도체|로봇|금융|전력|인프라|바이오|테크|방산/.test(name))category='thematic';
  else if(/S&P500|나스닥100|코스피|KODEX\s*200/.test(name))category='broad_index';
  else if(h.style==='dividend')category='factor';
 }else if(h.asset_class==='other')category='other';
 const tags=[];if(/커버드콜/.test(name))tags.push('covered_call');if(/레버리지/.test(name))tags.push('leverage');if(/인버스/.test(name))tags.push('inverse');
 const themes=[];if(/AI|인공지능/.test(name))themes.push('AI');if(/반도체/.test(name))themes.push('반도체');if(/금융/.test(name))themes.push('금융');if(/인프라/.test(name))themes.push('인프라');
 return {region:/글로벌/.test(name)?'GLOBAL':h.region,category,management:/액티브/.test(name)?'active':h.code==='069500'?'passive':'unknown',hedge:/\(H\)|환헤지/.test(name)?'hedged':'unknown',tags,theme:themes.join(' · '),source:'자동 제안: 기존 입력·종목마스터·상품명 기반. 최신 운용사 설명서 확인 필요.',status:'suggested',reviewed_on:null,updated_at:new Date().toISOString()};
}
function assetClassification(h,doc=portfolio){return doc.asset_classifications?.[assetInstrumentKey(h)]||suggestAssetClassification(h)}
function assetRegion(h){return assetClassification(h).region}
function classifiedAssetType(h){const category=assetClassification(h).category;return ['broad_index','thematic','factor','individual'].includes(category)?'equity':category==='mixed'?'mixed':category==='bond'?'bond':category==='cash_like'?'cash':category==='other'?'other':h.asset_class||'equity'}
function validateAssetClassifications(doc){
 const records=doc.asset_classifications;if(records===undefined)return;
 if(!records||typeof records!=='object'||Array.isArray(records)||Object.keys(records).length>20000)throw Error('공통 자산 분류 목록을 확인하세요.');
 for(const [key,r] of Object.entries(records)){
  if(!/^(KRW|USD):[A-Z0-9][A-Z0-9.^:-]{0,23}$/.test(key)||!r||!Object.hasOwn(ASSET_REGIONS,r.region)||!Object.hasOwn(ASSET_CATEGORIES,r.category)||!Object.hasOwn(ASSET_MANAGEMENT,r.management)||!Object.hasOwn(ASSET_HEDGE,r.hedge)||!Array.isArray(r.tags)||r.tags.length>3||new Set(r.tags).size!==r.tags.length||r.tags.some(tag=>typeof tag!=='string'||!Object.hasOwn(ASSET_STRATEGIES,tag))||typeof r.theme!=='string'||r.theme.length>100||typeof r.source!=='string'||r.source.length>500||!['suggested','confirmed'].includes(r.status)||!(r.reviewed_on===null||realDate(r.reviewed_on))||r.status==='confirmed'&&!realDate(r.reviewed_on)||typeof r.updated_at!=='string'||r.updated_at.length>40||Number.isNaN(Date.parse(r.updated_at)))throw Error('공통 자산 분류의 지역·유형·전략·확인일을 확인하세요.');
 }
}
function seedAssetClassifications(doc){
 const next=structuredClone(doc),records={...(next.asset_classifications||{})},added=[];
 for(const h of next.holdings){const key=assetInstrumentKey(h);if(Object.hasOwn(records,key))continue;const r=suggestAssetClassification(h);
  const peers=next.holdings.filter(p=>assetInstrumentKey(p)===key);
  if(!/글로벌/.test(h.name)&&new Set(peers.map(p=>p.region)).size>1){r.region='UNKNOWN';r.source+=' 계좌별 기존 지역이 달라 확인 필요.'}
  records[key]=r;added.push(key);
 }
 if(added.length){next.asset_classifications=records;next.revision++;next.audit.push({at:new Date().toISOString(),action:'공통 자산 분류 제안 등록',keys:added})}
 validateAssetClassifications(next);return {document:next,added};
}
function assetBadges(r){return [ASSET_MANAGEMENT[r.management],ASSET_HEDGE[r.hedge],...r.tags.map(tag=>ASSET_STRATEGIES[tag])].map(label=>`<span class="badge">${esc(label)}</span>`).join(' ')}
function assetManagementData(){
 const account=$('assetAccountFilter').value,region=$('assetRegionFilter').value,category=$('assetCategoryFilter').value,style=$('assetStyleFilter').value,query=$('assetSearch').value.trim().toLowerCase();
 const holdings=portfolio.holdings.filter(h=>(!account||h.account_id===account)&&(!style||compositionStyle(h)===style));
 const groups=new Map();for(const h of holdings){const c=assetClassification(h),key=assetInstrumentKey(h);if(region&&c.region!==region||category&&c.category!==category||query&&!(h.name+' '+h.code+' '+c.theme).toLowerCase().includes(query))continue;if(!groups.has(key))groups.set(key,{key,classification:c,holdings:[]});groups.get(key).holdings.push(h)}
 const period=marketDayPeriod(),rows=[...groups.values()].map(row=>{const values=row.holdings.map(resolvedHolding),known=values.filter(v=>v.value!==null);return {...row,name:row.holdings[0].name,code:row.holdings[0].code,currency:row.holdings[0].currency,quantity:row.holdings.reduce((n,h)=>n+h.quantity,0),value:known.length?known.reduce((n,v)=>n+v.value,0):null,missing:values.length-known.length,dayChange:holdingGroupSummary(row.holdings,period,known.length>0).dayChange}}).sort((a,b)=>Object.keys(ASSET_CATEGORIES).indexOf(a.classification.category)-Object.keys(ASSET_CATEGORIES).indexOf(b.classification.category)||a.name.localeCompare(b.name,'ko'));
 const composition=compositionSummary();const selected=account?composition.rows.filter(row=>row.account.id===account&&row.metrics.hasKnown):composition.rows.filter(row=>row.metrics.hasKnown);
 const denominator=selected.reduce((n,row)=>n+row.metrics.total,0),complete=selected.length>0&&selected.every(row=>row.metrics.complete),cash=selected.some(row=>row.metrics.cash!==null)?selected.reduce((n,row)=>n+(row.metrics.cash??0),0):null;
 return {rows,denominator,complete,cash,share:value=>complete&&denominator>0&&value!==null?value/denominator*100:null};
}
function assetGroupAmount(rows,data){const known=rows.filter(row=>row.value!==null),amount=known.length?known.reduce((n,row)=>n+row.value,0):rows.length?null:0,missing=rows.some(row=>row.missing||row.value===null);return rows.length?amountAndShare(amount,missing?null:data.share(amount),missing):'<span class="muted">—</span>'}
function renderAssetManagement(){
 const account=$('assetAccountFilter'),old=account.value;account.innerHTML='<option value="">전체 계좌</option>'+portfolio.accounts.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');account.value=portfolio.accounts.some(a=>a.id===old)?old:'';
 const data=assetManagementData(),categories=Object.keys(ASSET_CATEGORIES),accounts=new Map(portfolio.accounts.map(a=>[a.id,a.name]));
 $('assetMatrixHead').innerHTML='<tr><th scope="col">투자 지역</th>'+categories.map(key=>`<th class="num" scope="col">${ASSET_CATEGORIES[key]}</th>`).join('')+'<th class="num" scope="col">보유자산 합계</th></tr>';
 $('assetMatrixRows').innerHTML=Object.entries(ASSET_REGIONS).map(([region,label])=>{const rows=data.rows.filter(row=>row.classification.region===region);return `<tr><th scope="row">${label}</th>`+categories.map(category=>`<td class="num">${assetGroupAmount(rows.filter(row=>row.classification.category===category),data)}</td>`).join('')+`<td class="num">${assetGroupAmount(rows,data)}</td></tr>`}).join('');
 $('assetMatrixTotals').innerHTML='<tr><th scope="row">유형별 합계</th>'+categories.map(category=>`<td class="num">${assetGroupAmount(data.rows.filter(row=>row.classification.category===category),data)}</td>`).join('')+`<td class="num">${assetGroupAmount(data.rows,data)}</td></tr>`;
 $('assetSummary').textContent='조회 '+data.rows.length+'개 종목 · '+data.rows.reduce((n,row)=>n+row.holdings.length,0)+'개 보유행 · 분류 확인 필요 '+data.rows.filter(row=>row.classification.status!=='confirmed').length+'개. 비중 기준: '+(account.value?'선택 계좌':'전체 계좌')+'의 현금 포함 총액 '+(data.complete?money(data.denominator):'미확인 금액 있음')+' · 직접 입력 현금 '+money(data.cash)+'. 현금성 ETF와 직접 입력 현금은 별도입니다.';
 $('assetRegionGroups').innerHTML=Object.entries(ASSET_REGIONS).map(([region,label])=>{const rows=data.rows.filter(row=>row.classification.region===region);if(!rows.length)return '';return `<details class="asset-region-group" open><summary><b>${label} 자산</b> · ${rows.length}개 종목 · ${assetGroupAmount(rows,data)}</summary><div class="table-scroll asset-position-scroll"><table class="asset-position-table"><thead><tr><th>종목</th><th>기본 유형</th><th>테마</th><th>운용전략</th><th>성장/배당 표시</th><th class="num">합산 수량</th><th class="num">평가액</th><th class="num">전일 대비</th><th>보유 계좌</th><th>분류 확인</th><th>수정</th></tr></thead><tbody>${rows.map((row,index)=>(index===0||rows[index-1].classification.category!==row.classification.category?`<tr class="asset-category-heading"><th colspan="11" scope="rowgroup">${ASSET_CATEGORIES[row.classification.category]} · ${assetGroupAmount(rows.filter(r=>r.classification.category===row.classification.category),data)}</th></tr>`:'')+`<tr><td class="name-cell"><b>${esc(row.name)}</b><small>${esc(row.code)} · ${esc(row.currency)}</small></td><td>${ASSET_CATEGORIES[row.classification.category]}</td><td>${esc(row.classification.theme||'—')}</td><td class="asset-badges">${assetBadges(row.classification)}</td><td>${esc([...new Set(row.holdings.map(h=>STYLE_LABELS[compositionStyle(h)??h.style]))].join(' · '))}</td><td class="num">${fmt(row.quantity,6)}</td><td class="num">${assetGroupAmount([row],data)}</td><td class="num">${dailyChangeCell(row.dayChange)}</td><td>${esc([...new Set(row.holdings.map(h=>accounts.get(h.account_id)||'미확인'))].join(', '))}</td><td><span class="badge ${row.classification.status==='confirmed'?'dividend':''}">${row.classification.status==='confirmed'?'확인 완료':'자동 제안 · 확인 필요'}</span><div class="data-date">${esc(row.classification.reviewed_on||'미확인')}</div></td><td><button type="button" data-edit-classification="${esc(row.key)}">분류 수정</button></td></tr>`).join('')}</tbody></table></div></details>`}).join('')||'<div class="empty">조건에 맞는 보유 종목이 없습니다.</div>';
}
function cancelAssetClassificationEdit(){assetEditingKey=null;$('assetClassificationEditor').hidden=true}
function editAssetClassification(key){
 const h=portfolio.holdings.find(h=>assetInstrumentKey(h)===key);if(!h)return;const r=assetClassification(h);assetEditingKey=key;
 $('assetEditorTitle').textContent=(h.name||h.code)+' · '+h.code+' · 모든 계좌 공통';
 for(const [id,value] of Object.entries({assetRegion:r.region,assetCategory:r.category,assetManagement:r.management,assetHedge:r.hedge,assetTheme:r.theme,assetSource:r.source,assetReviewed:r.reviewed_on||krDate()}))$(id).value=value;
 for(const input of document.querySelectorAll('#assetClassificationForm input[name="strategy"]'))input.checked=r.tags.includes(input.value);
 $('assetConfirmed').checked=true;$('assetClassificationEditor').hidden=false;$('assetClassificationEditor').scrollIntoView({block:'start',behavior:'smooth'});
}
function saveAssetClassification(e){
 e.preventDefault();if(!assetEditingKey||!portfolio.holdings.some(h=>assetInstrumentKey(h)===assetEditingKey))return toast('수정할 종목을 다시 선택하세요.');
 const record={region:$('assetRegion').value,category:$('assetCategory').value,management:$('assetManagement').value,hedge:$('assetHedge').value,tags:[...document.querySelectorAll('#assetClassificationForm input[name="strategy"]')].filter(input=>input.checked).map(input=>input.value),theme:$('assetTheme').value.trim(),source:$('assetSource').value.trim(),status:$('assetConfirmed').checked?'confirmed':'suggested',reviewed_on:$('assetConfirmed').checked?$('assetReviewed').value:null,updated_at:new Date().toISOString()};
 const next={...(portfolio.asset_classifications||{}),[assetEditingKey]:record};try{validateAssetClassifications({asset_classifications:next})}catch(error){return toast(error.message)}
 portfolio.audit.push({at:new Date().toISOString(),action:'공통 자산 분류 수정',key:assetEditingKey,before:portfolio.asset_classifications?.[assetEditingKey]||null,after:structuredClone(record)});portfolio.asset_classifications=next;cancelAssetClassificationEdit();persist('공통 자산 분류 수정');toast('같은 종목을 보유한 모든 계좌의 분류를 저장했습니다.');
}
function applyAssetSuggestions(){const result=seedAssetClassifications(portfolio);if(!result.added.length)return toast('미저장 분류 제안이 없습니다.');portfolio.asset_classifications=result.document.asset_classifications;portfolio.audit.push({at:new Date().toISOString(),action:'공통 자산 분류 제안 등록',keys:result.added});persist('공통 자산 분류 제안 저장');toast(result.added.length+'개 종목의 제안 분류를 저장했습니다. 확인 후 수정할 수 있습니다.')}
function updateSharedClassificationFromHolding(h,old){
 const key=assetInstrumentKey(h),record=portfolio.asset_classifications?.[key];if(!record)return;
 const oldType=old?classifiedAssetType(old):classifiedAssetType(h);
 if(record.region===h.region&&oldType===h.asset_class)return;
 const category=h.asset_class!==oldType?({bond:'bond',mixed:'mixed',cash:'cash_like',other:'other',unknown:'unknown',equity:record.category==='individual'?'individual':'unknown'}[h.asset_class]||'unknown'):record.category;
 portfolio.audit.push({at:new Date().toISOString(),action:'계좌 상세에서 공통 분류 수정 전 값',key,classification:structuredClone(record)});
 portfolio.asset_classifications={...portfolio.asset_classifications,[key]:{...record,region:h.region,category,status:'confirmed',reviewed_on:krDate(),updated_at:new Date().toISOString(),source:'사용자 계좌 상세 입력에서 공통 지역·유형 수정'}};
}
function overviewRatioSet(label,entries){
 const width=value=>value===null?0:Math.max(0,Math.min(100,value));return `<div class="overview-ratio-row"><div class="overview-ratio-heading">${esc(label)}</div><div class="overview-ratio-values multi" style="grid-template-columns:repeat(${entries.length},minmax(0,1fr))">${entries.map(([name,value,kind])=>`<span class="${kind||''}">${esc(name)} <b>${value===null?'—':fmt(value,1)+'%'}</b></span>`).join('')}</div><div class="overview-ratio-track" aria-hidden="true">${entries.map(([name,value,kind])=>`<i class="${kind||''}" style="width:${width(value)}%"></i>`).join('')}</div></div>`;
}
for(const id of ['assetRegionFilter','assetRegion'])$(id).innerHTML=(id.endsWith('Filter')?'<option value="">전체 지역</option>':'')+Object.entries(ASSET_REGIONS).map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
for(const id of ['assetCategoryFilter','assetCategory'])$(id).innerHTML=(id.endsWith('Filter')?'<option value="">전체 상품 유형</option>':'')+Object.entries(ASSET_CATEGORIES).map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
$('assetManagement').innerHTML=Object.entries(ASSET_MANAGEMENT).map(([key,label])=>`<option value="${key}">${label}</option>`).join('');$('assetHedge').innerHTML=Object.entries(ASSET_HEDGE).map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
for(const id of ['assetAccountFilter','assetRegionFilter','assetCategoryFilter','assetStyleFilter'])$(id).onchange=renderAssetManagement;$('assetSearch').oninput=renderAssetManagement;
$('assetRegionGroups').onclick=e=>{const button=e.target.closest('[data-edit-classification]');if(button)editAssetClassification(button.dataset.editClassification)};
$('assetClassificationForm').onsubmit=saveAssetClassification;$('assetCancelEdit').onclick=cancelAssetClassificationEdit;$('assetApplySuggestions').onclick=applyAssetSuggestions;

$('assetExportCSV').onclick=()=>$('exportCSV').onclick();
