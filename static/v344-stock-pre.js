(function(){
  'use strict';
  const nativeFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    try{
      const raw=typeof input==='string'?input:(input&&input.url)||'';
      const u=new URL(raw,location.origin);
      const m=u.pathname.match(/^\/api\/stock\/(KR|US)\/([^/]+)$/i);
      if(m){
        const tf=u.searchParams.get('timeframe')||'1d';
        const repl=new URL(`/api/v344/stock/${m[1].toUpperCase()}/${encodeURIComponent(decodeURIComponent(m[2]))}`,location.origin);
        repl.searchParams.set('timeframe',tf);
        if(String(tf).toLowerCase()==='1d')repl.searchParams.set('days','30');
        return nativeFetch(repl.pathname+repl.search,init);
      }
    }catch(_){}
    return nativeFetch(input,init);
  };
})();
