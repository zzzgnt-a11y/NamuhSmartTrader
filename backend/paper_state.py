from __future__ import annotations
import os

def protected_codes():
    return {x.strip() for x in os.getenv("PROTECTED_CODES","").split(",") if x.strip()}
