// client-side include for site/nav.html — injects nav and fixes link targets relative to page location
(function(){
  const paths = ['./nav.html','../nav.html','../../nav.html'];
  function tryLoad(i){
    if(i>=paths.length) return;
    fetch(paths[i]).then(r=>{
      if(!r.ok) throw new Error('notfound');
      return r.text();
    }).then(html=>{
      const d = document.createElement('div');
      d.innerHTML = html;
      document.body.insertBefore(d, document.body.firstChild);

      // determine prefix to root (., .., or ../..) based on current pathname depth
      const p = location.pathname || '';
      let prefix = '.';
      if (/\/msg\//.test(p) || /\/browse\//.test(p) || /\/site\/msg\//.test(p) || /\/site\/browse\//.test(p)) {
        prefix = '..';
      }

      // set hrefs for elements that declare data-root-link
      document.querySelectorAll('[data-root-link]').forEach(function(el){
        const tgt = el.getAttribute('data-root-link');
        el.setAttribute('href', prefix + '/' + tgt);
      });

      // set form action to index at repo root
      const form = document.getElementById('nav-form');
      if(form) form.setAttribute('action', prefix + '/index.html');

      // copy q param into nav input if present
      const q = new URLSearchParams(location.search).get('q');
      if(q){
        const el = document.getElementById('nav-q') || document.getElementById('q');
        if(el) el.value = q;
      }

      // Make the nav search actually perform:
      if(form){
        form.addEventListener('submit', function(ev){
          ev.preventDefault();
          const qv = (document.getElementById('nav-q') || {}).value || '';
          // If we're already on the index/search page, dispatch a nav-search event and call common handlers
          const isIndex = /\/(?:index\.html)?$/.test(location.pathname) || location.pathname === '/';
          if(isIndex){
            // dispatch event for existing search code to listen to
            window.dispatchEvent(new CustomEvent('nav-search', { detail: { q: qv } }));
            // best-effort call to commonly used global functions
            try { if (typeof window.doSearch === 'function') window.doSearch(qv); } catch(e){}
            try { if (typeof window.performSearch === 'function') window.performSearch(qv); } catch(e){}
            try { if (typeof window.search === 'function') window.search(qv); } catch(e){}
            // fallback: update querystring so page scripts that read location.search react
            if(qv && history && history.replaceState){
              const url = new URL(location.href);
              url.searchParams.set('q', qv);
              history.replaceState(null, '', url.toString());
            }
          } else {
            // navigate to index with q parameter
            const tgt = prefix + '/index.html?q=' + encodeURIComponent(qv);
            location.href = tgt;
          }
        }, { passive: false });
      }

    }).catch(()=>tryLoad(i+1));
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', ()=> tryLoad(0));
  } else {
    tryLoad(0);
  }
})();