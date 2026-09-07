from __future__ import annotations


def apply(ns=None):
    """Extend only Condition 2 afternoon entry window to 15:00 KST."""
    import namuh_strategy123_patch
    import namuh_strategy23_fix

    window = (13 * 60, 15 * 60)
    namuh_strategy123_patch.ENTRY2_PM = window
    namuh_strategy23_fix.ENTRY2_PM = window
    print("NAMUH C2 WINDOW active: afternoon entry 13:00-15:00 KST", flush=True)
