
# Quickstart

This folder contains:
- `ebr_state_manager.py` — the helper
- `QUICKSTART.md` — this file
- `SAMPLE_state.json` — a barebones starting state

## Try it

```python
from ebr_state_manager import tolerant_load_json, add_card_from_db, add_tokens, set_card_state, save_state
import json

# Load the sample
state = json.load(open("SAMPLE_state.json","r",encoding="utf-8"))

# Add A Perfect Day weather
weather_db = tolerant_load_json("weather.json")
state = add_card_from_db(state, db=weather_db, title="A Perfect Day", dest_path=("surroundings","weather"), fallback_type="weather")

# Put Topside Mast along the way and add progress
lts_db = tolerant_load_json("lone_tree_station.json")
state = add_card_from_db(state, db=lts_db, title="Topside Mast", dest_path=("along_the_way",), fallback_type="feature")
state = add_tokens(state, {"title":"Topside Mast","zone":"along_the_way"}, {"progress": +2})

# Exhaust a being
woods_db = tolerant_load_json("woods.json")
state = add_card_from_db(state, db=woods_db, title="Prowling Wolhund", dest_path=("within_reach","ranger_1"), fallback_type="being")
state = set_card_state(state, {"title":"Prowling Wolhund","zone":"within_reach.ranger_1"}, "exhausted")

save_state(state, "OUT_state.json")
print("Wrote OUT_state.json")
```

## SAMPLE_state.json

This is minimal but valid. You can replace it with your own at any time.

- Day and phase metadata
- Empty surroundings/zones
- Single Ranger scaffold

Enjoy!
