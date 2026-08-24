(function(){
  'use strict';
  var tree=document.getElementById('wiki-tree'),article=document.getElementById('wiki-article'),loading=document.getElementById('wiki-loading'),search=document.getElementById('wiki-search'),count=document.getElementById('wiki-count'),sidebar=document.getElementById('wiki-sidebar'),menu=document.getElementById('wiki-menu'),overlay=document.getElementById('wiki-overlay');
  var knownPaths=new Set(),currentPath='',searchTimer=0;
  function esc(value){return String(value==null?'':value).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function hashPath(){try{return decodeURIComponent(location.hash.slice(1))}catch(e){return''}}
  function closeMenu(){sidebar.classList.remove('open');overlay.hidden=true;menu.setAttribute('aria-expanded','false')}
  function leaf(doc){return '<a class="wiki-link" data-path="'+esc(doc.path)+'" href="#'+encodeURIComponent(doc.path)+'">'+esc(doc.title)+(doc.status?'<small>'+esc(doc.status)+'</small>':'')+(doc.match?'<span class="wiki-match">'+esc(doc.match)+'</span>':'')+'</a>'}
  function branch(documents,depth){
    var leaves=[],groups={};
    documents.forEach(function(doc){var parts=doc.parts.slice(depth);if(parts.length<=1){leaves.push(doc);return}var key=parts[0];(groups[key]||(groups[key]=[])).push(doc)});
    var html=leaves.map(leaf).join('');
    Object.keys(groups).sort().forEach(function(name){html+='<details class="wiki-group" open><summary>'+esc(name)+'</summary><div class="wiki-branch">'+branch(groups[name],depth+1)+'</div></details>'});
    return html;
  }
  function renderCatalog(data){
    knownPaths=new Set(data.all_paths||[]);
    count.textContent=data.query?'Найдено: '+data.count:'Документов: '+data.count;
    tree.innerHTML=data.sections.map(function(section){return '<section class="wiki-section"><button type="button">'+esc(section.title)+'</button><div class="wiki-branch">'+branch(section.documents,0)+'</div></section>'}).join('')||'<p class="wiki-count">Ничего не найдено</p>';
    Array.prototype.forEach.call(tree.querySelectorAll('.wiki-section>button'),function(button){button.onclick=function(){button.parentElement.classList.toggle('closed')}});
    markActive();
  }
  function markActive(){Array.prototype.forEach.call(tree.querySelectorAll('[data-path]'),function(link){link.classList.toggle('active',link.getAttribute('data-path')===currentPath)})}
  function loadCatalog(query){fetch('/admin/api/knowledge-base?q='+encodeURIComponent(query||''),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error('Не удалось загрузить каталог');return response.json()}).then(function(data){renderCatalog(data);var requested=hashPath();if(!currentPath&&!query){var first=data.sections[0]&&data.sections[0].documents[0];loadDocument(knownPaths.has(requested)?requested:(first&&first.path))}}).catch(function(error){tree.innerHTML='<p class="wiki-error">'+esc(error.message)+'</p>'})}
  function resolveInternal(href){
    if(!href||href.charAt(0)==='#'||/^[a-z]+:/i.test(href)||href.indexOf('//')===0)return'';
    var base=currentPath.split('/');base.pop();
    href.split('/').forEach(function(part){if(!part||part==='.')return;if(part==='..')base.pop();else base.push(part)});
    return base.join('/').split('#')[0];
  }
  function bindArticleLinks(){
    Array.prototype.forEach.call(article.querySelectorAll('a[href]'),function(link){var href=link.getAttribute('href');var target=resolveInternal(href);if(target&&knownPaths.has(target)){link.href='#'+encodeURIComponent(target)}else if(/^https?:/i.test(href)){link.target='_blank';link.rel='noopener'}})
  }
  function loadDocument(path){
    if(!path)return;
    currentPath=path;loading.hidden=false;loading.textContent='Открываю документ…';article.hidden=true;markActive();
    fetch('/admin/api/knowledge-base/document?path='+encodeURIComponent(path),{credentials:'same-origin'}).then(function(response){if(!response.ok)throw new Error(response.status===404?'Документ не найден':'Не удалось открыть документ');return response.json()}).then(function(data){currentPath=data.path;article.innerHTML=data.html;article.hidden=false;loading.hidden=true;document.title=data.title+' · База знаний';bindArticleLinks();markActive();closeMenu();scrollTo(0,0)}).catch(function(error){loading.innerHTML='<div class="wiki-error">'+esc(error.message)+'</div>';loading.hidden=false})
  }
  tree.addEventListener('click',function(event){var link=event.target.closest('[data-path]');if(!link)return;event.preventDefault();var path=link.getAttribute('data-path');if(location.hash==='#'+encodeURIComponent(path))loadDocument(path);else location.hash=encodeURIComponent(path)});
  article.addEventListener('click',function(event){var link=event.target.closest('a');if(!link)return;var target=resolveInternal(link.getAttribute('href'));if(target&&knownPaths.has(target)){event.preventDefault();location.hash=encodeURIComponent(target)}});
  addEventListener('hashchange',function(){var path=hashPath();if(path&&path!==currentPath)loadDocument(path)});
  search.addEventListener('input',function(){clearTimeout(searchTimer);searchTimer=setTimeout(function(){loadCatalog(search.value.trim())},220)});
  menu.onclick=function(){var open=!sidebar.classList.contains('open');sidebar.classList.toggle('open',open);overlay.hidden=!open;menu.setAttribute('aria-expanded',String(open))};overlay.onclick=closeMenu;
  loadCatalog('');
}());
