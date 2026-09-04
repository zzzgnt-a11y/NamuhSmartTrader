from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from typing import Deque, List, Optional
import time

@dataclass
class Tick:
    code: str
    price: float
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    ts: float = field(default_factory=time.time)

@dataclass
class QuoteState:
    code: str
    name: str = ""
    open: float = 0.0
    price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    prev_volume: float = 0.0
    per: float = 0.0
    pbr: float = 0.0
    foreign_net: float = 0.0
    institution_net: float = 0.0
    sector: str = ""
    prices: Deque[float] = field(default_factory=lambda: deque(maxlen=240))
    volumes: Deque[float] = field(default_factory=lambda: deque(maxlen=240))
    updated_at: float = 0.0

    def mark(self, price: float, volume: float = 0.0) -> None:
        if price <= 0:
            return
        self.price = price
        if self.open <= 0:
            self.open = price
        self.high = max(self.high or price, price)
        self.low = min(self.low or price, price)
        self.volume = max(self.volume, volume)
        self.prices.append(price)
        self.volumes.append(volume)
        self.updated_at = time.time()
