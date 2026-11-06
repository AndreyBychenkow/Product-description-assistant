'use strict';
const $ = id => document.getElementById(id);
let responseData = null, activeTab = 'card', busy = false, timer = null;
let selectedExample = 'testo-830-t1', canGenerate = false, appMode = 'demo';
let inputDirty = false, pageReady = false;

const ICONS = {
  check: [['path', {d:'M5 12l4 4L19 6'}]],
  shield: [['path', {d:'m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6zM8 12l3 3 5-6'}]],
  alert: [['circle', {cx:12,cy:12,r:9}], ['path',{d:'M12 7v6m0 4h.01'}]],
  search: [['circle',{cx:10.5,cy:10.5,r:6.5}], ['path',{d:'m16 16 5 5'}]],
  user: [['circle',{cx:12,cy:8,r:4}], ['path',{d:'M4 21v-2a8 8 0 0 1 16 0v2'}]],
  target: [['circle',{cx:12,cy:12,r:8}], ['circle',{cx:12,cy:12,r:3}], ['path',{d:'M12 1v3m0 16v3M1 12h3m16 0h3'}]],
  clock: [['circle',{cx:12,cy:12,r:9}], ['path',{d:'M12 7v5l3 2'}]],
  sparkle: [['path',{d:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z'}]]
};
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox','0 0 24 24'); svg.setAttribute('class','icon'); svg.setAttribute('aria-hidden','true');
  (ICONS[name] || ICONS.check).forEach(([tag, attrs]) => {
    const child = document.createElementNS(svg.namespaceURI, tag);
    Object.entries(attrs).forEach(([key,value]) => child.setAttribute(key,String(value)));
    svg.append(child);
  });
  return svg;
}
function node(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}
function label(text, counter, good=false) {
  const el = node('div','section-label'); el.append(node('span','',text));
  if (counter !== undefined) el.append(node('span','counter'+(good?' good':''),counter));
  return el;
}
function setStage(stage) {
  document.querySelectorAll('.flow-step').forEach(el => {
    const value = Number(el.dataset.stage);
    el.classList.toggle('active',value===stage); el.classList.toggle('done',value<stage);
    if (value===stage) el.setAttribute('aria-current','step'); else el.removeAttribute('aria-current');
  });
}
function toast(text) {
  $('toast').textContent=text; $('toast').hidden=false;
  setTimeout(() => $('toast').hidden=true,2400);
}
function clearError() { $('errorArea').replaceChildren(); $('errorArea').hidden=true; }
function showError(error) {
  const area=$('errorArea'); area.replaceChildren(); area.hidden=false;
  const box=node('div','error-box');
  box.append(node('strong','',error.code==='demo_mode'?'Деморежим без новой генерации':'Не удалось завершить запрос'));
  box.append(node('div','',error.message||'Проверьте данные и подключение к API.'));
  box.append(node('code','',error.code||'request_error'));
  if (error.details?.length) {
    const details=node('details'); details.append(node('summary','','Подробности проверки'));
    const list=node('ul'); error.details.forEach(x => list.append(node('li','',(x.field?x.field+': ':'')+x.message)));
    details.append(list); box.append(details);
  }
  area.append(box);
}
async function api(path, options={}) {
  let res;
  try { res=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}}); }
  catch { throw {code:'connection_error',message:'Нет связи с приложением. Проверьте, что окно сервера открыто, и обновите страницу.'}; }
  let data;
  try { data=await res.json(); } catch { throw {code:'server_response_error',message:'Не удалось прочитать ответ приложения. Проверьте соединение.'}; }
  if (!res.ok) throw data.error||{code:'request_error',message:'Ошибка запроса: '+res.status};
  return data;
}
function inputObject() {
  try { return JSON.parse($('editor').value); }
  catch { throw {code:'invalid_json',message:'Входной JSON содержит синтаксическую ошибку. Проверьте запятые, кавычки и скобки.'}; }
}
function updateInput() {
  const bytes=new TextEncoder().encode($('editor').value).length;
  $('inputSize').textContent=(bytes/1024).toFixed(1)+' КБ';
}
function setSources(values) {
  const box=$('sourceLinks'); box.replaceChildren();
  const valid=(values||[]).filter(value => {try{return ['http:','https:'].includes(new URL(value).protocol);}catch{return false;}});
  if (!valid.length) { box.textContent='не указан'; return; }
  valid.forEach((url,index) => {
    if (index) box.append(document.createTextNode(' · '));
    const link=node('a','',new URL(url).hostname+' ↗');
    link.href=url; link.target='_blank'; link.rel='noopener noreferrer'; box.append(link);
  });
}
function table(items, limit) {
  const el=node('table','spec-table'), body=node('tbody');
  (limit?items.slice(0,limit):items).forEach(item => {
    const row=node('tr'), value=node('td',item.is_missing?'missing':'');
    if (item.is_missing) value.append(node('span','missing-value',item.value)); else value.textContent=item.value;
    row.append(node('td','',item.name),value); body.append(row);
  });
  el.append(body); return el;
}
function warningList(values) {
  if (!values?.length) return null;
  const box=node('div','warnings'), heading=node('div','label');
  heading.append(icon('alert'),document.createTextNode('На что обратить внимание'));
  box.append(heading); const list=node('ul'); values.forEach(text => list.append(node('li','',text))); box.append(list);
  return box;
}
function resetOutput() {
  responseData=null; activeTab='card';
  $('codeView').hidden=true; $('cardView').hidden=false; $('resultOrigin').hidden=true;
  $('copy').disabled=true; $('download').disabled=true; $('downloadLabel').textContent='Скачать JSON';
  document.querySelectorAll('.tab').forEach(el => {
    el.classList.toggle('active',el.dataset.tab==='card'); el.disabled=el.dataset.tab!=='card';
    el.setAttribute('aria-selected',String(el.dataset.tab==='card'));
  });
  $('resultMeta').textContent='Проверка данных не расходует токены';
  setStage(1);
}
function renderPreflight(data) {
  const box=$('cardView'); box.replaceChildren(); setStage(1);
  const heading=node('div','output-heading'), badge=node('span','status-pill');
  badge.append(icon('shield'),document.createTextNode(data.sufficient_for_generation?'Исходные данные проверены':'Недостаточно данных'));
  heading.append(badge,node('span','right-label','БЕЗ ВЫЗОВА LLM')); box.append(heading);
  const top=node('div','preflight-head'), text=node('div');
  text.append(node('h3','',data.sufficient_for_generation?'Сначала факты. Затем текст.':'Нечего выдумывать — нужно уточнить.'));
  text.append(node('p','',data.sufficient_for_generation?'Данные готовы для модели. Нажмите «Сформировать карточку» — появятся SEO-текст, запросы и блок для менеджера.':'Добавьте подтвержденные характеристики или назначение. Сервис не будет придумывать сведения ради объема текста.'));
  const count=node('div','fact-count',String(data.fact_count)); count.append(node('small','','ФАКТОВ')); top.append(text,count); box.append(top);
  const section=node('div','section'); section.append(label('Характеристики из JSON',data.characteristics.length+' полей'),table(data.characteristics,8)); box.append(section);
  if (data.characteristics.length>8) box.append(node('div','shortfall','Еще '+(data.characteristics.length-8)+' полей будут включены в результат.'));
  const note=node('div','preflight-note'); note.append(node('strong','','Это еще не сгенерированная карточка. '),document.createTextNode('Для нового текста используйте фиолетовую кнопку. Чтобы посмотреть результат без запроса к модели, нажмите «Готовый пример».')); box.append(note);
  if (data.missing_fields.length) {
    const line=node('div','shortfall'); line.append(node('i'),document.createTextNode('Полей для уточнения: '+data.missing_fields.length+'. Они будут явно отмечены.')); box.append(line);
  }
  const warnings=warningList(data.warnings); if (warnings) box.append(warnings);
  $('inputStatus').textContent=data.sufficient_for_generation?'ФАКТЫ ПОДГОТОВЛЕНЫ':'ЕСТЬ ПРОПУСКИ';
}
async function inspect() {
  if (busy) return; clearError();
  try {
    const product=inputObject(); const data=await api('/api/inspect',{method:'POST',body:JSON.stringify(product)});
    resetOutput(); setSources(product.source_urls); renderPreflight(data);
  } catch (error) { showError(error); }
}
async function loadExample(slug) {
  if (busy) return; clearError();
  try {
    selectedExample=slug; inputDirty=false;
    const product=await api('/api/examples/'+slug);
    $('editor').value=JSON.stringify(product,null,2);
    document.querySelectorAll('.example').forEach(el => {
      const chosen=el.dataset.example===slug; el.classList.toggle('selected',chosen); el.setAttribute('aria-pressed',String(chosen));
    });
    updateInput(); setBusy(false); await inspect();
  } catch (error) { showError(error); }
}
function renderResult(result) {
  const box=$('cardView'); box.replaceChildren();
  const ready=result.metadata.mode==='llm'; setStage(ready?3:1);
  const heading=node('div','output-heading');
  const badge=node('span','status-pill'+(result.status==='draft'?'':' amber'));
  const text=result.status==='insufficient_data'?'Недостаточно данных':result.status==='needs_review'?'Черновик · есть уточнения':'Черновик готов';
  badge.append(icon(result.status==='draft'?'check':'alert'),document.createTextNode(text));
  heading.append(badge,node('span','right-label',result.validation.passed?'ФОРМАЛЬНЫЕ ПРОВЕРКИ ✓':'ГЕНЕРАЦИЯ НЕ ВЫПОЛНЕНА')); box.append(heading);
  box.append(label('SEO-заголовок',result.validation.title_length+' / 70',result.validation.title_length>0&&result.validation.title_length<=70),node('h3','seo-title',result.seo_title||'Не сформирован: недостаточно данных.'));
  box.append(label('SEO-описание',result.validation.description_length+' / 800–1200',result.validation.description_length>=800&&result.validation.description_length<=1200),node('p','seo-description',result.seo_description||'Добавьте подтвержденные характеристики или описание назначения. API не вызывался.'));
  const specs=node('div','section'); specs.append(label('Ключевые характеристики','Из исходника'),table(result.characteristics)); box.append(specs);
  const querySection=node('div','section'); querySection.append(label('Поисковые запросы',result.search_queries.length+' / 3–5',result.search_queries.length>=3&&result.search_queries.length<=5));
  const queries=node('div','queries'); result.search_queries.forEach(text => {const tag=node('span','query');tag.append(icon('search'),node('span','',text));queries.append(tag);}); querySection.append(queries); box.append(querySection);
  if (result.commercial_block) {
    const section=node('div','section'); section.append(label('Для менеджера'));
    const block=node('div','commercial');
    [['Кому подходит',result.commercial_block.audience,'user'],['Какие задачи решает',result.commercial_block.tasks,'target']].forEach(([key,value,name]) => {
      const col=node('div'), title=node('b'); title.append(icon(name),document.createTextNode(key)); col.append(title,node('p','',value)); block.append(col);
    });
    section.append(block); box.append(section);
  }
  const warnings=warningList(result.warnings); if (warnings) box.append(warnings);
  $('resultMeta').textContent=result.metadata.model+' · попыток: '+result.metadata.attempts+' · промпт '+result.metadata.prompt_version;
}
function setOrigin(kind, result) {
  const box=$('resultOrigin'); box.replaceChildren(); box.hidden=false;
  box.className='origin-banner'+(kind==='live'?' live':'');
  const text=node('div');
  text.append(node('strong','',kind==='live'?'Новый ответ модели':'Сохранённый реальный пример'));
  let date='';
  try { date=new Date(result.metadata.generated_at).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'}); } catch { date=result.metadata.generated_at; }
  text.append(node('div','',kind==='live'?'Создан через API · '+date:'Карточка из архива · '+date+' · новый вызов LLM не выполнялся.'));
  box.append(icon(kind==='live'?'sparkle':'clock'),text);
}
function switchTab(tab) {
  if (tab!=='card'&&!responseData) return;
  activeTab=tab;
  document.querySelectorAll('.tab').forEach(el => {el.classList.toggle('active',el.dataset.tab===tab);el.setAttribute('aria-selected',String(el.dataset.tab===tab));});
  $('cardView').hidden=tab!=='card'; $('codeView').hidden=tab==='card';
  $('resultOrigin').hidden=!responseData;
  if (tab==='markdown') $('codeView').textContent=responseData.markdown;
  if (tab==='json') $('codeView').textContent=JSON.stringify(responseData.result,null,2);
  $('downloadLabel').textContent=tab==='markdown'?'Скачать .md':'Скачать JSON';
}
function setBusy(value) {
  busy=value; $('generate').disabled=value||!canGenerate; $('generate').setAttribute('aria-busy',String(value));
  $('inspect').disabled=value; $('savedExample').disabled=value||inputDirty; $('missingDemo').disabled=value;
  $('editor').readOnly=value; document.querySelectorAll('.example').forEach(el => el.disabled=value);
  $('generateText').textContent=value?'Генерируем…':canGenerate?'Сформировать карточку':'Новая генерация: подключите API';
}
function revealResult() {
  if (pageReady && window.innerWidth<1000) $('outputPanel').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
}
async function generate() {
  if (busy||!canGenerate) return; clearError();
  let product; try {product=inputObject();} catch(error) {showError(error);return;}
  resetOutput(); setBusy(true); setStage(2);
  const box=$('cardView'); box.replaceChildren();
  const loading=node('div','loading'); loading.append(node('div','spinner'),node('strong','','Модель готовит черновик'));
  const elapsed=node('span','','Отправили данные в настроенный API. Ответ проверим перед показом.'); loading.append(elapsed,node('div','skeleton')); box.append(loading); revealResult();
  const start=Date.now(); timer=setInterval(() => elapsed.textContent='Прошло '+Math.round((Date.now()-start)/1000)+' с · не более двух попыток',1000);
  try {
    responseData=await api('/api/generate',{method:'POST',body:JSON.stringify(product)});
    renderResult(responseData.result);
    if (responseData.result.metadata.mode==='llm') setOrigin('live',responseData.result);
    $('copy').disabled=false; $('download').disabled=false; document.querySelectorAll('.tab').forEach(el => el.disabled=false);
  } catch(error) {
    box.replaceChildren(); $('resultOrigin').hidden=true; setStage(1);
    try {const data=await api('/api/inspect',{method:'POST',body:JSON.stringify(product)});renderPreflight(data);} catch {box.append(node('div','empty','Проверьте данные и повторите запрос.'));}
    showError(error);
  } finally {clearInterval(timer);setBusy(false);await refreshHealth();}
}
async function refreshHealth() {
  try {
    const data=await api('/health'); appMode=data.app_mode; canGenerate=Boolean(data.can_generate);
    $('requestBudget').textContent=appMode==='demo'?'ДЕМО · LLM: '+data.api_requests_used:'API: '+data.api_requests_used+' / '+data.api_request_budget;
    $('providerDot').classList.toggle('ready',canGenerate&&!data.last_error);
    $('providerLabel').textContent=appMode==='demo'?'Демо · без LLM':canGenerate?'LLM API · настроен':'API · нужны настройки';
    $('providerNotice').hidden=canGenerate; $('providerNotice').classList.toggle('demo',appMode==='demo');
    if (appMode==='demo') {
      $('noticeTitle').textContent='Посмотрите, какой получится карточка';
      $('noticeText').textContent='ДЕМО БЕЗ LLM. Открывайте готовые реальные примеры, проверяйте JSON и экспорт. Модель не скачивается. Для нового ответа выполните python -m scripts.configure и перезапустите сервер.';
    } else if (!canGenerate) {
      const missing=[];
      if (!data.model) missing.push('LLM_MODEL');
      if (data.api_key_required && !data.api_key_configured) missing.push('LLM_API_KEY');
      $('noticeTitle').textContent=missing.length===1&&missing[0]==='LLM_API_KEY'?'Приложение не видит API-ключ':'Настройте доступ к модели';
      $('noticeText').textContent=(missing.length?'Не заполнено: '+missing.join(', ')+'. ':'')+'Запустите python -m scripts.configure: ключ вводится скрыто и сохраняется в .env. Затем перезапустите сервер. Ключ не вводится в JSON товара. Пока доступен «Готовый пример» — без обращения к API.';
    }
    setBusy(busy);
  } catch {canGenerate=false;$('providerLabel').textContent='Нет связи с сервером';$('providerDot').classList.remove('ready');setBusy(busy);}
}
async function loadSaved() {
  if (busy) return; clearError();
  try {
    await loadExample(selectedExample);
    responseData=await api('/api/examples/'+selectedExample+'/result');
    if (responseData.origin!=='saved_example') throw {code:'unexpected_origin',message:'Не удалось подтвердить происхождение сохраненного примера.'};
    renderResult(responseData.result); setOrigin('saved',responseData.result); setStage(3);
    $('cardView').querySelector('.right-label').textContent='СОХРАНЕННЫЙ РЕАЛЬНЫЙ ОТВЕТ LLM';
    $('resultMeta').textContent='Сохранено: '+responseData.result.metadata.generated_at+' · '+responseData.result.metadata.model;
    $('copy').disabled=false; $('download').disabled=false; document.querySelectorAll('.tab').forEach(el => el.disabled=false); revealResult();
  } catch(error) {showError(error);}
}
$('generate').addEventListener('click',generate);
$('inspect').addEventListener('click',inspect);
$('savedExample').addEventListener('click',loadSaved);
document.querySelectorAll('.example').forEach(el => el.addEventListener('click',() => loadExample(el.dataset.example)));
document.querySelectorAll('.tab').forEach(el => {
  el.addEventListener('click',() => switchTab(el.dataset.tab));
  el.addEventListener('keydown',event => {
    if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
    event.preventDefault(); const tabs=[...document.querySelectorAll('.tab')].filter(x => !x.disabled);
    const index=tabs.indexOf(el), next=tabs[(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];
    if (next) {next.focus();switchTab(next.dataset.tab);}
  });
});
$('editor').addEventListener('input',() => {
  inputDirty=true;updateInput();resetOutput();clearError();setBusy(false);
  $('cardView').replaceChildren(node('div','empty','Данные изменены. Нажмите «Проверить данные» или сформируйте новую карточку.'));
  $('inputStatus').textContent='ДАННЫЕ ИЗМЕНЕНЫ';
});
$('missingDemo').addEventListener('click',async() => {
  if (busy) return;
  try {
    const current=inputObject(); inputDirty=true;
    $('editor').value=JSON.stringify({name:current.name||'Прибор',manufacturer:current.manufacturer||null,specs:{'Диапазон измерений':null,'Питание':null},description:null,expected_specs:['Диапазон измерений','Питание']},null,2);
    updateInput();setBusy(false);await inspect();
  } catch(error) {showError(error);}
});
$('copy').addEventListener('click',async() => {
  if (!responseData) return;
  const text=activeTab==='json'?JSON.stringify(responseData.result,null,2):responseData.markdown;
  try {await navigator.clipboard.writeText(text);toast('Скопировано');}
  catch {
    const temp=node('textarea');temp.value=text;document.body.append(temp);temp.select();const ok=document.execCommand('copy');temp.remove();
    toast(ok?'Скопировано':'Копирование недоступно. Используйте скачивание.');
  }
});
$('download').addEventListener('click',() => {
  if (!responseData) return;
  const markdown=activeTab==='markdown', text=markdown?responseData.markdown:JSON.stringify(responseData.result,null,2);
  const blob=new Blob([text],{type:(markdown?'text/markdown':'application/json')+';charset=utf-8'}), url=URL.createObjectURL(blob), anchor=node('a');
  const name=(responseData.result.product_name||'product-card').replace(/[<>:"/\\|?*\u0000-\u001F]/g,'-').slice(0,80).trim()||'product-card';
  anchor.href=url;anchor.download=name+(markdown?'.md':'.json');anchor.click();setTimeout(() => URL.revokeObjectURL(url),1000);
});
(async() => {
  if (window.innerWidth<650) $('jsonDetails').open=false;
  await refreshHealth();
  if (appMode==='demo') await loadSaved(); else await loadExample('testo-830-t1');
  pageReady=true;
})();
