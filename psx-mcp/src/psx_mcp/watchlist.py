from __future__ import annotations
import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .models import AlertCondition, AlertRule, WatchEntry, RuleType


def _today() -> date:
    return date.today()


def _ser(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump()
    raise TypeError(f"not serializable: {type(o)}")


class WatchlistStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {"watch": [], "rules": []}
        if self.path.exists() and self.path.stat().st_size:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, default=_ser, indent=2), encoding="utf-8")

    # ---- watch ----
    def add_watch(self, symbol: str, notes: Optional[str] = None) -> WatchEntry:
        sym = symbol.upper()
        for w in self._data["watch"]:
            if w["symbol"] == sym:
                return WatchEntry(**{**w, "added_at": date.fromisoformat(w["added_at"])})
        entry = WatchEntry(symbol=sym, notes=notes, added_at=_today())
        self._data["watch"].append(json.loads(entry.model_dump_json()))
        self._save()
        return entry

    def remove_watch(self, symbol: str) -> bool:
        sym = symbol.upper()
        before = len(self._data["watch"])
        self._data["watch"] = [w for w in self._data["watch"] if w["symbol"] != sym]
        if len(self._data["watch"]) < before:
            self._save()
            return True
        return False

    def list_watch(self) -> list[WatchEntry]:
        return [
            WatchEntry(**{**w, "added_at": date.fromisoformat(w["added_at"])})
            for w in self._data["watch"]
        ]

    # ---- rules ----
    def set_alert_rule(self, *, symbol: str, type: RuleType,
                       condition: AlertCondition, rule_id: Optional[str] = None) -> AlertRule:
        rid = rule_id or f"{symbol.lower()}-{type}-{uuid.uuid4().hex[:6]}"
        rule = AlertRule(
            id=rid, symbol=symbol, type=type, condition=condition,
            active=True, created_at=_today(),
        )
        self._data["rules"] = [r for r in self._data["rules"] if r["id"] != rid]
        self._data["rules"].append(json.loads(rule.model_dump_json()))
        self._save()
        return rule

    def list_alert_rules(self, symbol: Optional[str] = None) -> list[AlertRule]:
        out = []
        for r in self._data["rules"]:
            if symbol and r["symbol"] != symbol.upper():
                continue
            out.append(AlertRule(**{
                **r,
                "created_at": date.fromisoformat(r["created_at"]),
                "last_checked": (datetime.fromisoformat(r["last_checked"])
                                 if r.get("last_checked") else None),
            }))
        return out

    def remove_alert_rule(self, rule_id: str) -> bool:
        before = len(self._data["rules"])
        self._data["rules"] = [r for r in self._data["rules"] if r["id"] != rule_id]
        if len(self._data["rules"]) < before:
            self._save()
            return True
        return False

    def mark_checked(self, rule_id: str, at: datetime) -> None:
        for r in self._data["rules"]:
            if r["id"] == rule_id:
                r["last_checked"] = at.isoformat()
        self._save()
