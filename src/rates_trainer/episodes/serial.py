"""Plain-data conversion and the decision codec (no I/O, no engine logic).

`plain(x)` turns engine records (dataclasses, enums, tuples, mappings) into JSON-ready data, so nothing a frontend receives is an engine object.

The decision codec is the exact, text-independent way to store a decision. Replaying `episode id + seed + market seed + [encoded decisions]`
reproduces an episode bit for bit in any process (see api.py for the record format).
"""

from __future__ import annotations

import numbers
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Mapping

from ..engine.instruments import Side
from .state import BondTrade, CheckpointAnswer, FuturesTrade, HedgeDecision, HedgeTrade, QuoteDecision, RFQDecision


def plain(x):
    """JSON-ready copy of x: dataclasses become dicts (fields only), enums their values, tuples/sets lists, mapping keys strings."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, numbers.Integral):
        return int(x)
    if isinstance(x, numbers.Real):
        return float(x)
    if is_dataclass(x) and not isinstance(x, type):
        return {f.name: plain(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, Mapping):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set, frozenset)):
        return [plain(v) for v in x]
    raise TypeError(f"cannot make {type(x).__name__} plain")


# ------------------------------------------------------------------------------------------------- decision codec

def encode_decision(d) -> dict:
    if isinstance(d, QuoteDecision):
        return {"type": "quote", "bid": d.bid, "offer": d.offer}
    if isinstance(d, RFQDecision):
        return {"type": "rfq", "level": d.level}
    if isinstance(d, CheckpointAnswer):
        return {"type": "checkpoint", "raw": d.raw}
    if isinstance(d, HedgeDecision):
        trades = []
        for t in d.trades:
            if isinstance(t, HedgeTrade):
                trades.append({"kind": "swap", "tenor": t.tenor, "side": t.side.value, "notional": t.notional})
            elif isinstance(t, FuturesTrade):
                trades.append({"kind": "future", "code": t.code, "contracts": t.contracts})
            elif isinstance(t, BondTrade):
                trades.append({"kind": "bond", "code": t.code, "face": t.face})
            else:
                raise TypeError(f"unknown trade {t!r}")
        return {"type": "hedge", "label": d.label, "trades": trades}
    raise TypeError(f"unknown decision {d!r}")


def decode_decision(e: Mapping):
    kind = e["type"]
    if kind == "quote":
        return QuoteDecision(float(e["bid"]), float(e["offer"]))
    if kind == "rfq":
        return RFQDecision(None if e["level"] is None else float(e["level"]))
    if kind == "checkpoint":
        return CheckpointAnswer(str(e["raw"]))
    if kind == "hedge":
        trades = []
        for t in e["trades"]:
            if t["kind"] == "swap":
                trades.append(HedgeTrade(int(t["tenor"]), Side(t["side"]), float(t["notional"])))
            elif t["kind"] == "future":
                trades.append(FuturesTrade(str(t["code"]), float(t["contracts"])))
            elif t["kind"] == "bond":
                trades.append(BondTrade(str(t["code"]), float(t["face"])))
            else:
                raise ValueError(f"unknown trade kind {t['kind']!r}")
        return HedgeDecision(tuple(trades), str(e.get("label", "")))
    raise ValueError(f"unknown decision type {kind!r}")
