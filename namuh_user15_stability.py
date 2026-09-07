from __future__ import annotations


def apply(ns):
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None or getattr(core, '_NAMUH_USER15_STABILITY', False):
        return
    core._NAMUH_USER15_STABILITY = True
    feed = core.feed

    # Keep the broadened currentInvestor scanner for sector flow coverage, but
    # do not fan the realtime program WebSocket out across that entire universe.
    # NH realtime can close the socket while a large subscribe batch is being
    # sent, which creates worker tracebacks and unnecessary CPU/log pressure.
    # A bounded fixed-list channel remains the realtime supplement; the wider
    # sector map still receives foreign/institution/person/program fields from
    # currentInvestor where the official payload provides them.
    def program_loop():
        delay = 1
        while not feed._stop.is_set():
            try:
                from nhplug.realtime import subscribe
                codes = list(feed.fixed.get('KR') or [])[:20]
                subscribe(codes, feed._apply_program_message, tr_cd='mn', timeout=30)
                delay = 1
                if not feed.program_realtime.get('connected'):
                    feed.program_realtime['error'] = '실시간 프로그램매매 수신 대기'
            except Exception as exc:
                feed.program_realtime['connected'] = False
                feed.program_realtime['error'] = str(exc)[:240]
                feed._stop.wait(delay)
                delay = min(30, delay * 2)

    feed.program_loop = program_loop
    print('NAMUH USER15 STABILITY active: bounded program websocket + broad investor scanner', flush=True)
