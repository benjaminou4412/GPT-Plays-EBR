
# Earthborne Rangers — Elemental JSON State Manager

A tiny, deterministic helper to perform **regex-free, minimal** updates to a JSON game state for Earthborne Rangers. It’s designed so an LLM (or you) can:

- Parse → **mutate with code** → serialize
- Make **elemental** changes (set state, add tokens, move/discard, add a card from a DB)
- Avoid ambiguity (explicit errors when selection is ambiguous or not found)
- Keep all **visible cards** self-contained (title, rules, tokens, traits in `data`, etc.)
- **Always seed** `enters_play_with` tokens when a card enters play (even when the amount is `0`).

## Install / Use

No dependencies beyond Python’s standard library. Drop `ebr_state_manager.py` into your project.

```python
from ebr_state_manager import (
    load_state, save_state, tolerant_load_json,
    select_cards, set_card_state, add_tokens, move_card,
    discard_card, add_card_from_db, find_in_db_by_title
)

state = load_state("game_state.json")
```

## JSON State Layout (minimal, extensible)

```jsonc
{
  "metadata": { "day": 2, "phase": "Setup", "step": "…", "created_at": "…" },
  "campaign": { "log": ["IMPRESSED CALYPSA"] },
  "surroundings": {
    "location": { "id": "…", "title": "White Sky", "type": "location", "state": "ready", "rules": [...], "tokens": { "progress": 0 }, "data": {...} },
    "weather":  { "id": "…", "title": "Midday Sun", "type": "weather",  "state": "ready", "rules": [...], "tokens": { "cloud": 0 },  "data": {...} },
    "missions": [{ "id": "…", "title": "Biscuit Delivery", "type": "mission", "state": "ready", "rules": [...], "tokens": {}, "data": {...} }]
  },
  "along_the_way": [ /* feature/being cards */ ],
  "within_reach": { "ranger_1": [ /* beings/features */ ] },
  "rangers": {
    "ranger_1": {
      "hand": [ /* cards with state: "in_hand" */ ],
      "discard_pile": [ /* public information */ ]
    }
  }
}
```

Notes:
- Token names are literal (e.g., `"progress"`, `"harm"`, `"cloud"`).

## Core Operations (Elemental)

### Select, then set a card’s state
```python
state = set_card_state(state, {"title": "Prowling Wolhund", "zone": "within_reach.ranger_1"}, "exhausted")
```

### Add / remove tokens (0 prunes the key)
```python
state = add_tokens(state, {"title": "Topside Mast", "zone": "along_the_way"}, {"progress": +2})
state = add_tokens(state, {"title": "Prowling Wolhund"}, {"harm": +2})
```

### Move a card (between lists/zones)
```python
state = move_card(state, {"title": "Pokodo the Ferret", "zone": "rangers.ranger_1.hand"}, ("within_reach","ranger_1"))
```

### Discard a card
```python
state = discard_card(state, {"title": "Perceptive", "zone": "rangers.ranger_1.hand"}, ranger_id="ranger_1")
```

### Add a card from a DB (with rules + enters_play_with)
```python
weather_db = tolerant_load_json("weather.json")
state = add_card_from_db(state, db=weather_db, title="A Perfect Day", dest_path=("surroundings","weather"), fallback_type="weather", card_state="ready")
```

> The helper seeds tokens from `enters_play_with` automatically (even if `0`).

## Recipes

### Travel (minimal)
1. Swap `surroundings.location` to the new location (fresh instance with `progress: 0`).
2. Clear `along_the_way = []` and `within_reach.* = []` (or filter to keep `Persistent` yourself).
3. Add any “arrival” cards to `along_the_way` or `within_reach` using `add_card_from_db`.

### End Day → New Day (minimal)
1. Start a fresh state object for day N+1 (preserving `campaign.log`).
2. Re-add Weather, Location, Missions with `add_card_from_db` (tokens auto-seeded).
3. Add arrival cards to `along_the_way`.
4. Build your starting hand under `rangers.<id>.hand` with `card_state="in_hand"`.

## Ambiguity Handling

- Title selection is fuzzy (case/punctuation/articles ignored), but **never** guesses if multiple matches exist — it **raises** with candidates listed. Pass an `id` or a narrower `zone` to disambiguate.

## Gotchas & Guarantees

- All mutators are **pure**: they return a deep-copied state; you decide when to `save_state`.
- No hidden cleanup: we do not auto-clear on thresholds, travel, etc., unless you explicitly do it.
- Enter-play tokens are always set from the DB when you add a card via `add_card_from_db`.

## Example

```python
from ebr_state_manager import load_state, save_state, tolerant_load_json, add_card_from_db, add_tokens, set_card_state

state = {
  "metadata": {"day": 2, "phase": "Setup"},
  "surroundings": {}, "along_the_way": [], "within_reach": {"ranger_1": []},
  "rangers": {"ranger_1": {"hand": [], "discard_pile": []}}, "campaign": {"log": []},
}

# Add weather and seed tokens per DB
weather_db = tolerant_load_json("weather.json")
state = add_card_from_db(state, db=weather_db, title="Midday Sun", dest_path=("surroundings","weather"), fallback_type="weather")

# Put a feature along the way and advance it
lts_db = tolerant_load_json("lone_tree_station.json")
state = add_card_from_db(state, db=lts_db, title="Topside Mast", dest_path=("along_the_way",), fallback_type="feature")
state = add_tokens(state, {"title": "Topside Mast", "zone": "along_the_way"}, {"progress": +2})

# Exhaust a being within reach
woods_db = tolerant_load_json("woods.json")
state = add_card_from_db(state, db=woods_db, title="Prowling Wolhund", dest_path=("within_reach","ranger_1"), fallback_type="being")
state = set_card_state(state, {"title": "Prowling Wolhund", "zone": "within_reach.ranger_1"}, "exhausted")

save_state(state, "game_state.json")
```

---

If you need extra helpers (e.g., `travel_minimal`), you can build them on top of these primitives without changing the philosophy.
