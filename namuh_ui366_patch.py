from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

_INSTALLED = False


def _inject_asset(html: str, asset_version: str) -> str:
    html = re.sub(r'\s*<link\s+rel=["\']stylesheet["\']\s+href=["\']/static/v366_unified\.css(?:\?[^"\']*)?["\']\s*/?>\s*', '\n', html, flags=re.I)
    html = re.sub(r'\s*<script\s+src=["\']/static/v366_unified\.js(?:\?[^"\']*)?["\']\s*></script>\s*', '\n', html, flags=re.I)
    css = f'  <link rel="stylesheet" href="/static/v366_unified.css?v={asset_version}">'
    js = f'  <script src="/static/v366_unified.js?v={asset_version}"></script>'
    html = html.replace('</head>', f'{css}\n</head>')
    html = html.replace('</body>', f'{js}\n</body>')
    return html


def _patch_stock_ui(root: Path, asset_version: str) -> None:
    p = root / 'static' / 'stock.html'
    text = p.read_text(encoding='utf-8')
    text = text.replace('<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 점수 분해</h2>',
                        '<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 점수 구성표</h2>')
    text = text.replace('<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 분석 점수표</h2>',
                        '<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 점수 구성표</h2>')
    text = text.replace('<small>점수 근거 확인</small>', '<small>조건1 · 100점 구성</small>')
    text = re.sub(r'/static/stock\.js\?v=[^"\']+', f'/static/stock.js?v={asset_version}', text)
    text = _inject_asset(text, asset_version)
    p.write_text(text, encoding='utf-8')

    p = root / 'static' / 'stock.js'
    text = p.read_text(encoding='utf-8')
    new_render = r'''function v366Metric(label,value,max){
 const n=num(value),mx=Math.max(.01,num(max)),w=Math.max(0,Math.min(100,n/mx*100));
 return `<div class="v366-metric"><div class="v366-metric-line"><span>${esc(label)}</span><b>${n.toFixed(1)}/${mx}</b></div><div class="v366-meter"><i style="width:${w}%"></i></div></div>`
}
function renderScores(d){
 const labels={'1m':'1분','3m':'3분','5m':'5분','20m':'20분','1d':'일봉'};
 $('scoreGrid').innerHTML=Object.entries(d.scores||{}).map(([k,v])=>`<div class="score-tile ${k===TF?'active':''}"><span>${labels[k]||esc(k)}</span><strong>${v==null?'—':num(v).toFixed(0)}</strong></div>`).join('')||'<div class="empty">AI 점수 축적 중</div>';
 const a=d.analysis;
 $('analysisReasons').innerHTML=a?(a.reasons||[]).slice(0,8).map(x=>`<span>${esc(x)}</span>`).join(''):'<div class="empty">해당 봉 기준 분석 데이터 축적 중</div>';
 const sc=d.strategy_conditions||{},c1=sc.condition1||{},b=c1.breakdown||{},raw=c1.standard_raw||{},g=c1.gates||{};
 if(!Object.keys(c1).length){
   const br=a?.breakdown||a?.components||{},maxes={'MACD':10,'RSI':10,'볼린저':10,'거래량':15,'이평':10,'가격구조':10,'엘리어트':10,'수급':10,'섹터':7.5,'섹터내강도':3.75,'공시/이벤트':3.75};
   $('breakdown').innerHTML=Object.entries(br).length?`<div class="v366-scoremap"><div class="v366-score-head"><div><small>CONDITION 1 · STANDARD</small><h3>조건1 구성 데이터 연결 중</h3></div><div class="v366-score-total">${num(a?.score).toFixed(1)} <span>/ 100</span></div></div><div class="v366-metrics">${Object.entries(br).map(([k,v])=>v366Metric(k,v,maxes[k]||10)).join('')}</div></div>`:'<div class="empty">조건1 구성 데이터 축적 중</div>';
   return;
 }
 const pre=num(c1.prerequisite_score!=null?c1.prerequisite_score:(num(b.daily10)+num(b.minute10)+num(b.execution12)+num(b.orderbook8)));
 const standard=num(c1.standard_score!=null?c1.standard_score:b.standard45);
 const bonus=num(c1.bonus_score!=null?c1.bonus_score:(num(b.sector_relative7_5)+num(b.leading_sector_flow3_75)+num(b.news3_75)));
 const total=num(c1.score!=null?c1.score:pre+standard+bonus);
 const threshold=num(c1.entry_threshold||72);
 const ratio=c1.orderbook?.ratio;
 const gate=Boolean(c1.gate);
 $('breakdown').innerHTML=`<div class="v366-scoremap">
   <div class="v366-score-head"><div><small>CONDITION 1 · STANDARD</small><h3>조건1 AI 점수 구성</h3></div><div class="v366-score-total">${total.toFixed(1)} <span>/ 100</span></div></div>
   <div class="v366-venn">
     <div class="v366-orb"><small>01 · FIRST</small><b>선행조건</b><strong>${pre.toFixed(1)}/40</strong><em>진입 전 확인</em></div>
     <div class="v366-orb"><small>02 · STANDARD</small><b>스탠다드</b><strong>${standard.toFixed(1)}/45</strong><em>기술지표 환산</em></div>
     <div class="v366-orb"><small>03 · BONUS</small><b>추가가점</b><strong>${bonus.toFixed(1)}/15</strong><em>섹터·수급·뉴스</em></div>
   </div>
   <div class="v366-eq"><span>선행조건 40</span><b>+</b><span>스탠다드 45</span><b>+</b><span>추가가점 15</span><b>=</b><strong>조건1 총점 ${total.toFixed(1)} / 100</strong></div>
   <section class="v366-stage"><h4><span>① 선행조건</span><b>${pre.toFixed(1)} / 40</b></h4><div class="v366-metrics">
     ${v366Metric('일봉',b.daily10,10)}${v366Metric('분봉',b.minute10,10)}${v366Metric('체결강도',b.execution12,12)}${v366Metric('호가',b.orderbook8,8)}
   </div><div class="v366-gate ${g.daily&&g.minute1m&&g.execution&&g.orderbook?'pass':'wait'}">일봉 ${g.daily?'통과':'대기'} · 분봉 ${g.minute1m?'통과':'대기'} · 체결 ${g.execution?'통과':'대기'} · 호가 ${g.orderbook?'통과':'대기'}${ratio==null?'':` · 호가비 ${num(ratio).toFixed(2)}배`}</div></section>
   <section class="v366-stage"><h4><span>② 스탠다드 기술지표</span><b>${standard.toFixed(1)} / 45</b></h4><div class="v366-metrics">
     ${v366Metric('MACD',raw.MACD,10)}${v366Metric('RSI',raw.RSI,10)}${v366Metric('볼린저',raw['볼린저'],10)}${v366Metric('거래량',raw['거래량'],15)}${v366Metric('이동평균',raw['이평'],10)}${v366Metric('가격구조',raw['가격구조'],10)}${v366Metric('엘리어트',raw['엘리어트'],10)}${v366Metric('75점→45점 환산',standard,45)}
   </div></section>
   <section class="v366-stage"><h4><span>③ 추가가점</span><b>${bonus.toFixed(1)} / 15</b></h4><div class="v366-metrics">
     ${v366Metric('섹터 상대강도',b.sector_relative7_5,7.5)}${v366Metric('주도섹터 수급',b.leading_sector_flow3_75,3.75)}${v366Metric('뉴스 / 공시',b.news3_75,3.75)}
   </div></section>
   <div class="v366-gate ${gate?'pass':'wait'}">조건1 ${gate?'진입조건 충족':'대기'} · 총점 기준 ${threshold.toFixed(0)}점 이상 + 선행조건 통과 · 엔벨로프 제외</div>
 </div>`;
}'''
    pattern = r'function renderScores\(d\)\{.*?function renderLiveFlow\(d\)\{'
    updated, count = re.subn(pattern, new_render + '\nfunction renderLiveFlow(d){', text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError('stock.js renderScores replacement failed')
    p.write_text(updated, encoding='utf-8')


def _patch_main_coin(root: Path, asset_version: str) -> None:
    for rel in ('static/index.html', 'static/coin.html'):
        p = root / rel
        if not p.exists():
            continue
        text = _inject_asset(p.read_text(encoding='utf-8'), asset_version)
        p.write_text(text, encoding='utf-8')


def _attach_strategy_detail(core) -> None:
    if getattr(core, '_NAMUH_UI366_DETAIL', False):
        return
    old = getattr(core, 'stock_detail', None)
    if not callable(old):
        return
    core._NAMUH_UI366_DETAIL = True

    def stock_detail(market: str, code: str, timeframe='1d'):
        d = old(market, code, timeframe)
        try:
            m = str(market or '').upper()
            c = str(code or '').upper()
            q = core.feed.quotes_for(m).get(c)
            if q is None:
                q = core.feed.q(m, c)
            sectors = []
            stockmap = {}
            try:
                with core.cache_lock:
                    sectors = list((core.CACHE.get(m) or {}).get('sectors') or [])
                    stockmap = dict((core.CACHE.get(m) or {}).get('stock_strength') or {})
            except Exception:
                pass
            secmap = {str(x.get('sector') or ''): float(x.get('score') or 0) for x in sectors if isinstance(x, dict)}
            leadermap = {str(x.get('sector') or ''): str(x.get('leader') or '') for x in sectors if isinstance(x, dict)}
            ranked = sorted([x for x in sectors if isinstance(x, dict)], key=lambda x: float(x.get('score') or 0), reverse=True)
            rankmap = {str(x.get('sector') or ''): i + 1 for i, x in enumerate(ranked) if str(x.get('sector') or '')}
            cand = core.candidate(q, m, False, secmap, stockmap, leadermap, rankmap, datetime.now(core.KST))
            if isinstance(cand, dict):
                d = dict(d)
                d['strategy_conditions'] = {
                    'condition1': dict(cand.get('condition1') or {}),
                    'condition2': dict(cand.get('condition2') or {}),
                    'condition3': dict(cand.get('condition3') or {}),
                }
                d['condition1_score'] = float((cand.get('condition1') or {}).get('score') or cand.get('score') or 0)
        except Exception as exc:
            try:
                d = dict(d)
                d['strategy_conditions_error'] = str(exc)[:160]
            except Exception:
                pass
        return d

    core.stock_detail = stock_detail


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    root = Path(__file__).resolve().parent
    asset_version = (os.getenv('RENDER_GIT_COMMIT') or os.getenv('GY_BUILD_ID') or '366')[:12]
    try:
        _patch_main_coin(root, asset_version)
        _patch_stock_ui(root, asset_version)
    except Exception as exc:
        print('NAMUH UI366 STATIC ERROR:', str(exc)[:220], flush=True)
    try:
        core = ns.get('core') if isinstance(ns, dict) else None
        if core is not None:
            _attach_strategy_detail(core)
    except Exception as exc:
        print('NAMUH UI366 DETAIL ERROR:', str(exc)[:220], flush=True)
    _INSTALLED = True
    print('NAMUH UI366 active: calendar/filter/search unified + C1 40/45/15 score map', flush=True)
    return True
