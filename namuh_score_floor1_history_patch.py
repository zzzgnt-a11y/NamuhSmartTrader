from __future__ import annotations

_INSTALLED = False


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    # Keep the existing shared minute-history collector connected, then hand the
    # absolute-final C1/C2 score normalization to the integrity owner below.
    try:
        import namuh_minute_data_patch as minute_data
        minute_data.install(core)
    except Exception as exc:
        print("NAMUH FLOOR1 minute history install error:", str(exc)[:180], flush=True)

    import namuh_c1_score_integrity_patch
    ok = bool(namuh_c1_score_integrity_patch.apply(ns))
    _INSTALLED = ok
    if ok:
        print("NAMUH SCORE FLOOR1 delegated to C1 score integrity owner", flush=True)
    return ok
