'use strict';
// A single fixed server file; requests are serialized and guarded by file version.
let portfolioStorageMode='checking',portfolioStorageVersion=null,portfolioStoragePath='',portfolioStorageLayout=0,portfolioStorageMessage='자동 저장 연결을 확인하는 중…';
let portfolioSavePending=null,portfolioSaveBusy=false,portfolioSaveBlocked=false,portfolioDiskDocument=null,portfolioSavedKey=null;
const portfolioIsLocal=['127.0.0.1','localhost'].includes(location.hostname);
function portfolioKey(doc){return doc.document_id+':'+doc.revision}
function portfolioHasData(doc){return !!(doc.holdings.length||(doc.dividend_receipts||[]).length||doc.snapshots.length||doc.audit.length||doc.accounts.some(a=>a.cash!==null))}
function renderPortfolioStorageState(){
 $('portfolioAutoSaveStatus').textContent=portfolioStorageMessage;
 $('receiptSaveStatus').textContent=portfolioStorageMessage;$('receiptHistorySaveStatus').textContent=portfolioStorageMessage;
 $('loadDiskPortfolio').hidden=!portfolioSaveBlocked||!portfolioDiskDocument;
 $('replaceDiskPortfolio').hidden=!portfolioSaveBlocked;
 if(portfolioSavedKey===portfolioKey(portfolio)&&!portfolioSavePending&&!portfolioSaveBusy&&!portfolioSaveBlocked)$('saveState').textContent='JSON 자동 저장 완료';
}
function portfolioStorageMessageSet(message){portfolioStorageMessage=message;renderPortfolioStorageState()}
async function portfolioRequest(method,body,path='/api/portfolio'){
 const response=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
 const result=await response.json();
 if(!response.ok){const error=Error(result.error||'JSON 파일 저장 실패');error.status=response.status;throw error}
 return result;
}
function comparablePortfolio(doc){
 const clean=value=>Array.isArray(value)?value.map(clean):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().filter(key=>key!=='exported_at').map(key=>[key,clean(value[key])])):value;
 return JSON.stringify(clean(doc));
}
async function savePersonalExport(content,name){
 await portfolioStorageReady;
 if(portfolioStorageMode!=='server'||portfolioStorageLayout!==2)throw Error('OneDrive 저장 서버를 실행하세요. 새 폴더의 KRX_Portfolio_열기.cmd를 열면 연결됩니다.');
 const kind=name.startsWith('dividend_')?'dividends':'main';
 return portfolioRequest('POST',{name,kind,content},'/api/export-file');
}
function applyDiskPortfolio(){
 const next=validatePortfolio(portfolioDiskDocument),changed=JSON.stringify(next)!==JSON.stringify(portfolioDiskDocument);
 portfolio=next;portfolioSavePending=null;portfolioSaveBlocked=false;portfolioSavedKey=changed?null:portfolioKey(next);dirty=changed;activeAccountId=null;cancelHoldingEdit();resetDividendReceiptForm();switchView('portfolio');
 try{localStorage.setItem('krx-portfolio-v1',JSON.stringify(portfolio))}catch{}
 renderPortfolio();renderSaveState();portfolioStorageMessageSet('JSON 파일을 불러왔습니다 · '+portfolioStoragePath);
 if(changed)queuePortfolioSave('파일 형식 보강');
}
function blockPortfolioSave(message){portfolioSaveBlocked=true;portfolioStorageMessageSet(message+' 기존 파일은 유지됩니다. 아래에서 저장할 데이터를 선택하세요.')}
async function initializePortfolioStorage(){
 if(!portfolioIsLocal){portfolioStorageMode='download';portfolioStorageMessageSet('OneDrive 자동 저장을 위해 새 폴더의 KRX_Portfolio_열기.cmd를 실행하세요. 현재 입력은 브라우저에 보존됩니다.');return}
 try{
  const statusResponse=await fetch('/api/status',{signal:AbortSignal.timeout(5000)}),status=await statusResponse.json();
  if(!statusResponse.ok||!status.portfolio_storage||status.storage_layout!==2){portfolioStorageMode='download';portfolioStorageMessageSet('OneDrive 저장을 지원하는 새 서버가 필요합니다. KRX_Portfolio_열기.cmd를 실행하세요.');return}
  portfolioStorageMode='server';portfolioStorageLayout=status.storage_layout;
  const disk=await portfolioRequest('GET');portfolioStorageVersion=disk.version;portfolioStoragePath=disk.path;portfolioDiskDocument=disk.document;
  if(disk.document){
   const loaded=validatePortfolio(disk.document);
   if(!portfolioHasData(portfolio)&&!portfolioSavePending){applyDiskPortfolio();return}
   if(loaded.document_id!==portfolio.document_id){blockPortfolioSave('파일과 현재 브라우저의 포트폴리오가 다릅니다.');return}
   if(comparablePortfolio(loaded)===comparablePortfolio(portfolio)){portfolioSavedKey=portfolioKey(portfolio);dirty=false;renderSaveState()}
   else if(loaded.revision>portfolio.revision&&!portfolioSavePending){applyDiskPortfolio();return}
   else if(loaded.revision>=portfolio.revision){blockPortfolioSave('파일과 현재 입력의 내용이 다릅니다.');return}
   else portfolioSavePending=structuredClone(portfolio);
  }
  portfolioStorageMessageSet((portfolioSavedKey?'JSON 자동 저장 확인 · ':'자동 저장 준비 · ')+portfolioStoragePath);
 }catch(error){portfolioStorageMode='error';portfolioStorageMessageSet('자동 저장 연결 실패: '+error.message+' · 브라우저 입력은 유지됩니다. JSON 저장 재시도를 눌러주세요.')}
}
const portfolioStorageReady=initializePortfolioStorage();
async function flushPortfolioSave(){
 if(portfolioSaveBusy||portfolioSaveBlocked||portfolioStorageMode!=='server'||!portfolioSavePending)return;
 portfolioSaveBusy=true;
 try{
  while(portfolioSavePending&&!portfolioSaveBlocked){
   const snapshot=portfolioSavePending;portfolioSavePending=null;portfolioStorageMessageSet('JSON 파일에 저장 중…');
   try{
    const saved=await portfolioRequest('POST',{document:snapshot,expected_version:portfolioStorageVersion});
    portfolioStorageVersion=saved.version;portfolioDiskDocument=snapshot;portfolioSavedKey=portfolioKey(snapshot);
    if(portfolioKey(portfolio)===portfolioSavedKey&&!portfolioSavePending){dirty=false;renderSaveState()}
    portfolioStorageMessageSet('JSON 자동 저장 완료 · '+saved.saved_at+' · '+saved.path);
   }catch(error){
    if(!portfolioSavePending)portfolioSavePending=snapshot;
    if(error.status===409){
     const disk=await portfolioRequest('GET');portfolioStorageVersion=disk.version;portfolioDiskDocument=disk.document;
     blockPortfolioSave('다른 화면에서 JSON 파일이 변경됐습니다.');
    }else{portfolioStorageMessageSet('JSON 자동 저장 실패: '+error.message+' · 입력은 브라우저에 남아 있습니다. 저장 재시도 또는 전체 JSON 내보내기를 이용하세요.');break}
   }
  }
 }catch(error){portfolioStorageMessageSet('파일 상태 확인 실패: '+error.message+' · JSON 저장 재시도를 눌러주세요.')}
 finally{portfolioSaveBusy=false;renderPortfolioStorageState()}
}
function portfolioNeedsDownload(reason){return ['보유 종목 추가','종목 정보 수정'].includes(reason)||reason.startsWith('배당 수령 ')}
function queuePortfolioSave(reason){
 portfolioSavedKey=null;
 if(portfolioStorageMode==='download'){
  portfolioSavePending=structuredClone(portfolio);portfolioStorageMessageSet('OneDrive 저장 대기 · KRX_Portfolio_열기.cmd로 저장 서버를 실행하세요. 입력은 브라우저에 보존됩니다.');
  return;
 }
 portfolioSavePending=structuredClone(portfolio);portfolioStorageReady.then(()=>{
  if(portfolioStorageMode==='download'){
   portfolioStorageMessageSet('OneDrive 저장 대기 · KRX_Portfolio_열기.cmd를 실행하세요.');
  }else flushPortfolioSave();
 });
}
$('retryPortfolioSave').onclick=async()=>{
 if(portfolioStorageMode==='download'){await initializePortfolioStorage();if(portfolioStorageMode!=='server')return}
 if(portfolioSaveBusy)return;
 if(portfolioStorageMode!=='server'){await initializePortfolioStorage()}
 if(portfolioSaveBlocked)return;
 portfolioSavePending=structuredClone(portfolio);await flushPortfolioSave();
};
$('loadDiskPortfolio').onclick=()=>{if(confirm('현재 브라우저 입력을 파일의 데이터로 바꿀까요? 필요한 입력은 먼저 전체 JSON으로 내보내세요.'))applyDiskPortfolio()};
$('replaceDiskPortfolio').onclick=()=>{if(!confirm('현재 입력으로 JSON 파일을 저장할까요? 기존 파일은 portfolio.previous.json에 보관합니다.'))return;portfolioSaveBlocked=false;portfolioSavePending=structuredClone(portfolio);flushPortfolioSave()};
portfolioStorageReady.then(flushPortfolioSave);

const personalPaths=typeof PERSONAL_STORAGE_CONFIG!=='undefined'?PERSONAL_STORAGE_CONFIG:null;
if(personalPaths)$('personalStorageFolders').innerHTML=[['메인 데이터',personalPaths.main],['일별 평가 기록',personalPaths.daily],['배당 기록',personalPaths.dividends]].map(([label,path])=>'<div><b>'+esc(label)+'</b> · <code>'+esc(path)+'</code></div>').join('')+'<div class="muted">main/portfolio.json이 복원 기준 원본이며 일별·배당 파일은 같은 데이터에서 분리해 함께 저장합니다.</div>';
$('openPersonalServer').onclick=()=>{if(personalPaths?.server_url)location.href=personalPaths.server_url+'/portfolio_dashboard.html?view=portfolio'};
