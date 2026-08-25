(function(){
  'use strict';
  var tree=document.getElementById('wiki-tree'),article=document.getElementById('wiki-article'),loading=document.getElementById('wiki-loading'),search=document.getElementById('wiki-search'),count=document.getElementById('wiki-count'),sidebar=document.getElementById('wiki-sidebar'),menu=document.getElementById('wiki-menu'),overlay=document.getElementById('wiki-overlay'),filters=document.getElementById('wiki-filters'),documentStatus=document.getElementById('document-status'),implementationStatus=document.getElementById('implementation-status'),notice=document.getElementById('wiki-notice');
  var knownPaths=new Set(),currentPath='',currentModule='',currentView='map',searchTimer=0,catalogData=null,projectMap=null;
  function esc(value){return String(value==null?'':value).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function hashValue(){try{return decodeURIComponent(location.hash.slice(1))}catch(e){return''}}
  function requestedView(){var view=new URLSearchParams(location.search).get('view');return['map','documents','guide','plans','technical'].indexOf(view)>=0?view:'map'}
  function closeMenu(){sidebar.classList.remove('open');overlay.hidden=true;menu.setAttribute('aria-expanded','false')}
  function showNotice(message){notice.innerHTML=esc(message)+' <button type="button">Открыть документы</button>';notice.hidden=false;notice.querySelector('button').onclick=function(){setView('documents')}}
  function clearNotice(){notice.hidden=true;notice.textContent=''}
  function setUrl(view,hash,replace){var url=new URL(location.href);url.searchParams.set('view',view);url.hash=hash?encodeURIComponent(hash):'';history[replace?'replaceState':'pushState']({},'',url)}
  function syncViewControls(){Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(button){button.classList.toggle('active',button.getAttribute('data-view')===currentView)});filters.hidden=currentView!=='map';search.placeholder=currentView==='map'?'Название, функция или файл':'Название или текст'}
  function setView(view,replace){currentView=view;currentPath='';currentModule='';syncViewControls();search.value='';clearNotice();setUrl(view,'',replace);renderView()}
  function leaf(doc){return '<a class="wiki-link" data-path="'+esc(doc.path)+'" href="?view='+currentView+'#'+encodeURIComponent(doc.path)+'">'+esc(doc.title)+(doc.status?'<small>'+esc(doc.status)+'</small>':'')+(doc.match?'<span class="wiki-match">'+esc(doc.match)+'</span>':'')+'</a>'}
  function branch(documents,depth){
    var leaves=[],groups={};
    documents.forEach(function(doc){var parts=doc.parts.slice(depth);if(parts.length<=1){leaves.push(doc);return}var key=parts[0];(groups[key]||(groups[key]=[])).push(doc)});
    var html=leaves.map(leaf).join('');
    Object.keys(groups).sort().forEach(function(name){html+='<details class="wiki-group" open><summary>'+esc(name)+'</summary><div class="wiki-branch">'+branch(groups[name],depth+1)+'</div></details>'});
    return html;
  }
  function filteredSections(data){
    if(currentView==='plans')return data.sections.filter(function(section){return section.code==='plans'});
    if(currentView==='technical')return data.sections.filter(function(section){return section.code==='start'||section.code==='working'});
    return data.sections;
  }
  function renderCatalog(data){
    knownPaths=new Set(data.all_paths||[]);var sections=filteredSections(data);
    var total=sections.reduce(function(sum,section){return sum+section.documents.length},0);
    count.textContent=data.query?'Найдено: '+total:'Документов: '+total;
    tree.innerHTML=sections.map(function(section){return '<section class="wiki-section"><button type="button">'+esc(section.title)+'</button><div class="wiki-branch">'+branch(section.documents,0)+'</div></section>'}).join('')||'<p class="wiki-count">Ничего не найдено</p>';
    Array.prototype.forEach.call(tree.querySelectorAll('.wiki-section>button'),function(button){button.onclick=function(){button.parentElement.classList.toggle('closed')}});markActive();
  }
  function renderPlansIndex(data,map){
    knownPaths=new Set(data.all_paths||[]);var visiblePaths=new Set();
    data.sections.filter(function(section){return section.code==='plans'}).forEach(function(section){section.documents.forEach(function(doc){visiblePaths.add(doc.path)})});
    var modules={};(map.modules||[]).forEach(function(module){modules[module.id]=module});var groups={};
    var allPlans=(map.plans||[]).concat(map.cross_project_plans||[]);
    allPlans.filter(function(plan){return visiblePaths.has(plan.path)}).forEach(function(plan){var key=plan.module_id||'cross-project';(groups[key]||(groups[key]=[])).push(plan)});
    var total=Object.keys(groups).reduce(function(sum,key){return sum+groups[key].length},0);count.textContent=(data.query?'Найдено планов: ':'Планов: ')+total;
    tree.innerHTML=Object.keys(groups).sort(function(a,b){return(moduleLabel(modules[a]||{id:a})).localeCompare(moduleLabel(modules[b]||{id:b}),'ru')}).map(function(moduleId){var module=modules[moduleId],title=module?moduleLabel(module):'Общие планы';return '<section class="wiki-section"><button type="button">'+esc(title)+'</button><div class="wiki-branch">'+groups[moduleId].map(function(plan){return '<a class="wiki-link" data-path="'+esc(plan.path)+'" href="?view=plans#'+encodeURIComponent(plan.path)+'">'+esc(plan.title||plan.path)+(plan.date?'<small>'+esc(plan.date)+'</small>':'')+'</a>'}).join('')+'</div></section>'}).join('')||'<p class="wiki-count">Планов не найдено</p>';
    Array.prototype.forEach.call(tree.querySelectorAll('.wiki-section>button'),function(button){button.onclick=function(){button.parentElement.classList.toggle('closed')}});markActive();
    var requested=hashValue(),first=allPlans.find(function(plan){return visiblePaths.has(plan.path)});if(requested&&visiblePaths.has(requested))loadDocument(requested);else if(first)loadDocument(first.path);else{loading.textContent='Явных планов нет.';loading.hidden=false;article.hidden=true}
  }
  function markActive(){Array.prototype.forEach.call(tree.querySelectorAll('[data-path]'),function(link){link.classList.toggle('active',link.getAttribute('data-path')===currentPath)});Array.prototype.forEach.call(tree.querySelectorAll('[data-module]'),function(link){link.classList.toggle('active',link.getAttribute('data-module')===currentModule)})}
  function loadCatalog(query,skipInitial){
    return fetch('/admin/api/knowledge-base?q='+encodeURIComponent(query||''),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error('Не удалось загрузить каталог');return response.json()}).then(function(data){catalogData=data;renderCatalog(data);if(!query&&!skipInitial)openInitialDocument()}).catch(function(error){tree.innerHTML='<p class="wiki-error">'+esc(error.message)+'</p>'});
  }
  function loadPlans(query){
    loading.hidden=false;loading.textContent='Загружаю планы…';article.hidden=true;
    return Promise.all([
      fetch('/admin/api/knowledge-base?q='+encodeURIComponent(query||''),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error('Не удалось загрузить документы');return response.json()}),
      fetch('/admin/api/project-map',{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error('Карта временно недоступна');return response.json()})
    ]).then(function(results){catalogData=results[0];projectMap=results[1];renderPlansIndex(catalogData,projectMap)}).catch(function(error){showNotice(error.message+'. Активные планы без карты не показываются.');currentView='documents';syncViewControls();setUrl('documents','',true);loadCatalog(query||'')});
  }
  function openInitialDocument(){
    var requested=hashValue();if(requested&&knownPaths.has(requested)){loadDocument(requested);return}
    var preferred='';
    if(currentView==='guide')preferred=Array.from(knownPaths).find(function(path){return path.endsWith('/OWNER_PROJECT_GUIDE.md')})||'docs/README.md';
    if(currentView==='technical')preferred='docs/OPERATIONS.md';
    var sections=catalogData?filteredSections(catalogData):[],first=sections[0]&&sections[0].documents[0];
    loadDocument(knownPaths.has(preferred)?preferred:(first&&first.path));
  }
  function resolveInternal(href){
    if(!href||href.charAt(0)==='#'||/^[a-z]+:/i.test(href)||href.indexOf('//')===0)return'';
    var base=currentPath.split('/');base.pop();href.split('/').forEach(function(part){if(!part||part==='.')return;if(part==='..')base.pop();else base.push(part)});return base.join('/').split('#')[0];
  }
  function bindArticleLinks(){Array.prototype.forEach.call(article.querySelectorAll('a[href]'),function(link){var href=link.getAttribute('href'),target=resolveInternal(href);if(target&&knownPaths.has(target)){link.href='?view=documents#'+encodeURIComponent(target)}else if(/^https?:/i.test(href)){link.target='_blank';link.rel='noopener'}})}
  function loadDocument(path){
    if(!path)return;currentPath=path;loading.hidden=false;loading.textContent='Открываю документ…';article.hidden=true;markActive();
    fetch('/admin/api/knowledge-base/document?path='+encodeURIComponent(path),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error(response.status===404?'Документ не найден':'Не удалось открыть документ');return response.json()}).then(function(data){currentPath=data.path;article.className='wiki-article';article.innerHTML=data.html;article.hidden=false;loading.hidden=true;document.title=data.title+' · Проект';bindArticleLinks();markActive();closeMenu();setUrl(currentView,currentPath,true);scrollTo(0,0)}).catch(function(error){loading.innerHTML='<div class="wiki-error">'+esc(error.message)+'</div>';loading.hidden=false});
  }
  function moduleLabel(module){return module.title||module.name||module.id}
  function moduleMatches(module,query){var values=[module.id,moduleLabel(module),module.summary,module.boundary,(module.capabilities||[]).join(' '),(module.truths||[]).join(' ')];['files','routes','tables','symbols'].forEach(function(key){(module[key]||[]).forEach(function(item){values.push(typeof item==='string'?item:JSON.stringify(item))})});return values.join(' ').toLocaleLowerCase('ru').indexOf(query)>=0}
  function filteredModules(){
    var query=search.value.trim().toLocaleLowerCase('ru'),doc=documentStatus.value,implementation=implementationStatus.value,modules=projectMap.modules||[];
    var direct=new Set(modules.filter(function(module){return(!query||moduleMatches(module,query))&&(!doc||module.document_status===doc)&&(!implementation||module.implementation_status===implementation)}).map(function(module){return module.id}));
    if(query||doc||implementation){var byId={};modules.forEach(function(module){byId[module.id]=module});direct.forEach(function(id){var parent=byId[id]&&byId[id].parent;while(parent&&byId[parent]){direct.add(parent);parent=byId[parent].parent}})}
    return modules.filter(function(module){return direct.has(module.id)});
  }
  function moduleTree(modules,parent,seen){
    var children=modules.filter(function(module){return(module.parent||null)===parent}).sort(function(a,b){return moduleLabel(a).localeCompare(moduleLabel(b),'ru')});
    return children.map(function(module){if(seen.has(module.id))return'';var next=new Set(seen);next.add(module.id);var nested=moduleTree(modules,module.id,next);return '<div><button class="module-link'+(module.id===currentModule?' active':'')+'" type="button" data-module="'+esc(module.id)+'">'+esc(moduleLabel(module))+'<small>'+esc(module.implementation_status||'')+'</small></button>'+(nested?'<div class="module-children">'+nested+'</div>':'')+'</div>'}).join('');
  }
  function renderModuleTree(){
    var modules=filteredModules(),ids=new Set(modules.map(function(module){return module.id}));var html=moduleTree(modules,null,new Set());
    modules.filter(function(module){return module.parent&&!ids.has(module.parent)}).forEach(function(module){html+=moduleTree(modules,module.parent,new Set())});
    count.textContent='Модулей: '+modules.length;tree.innerHTML=html||'<p class="wiki-count">Модули не найдены</p>';markActive();
  }
  function list(items,formatter){if(!items||!items.length)return'';return '<ul>'+items.map(function(item){return '<li>'+formatter(item)+'</li>'}).join('')+'</ul>'}
  function textItem(item){if(typeof item==='string')return esc(item);return esc(item.path||item.name||item.qualname||item.id||JSON.stringify(item))}
  function linkItem(url){return '<a href="'+esc(url)+'" target="_blank" rel="noopener">'+esc(url)+'</a>'}
  function relationBoxes(module){var labels={reads_from:'Читает из',writes_to:'Пишет в',depends_on:'Зависит от',events_in:'Получает события',events_out:'Отправляет события'},relations=module.relations||{};return Object.keys(labels).filter(function(key){return relations[key]&&relations[key].length}).map(function(key){return '<div class="relation-box"><b>'+labels[key]+'</b>'+list(relations[key],textItem)+'</div>'}).join('')}
  function technicalGroup(title,items,formatter){if(!items||!items.length)return'';return '<div class="technical-group"><h3>'+esc(title)+' · '+items.length+'</h3><ul class="technical-list">'+items.map(function(item){return '<li>'+formatter(item)+'</li>'}).join('')+'</ul></div>'}
  function renderModuleCard(id){
    var module=(projectMap.modules||[]).find(function(item){return item.id===id});if(!module)return;
    currentModule=id;var relations=relationBoxes(module),urls=(module.admin_urls||[]).concat(module.public_urls||[]),sources=module.sources||[];
    var html='<div class="module-card"><header><div class="module-eyebrow">'+esc(module.id)+'</div><h1>'+esc(moduleLabel(module))+'</h1><p class="module-summary">'+esc(module.summary||'Описание пока не заполнено.')+'</p><div class="status-row"><span class="status-pill">Документ: '+esc(module.document_status||'—')+'</span><span class="status-pill">Реализация: '+esc(module.implementation_status||'—')+'</span></div>'+(module.card?'<a href="?view=documents#'+encodeURIComponent(module.card)+'" data-card-path="'+esc(module.card)+'">Открыть каноническую карточку</a>':'')+'</header>';
    if(module.capabilities&&module.capabilities.length)html+='<section><h2>Что умеет</h2>'+list(module.capabilities,textItem)+'</section>';
    if(module.boundary)html+='<section><h2>Граница</h2><p>'+esc(module.boundary)+'</p></section>';
    if(module.truths&&module.truths.length)html+='<section><h2>Источники истины</h2>'+list(module.truths,textItem)+'</section>';
    if(urls.length)html+='<section><h2>Где открыть</h2>'+list(urls,linkItem)+'</section>';
    if(sources.length)html+='<section><h2>Машинные источники</h2>'+list(sources,function(source){return '<code>'+esc(source.path)+'</code> — '+esc(source.role)+(source.shared?' · общий':'')})+'</section>';
    if(relations)html+='<section><h2>Связи</h2><div class="module-relations">'+relations+'</div></section>';
    if(module.plans&&module.plans.length)html+='<section><h2>Планы</h2>'+list(module.plans,function(plan){return '<a href="?view=plans#'+encodeURIComponent(plan.path)+'">'+esc(plan.title||plan.path)+'</a>'})+'</section>';
    html+='<details class="module-technical"><summary>Технические детали</summary><div class="technical-body">'+technicalGroup('Файлы',module.files||[],textItem)+technicalGroup('API-маршруты',module.routes||[],function(route){return esc((route.method||'')+' '+(route.path||route.name||''))})+technicalGroup('Таблицы',module.tables||[],textItem)+technicalGroup('Программные символы',module.symbols||[],function(symbol){return esc(symbol.qualname||symbol.name||symbol)})+'</div></details></div>';
    article.className='wiki-article module-card';article.innerHTML=html;article.hidden=false;loading.hidden=true;document.title=moduleLabel(module)+' · Карта проекта';markActive();closeMenu();setUrl('map',module.id,true);scrollTo(0,0);
  }
  function loadProjectMap(){
    loading.hidden=false;loading.textContent='Загружаю карту системы…';article.hidden=true;
    return fetch('/admin/api/project-map',{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error('Карта временно недоступна');return response.json()}).then(function(data){projectMap=data;renderModuleTree();var requested=hashValue(),first=(data.modules||[])[0];if(!first){loading.textContent='В карте пока нет модулей.';return}renderModuleCard((data.modules||[]).some(function(module){return module.id===requested})?requested:first.id)}).catch(function(error){showNotice(error.message+'. Документы продолжают работать.');currentView='documents';syncViewControls();setUrl('documents','',true);loadCatalog('')});
  }
  function renderView(){
    article.hidden=true;loading.hidden=false;tree.innerHTML='';count.textContent='Загружаю…';
    if(currentView==='map'){loadProjectMap();return}
    if(currentView==='plans'){filters.hidden=true;loadPlans('');return}
    if(currentView==='guide'){filters.hidden=true;loadCatalog('');return}
    filters.hidden=true;loadCatalog('');
  }
  tree.addEventListener('click',function(event){var moduleLink=event.target.closest('[data-module]');if(moduleLink){renderModuleCard(moduleLink.getAttribute('data-module'));return}var link=event.target.closest('[data-path]');if(!link)return;event.preventDefault();loadDocument(link.getAttribute('data-path'))});
  article.addEventListener('click',function(event){var card=event.target.closest('[data-card-path]');if(card){event.preventDefault();currentView='documents';Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(button){button.classList.toggle('active',button.getAttribute('data-view')==='documents')});filters.hidden=true;loadCatalog('',true).then(function(){loadDocument(card.getAttribute('data-card-path'))});return}var link=event.target.closest('a');if(!link)return;var target=resolveInternal(link.getAttribute('href'));if(target&&knownPaths.has(target)){event.preventDefault();loadDocument(target)}});
  Array.prototype.forEach.call(document.querySelectorAll('[data-view]'),function(button){button.onclick=function(){setView(button.getAttribute('data-view'))}});
  addEventListener('popstate',function(){currentView=requestedView();syncViewControls();renderView()});
  search.addEventListener('input',function(){clearTimeout(searchTimer);searchTimer=setTimeout(function(){if(currentView==='map'){renderModuleTree()}else if(currentView==='plans'){loadPlans(search.value.trim())}else{loadCatalog(search.value.trim())}},220)});
  documentStatus.onchange=renderModuleTree;implementationStatus.onchange=renderModuleTree;
  menu.onclick=function(){var open=!sidebar.classList.contains('open');sidebar.classList.toggle('open',open);overlay.hidden=!open;menu.setAttribute('aria-expanded',String(open))};overlay.onclick=closeMenu;
  currentView=requestedView();syncViewControls();renderView();
}());
