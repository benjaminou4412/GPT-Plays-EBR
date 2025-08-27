
"""
Earthborne Rangers — Elemental State Helper (v1.2)
--------------------------------------------------
Purpose
  Keep a structured board state, apply tiny, atomic updates (setters),
  validate invariants, and render a canonical YAML snapshot to paste
  into your canvas.

Design
  • One plain Python module, no external services.
  • Elemental reducers only (no big "apply_challenge"—you drive choices).
  • Attachments always live in the same zone as their host.
  • Full-snapshot render for reliability; avoid incremental text edits.

Quickstart
  from ebr_state_helper import Engine, Card
  eng = Engine()
  eng.set_weather({"title":"A Perfect Day","state":"Ready","tokens":{"cloud":3}})
  eng.set_location({"title":"White Sky","traits":["Pivotal","Water","Trail"],"presence":1,
                    "progress_threshold":"3R","harm_threshold":-1,"state":"Ready",
                    "tokens":{"progress":0,"harm":0}})
  ar = eng.add_card("within_reach", Card(title="Ar Tel, Angler", traits=["Human","Villager"],
                                         presence=1, progress_threshold="2R", harm_threshold=3).to_dict())
  # Render YAML snapshot
  print(eng.render_yaml())

Zones
  • surroundings.weather, surroundings.location, surroundings.missions
  • along_the_way, within_reach
  • ranger.{role,aspects,gear,injuries,deck_size,fatigue_size,discard_pile,hand}

Notes
  • Methods prefer id-based updates to avoid title collisions.
  • Minimal validation: negative energy/tokens, attachment zone mismatch.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
    _HAVE_YAML = True
except Exception:
    yaml = None
    _HAVE_YAML = False


# ------------------------- helpers -------------------------

def _gen_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:8]}"

def _deepcopy(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


# -------------------------- data ---------------------------

@dataclass
class Card:
    title: str
    traits: List[str] = field(default_factory=list)
    type: Optional[str] = None
    presence: Optional[int] = None
    progress_threshold: Any = None
    harm_threshold: Any = None
    state: str = "Ready"         # "Ready" | "Exhausted"
    friendly: Optional[bool] = None
    persistent: Optional[bool] = None
    tokens: Dict[str, int] = field(default_factory=dict)   # e.g., {"progress":0,"harm":0,"glint":2}
    attachments: List[str] = field(default_factory=list)   # child card ids
    id: str = field(default_factory=lambda: _gen_id("card"))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # drop Nones/empties for cleaner YAML
        return {k: v for k, v in d.items() if v not in (None, [], {})}


# -------------------------- engine -------------------------

class Engine:
    def __init__(self, state: Optional[Dict[str, Any]] = None) -> None:
        self.state: Dict[str, Any] = state if state is not None else self._empty_state()

    # ---- skeleton ----
    def _empty_state(self) -> Dict[str, Any]:
        return {
            "campaign_log": {
                "campaign": "Lure of the Valley",
                "current_location": None,
                "path_terrain": None,
                "missions": [],
                "unlocked_rewards": [],
                "notable_events": [],
            },
            "surroundings": {
                "weather": None,
                "location": None,
                "missions": [],      # missions that physically sit in surroundings
            },
            "along_the_way": [],
            "within_reach": [],
            "ranger": {
                "role": {"name":"Prodigy of the Floating Tower","state":"Ready","tokens":{}},
                "aspects": {
                    "printed": {"AWA":3,"FIT":2,"FOC":2,"SPI":1},
                    "energy":  {"AWA":3,"FIT":2,"FOC":2,"SPI":1},
                },
                "gear": [],
                "injuries": 0,
                "deck_size": 30,
                "fatigue_size": 0,
                "discard_pile": [],
                "hand": [],
            },
        }

    # ---- hydrate / render ----
    def hydrate_yaml(self, yaml_text: str) -> None:
        if _HAVE_YAML:
            self.state = yaml.safe_load(yaml_text) or {}
        else:
            self.state = json.loads(yaml_text)

    def render_yaml(self) -> str:
        if _HAVE_YAML:
            return yaml.safe_dump(self.state, sort_keys=False, allow_unicode=True)
        return json.dumps(self.state, indent=2, ensure_ascii=False)

    # ---- state access ----
    def get_state(self) -> Dict[str, Any]:
        return _deepcopy(self.state)

    def set_state(self, state: Dict[str, Any]) -> None:
        self.state = _deepcopy(state)

    # ---- location / weather ----
    def set_location(self, card_like: Dict[str, Any]) -> str:
        c = self._materialize(card_like, "loc")
        self.state["surroundings"]["location"] = c
        self.state["campaign_log"]["current_location"] = c.get("title")
        return c["id"]

    def set_weather(self, card_like: Dict[str, Any]) -> str:
        c = self._materialize(card_like, "wx")
        self.state["surroundings"]["weather"] = c
        return c["id"]

    # ---- zones ----
    def add_card(self, area: str, card: Card | Dict[str, Any]) -> str:
        if isinstance(card, Card):
            c = card.to_dict()
        else:
            c = self._materialize(card, "card")
        if area not in ("within_reach","along_the_way","surroundings.missions","ranger.gear"):
            raise ValueError("area must be within_reach | along_the_way | surroundings.missions | ranger.gear")
        if area == "surroundings.missions":
            self.state["surroundings"]["missions"].append(c)
        elif area == "ranger.gear":
            self.state["ranger"]["gear"].append(c)
        else:
            self.state[area].append(c)
        return c["id"]

    def remove_card(self, card_id: str) -> None:
        area, idx = self._find(card_id)
        if area is None:
            return
        self._ensure_no_children(card_id)
        self.state[area].pop(idx)

    def move_card(self, card_id: str, area: str) -> None:
        card = self._pop_card(card_id)
        if area == "surroundings.missions":
            self.state["surroundings"]["missions"].append(card)
        elif area == "ranger.gear":
            self.state["ranger"]["gear"].append(card)
        else:
            self.state[area].append(card)

    # ---- attachments ----
    def attach(self, child: Card | Dict[str, Any], host_id: str) -> str:
        child_dict = child.to_dict() if isinstance(child, Card) else self._materialize(child, "card")
        host_area, host_idx = self._find(host_id)
        if host_area is None:
            raise ValueError(f"host {host_id} not found")
        # place child in same area as host
        self.state[host_area].append(child_dict)
        host = self.state[host_area][host_idx]
        host.setdefault("attachments", []).append(child_dict["id"])
        return child_dict["id"]

    def detach(self, child_id: str) -> None:
        area, idx = self._find(child_id)
        if area is None:
            return
        # remove child id from any host attachments in same area
        for c in self.state[area]:
            if isinstance(c, dict) and child_id in c.get("attachments", []):
                c["attachments"] = [x for x in c["attachments"] if x != child_id]
        self.state[area].pop(idx)

    # ---- card flags / tokens ----
    def set_ready(self, card_id: str, ready: bool) -> None:
        card = self._get(card_id)
        card["state"] = "Ready" if ready else "Exhausted"

    def set_friendly(self, card_id: str, friendly: bool) -> None:
        card = self._get(card_id)
        card["friendly"] = friendly

    def set_persistent(self, card_id: str, persistent: bool) -> None:
        card = self._get(card_id)
        card["persistent"] = persistent

    def add_tokens(self, card_id: str, kind: str, n: int) -> None:
        card = self._get(card_id)
        tokens = card.setdefault("tokens", {})
        tokens[kind] = max(0, int(tokens.get(kind, 0)) + int(n))

    def set_tokens(self, card_id: str, kind: str, n: int) -> None:
        card = self._get(card_id)
        tokens = card.setdefault("tokens", {})
        tokens[kind] = max(0, int(n))

    # ---- energy & resources ----
    def spend_energy(self, awa: int=0, fit: int=0, foc: int=0, spi: int=0) -> None:
        e = self.state["ranger"]["aspects"]["energy"]
        for k, v in (("AWA",awa),("FIT",fit),("FOC",foc),("SPI",spi)):
            e[k] = int(e[k]) - int(v)
            if e[k] < 0:
                raise ValueError(f"energy underflow: {k} < 0")

    def add_energy(self, awa: int=0, fit: int=0, foc: int=0, spi: int=0) -> None:
        e = self.state["ranger"]["aspects"]["energy"]
        for k, v in (("AWA",awa),("FIT",fit),("FOC",foc),("SPI",spi)):
            e[k] = int(e[k]) + int(v)

    def set_energy(self, AWA: int, FIT: int, FOC: int, SPI: int) -> None:
        self.state["ranger"]["aspects"]["energy"] = {"AWA":int(AWA),"FIT":int(FIT),"FOC":int(FOC),"SPI":int(SPI)}

    def draw(self, n: int) -> None:
        self.state["ranger"]["deck_size"] = max(0, int(self.state["ranger"]["deck_size"]) - int(n))

    def discard(self, titles: List[str]) -> None:
        self.state["ranger"]["discard_pile"].extend(titles)

    def fatigue(self, n: int) -> None:
        self.state["ranger"]["deck_size"] = max(0, int(self.state["ranger"]["deck_size"]) - int(n))
        self.state["ranger"]["fatigue_size"] = int(self.state["ranger"]["fatigue_size"]) + int(n)

    def soothe(self, n: int) -> None:
        take = min(int(self.state["ranger"]["fatigue_size"]), int(n))
        self.state["ranger"]["fatigue_size"] -= take
        # (Optionally reflect drawn cards into hand elsewhere if you track identities.)

    def set_deck_size(self, n: int) -> None:
        self.state["ranger"]["deck_size"] = max(0, int(n))

    def set_fatigue_size(self, n: int) -> None:
        self.state["ranger"]["fatigue_size"] = max(0, int(n))

    # ---- day helpers ----
    def ready_all(self) -> None:
        for area in ("along_the_way","within_reach"):
            for c in self.state[area]:
                if isinstance(c, dict):
                    c["state"] = "Ready"
        for g in self.state["ranger"]["gear"]:
            g["state"] = "Ready"

    def refresh_energy(self) -> None:
        self.state["ranger"]["aspects"]["energy"] = _deepcopy(self.state["ranger"]["aspects"]["printed"])

    def travel_to(self, location_card: Dict[str, Any]) -> None:
        # Discard path & ranger cards not in player area. Persistent beings remain attached to hosts only across travel;
        # You should enforce "Persistent" by choosing which cards to keep when you mutate within_reach.
        self.state["along_the_way"] = []
        self.state["within_reach"] = [c for c in self.state["within_reach"] if c.get("persistent")]
        self.set_location(location_card)

    def camp(self) -> None:
        # Minimal: Ready & refill; campaign flow will rebuild other parts.
        self.ready_all()
        self.refresh_energy()

    # ---- validation ----
    def validate(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # Build id → zone index
        by_id = {c["id"]:("within_reach", i) for i, c in enumerate(self.state.get("within_reach", [])) if isinstance(c, dict)}
        by_id.update({c["id"]:("along_the_way", i) for i, c in enumerate(self.state.get("along_the_way", [])) if isinstance(c, dict)})
        by_id.update({c["id"]:("ranger.gear", i) for i, c in enumerate(self.state.get("ranger", {}).get("gear", [])) if isinstance(c, dict)})

        def _zone_of(cid: str) -> Optional[str]:
            info = by_id.get(cid)
            return info[0] if info else None

        # Attachment zone consistency
        for cid, (zone, idx) in list(by_id.items()):
            card = self._get(cid)
            for child in card.get("attachments", []):
                cz = _zone_of(child)
                if cz and cz != zone:
                    errors.append(f"Attachment zone mismatch: child {child} not in {zone} with host {cid}")

        # Energy non-negative
        for k, v in self.state["ranger"]["aspects"]["energy"].items():
            if v < 0:
                errors.append(f"Negative energy: {k}={v}")

        # No negative tokens
        for area in ("within_reach","along_the_way","ranger.gear"):
            for c in self._iter_area(area):
                for t, n in c.get("tokens", {}).items():
                    if n < 0:
                        errors.append(f"Negative token {t} on {c.get('title')}")

        return (len(errors) == 0, errors)

    # ----------------------- internals -----------------------
    def _materialize(self, card_like: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        d = _deepcopy(card_like)
        if "id" not in d:
            d["id"] = _gen_id(prefix)
        return d

    def _iter_area(self, area: str) -> List[Dict[str, Any]]:
        if area == "within_reach":
            return self.state["within_reach"]
        if area == "along_the_way":
            return self.state["along_the_way"]
        if area == "ranger.gear":
            return self.state["ranger"]["gear"]
        if area == "surroundings.missions":
            return self.state["surroundings"]["missions"]
        raise ValueError(f"unknown area {area}")

    def _find(self, card_id: str) -> Tuple[Optional[str], Optional[int]]:
        for area in ("within_reach","along_the_way","ranger.gear","surroundings.missions"):
            for i, c in enumerate(self._iter_area(area)):
                if isinstance(c, dict) and c.get("id") == card_id:
                    return area, i
        return None, None

    def _get(self, card_id: str) -> Dict[str, Any]:
        area, idx = self._find(card_id)
        if area is None:
            raise ValueError(f"card {card_id} not found")
        return self.state[area][idx]

    def _pop_card(self, card_id: str) -> Dict[str, Any]:
        area, idx = self._find(card_id)
        if area is None:
            raise ValueError(f"card {card_id} not found")
        self._ensure_no_children(card_id)
        return self.state[area].pop(idx)

    def _ensure_no_children(self, card_id: str) -> None:
        area, idx = self._find(card_id)
        if area is None:
            return
        card = self.state[area][idx]
        if card.get("attachments"):
            raise ValueError("remove/detach child attachments first")
