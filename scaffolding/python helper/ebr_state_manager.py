
# ebr_state_manager.py
# Elemental JSON state manager for Earthborne Rangers
# - Deterministic, regex-free updates
# - Fuzzy-safe selection by id/title with zone hints
# - Token/state ops
# - Optional DB integration helpers (attach rules, seed enters_play_with tokens)
#
# Standard library only.

from typing import Any, Dict, List, Tuple, Iterable, Union, Optional
import re, copy, json

PathT = Tuple[Union[str, int], ...]

# ---------- Serialization ----------

def dump_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)

def load_json(text: str) -> Dict[str, Any]:
    return json.loads(text)

def load_state(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# Tolerant JSON for DB files that may contain trailing commas or BOMs
def tolerant_load_json(path: str):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    raw = raw.lstrip("\ufeff")
    raw = re.sub(r",\s*([}\]])", r"\1", raw)  # strip trailing commas
    return json.loads(raw)

# ---------- Utilities ----------

def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s

def norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).strip()

def _normalize_article(s: str) -> str:
    s = slugify(s)
    return re.sub(r"^(the_|a_|an_)", "", s)

# ---------- Structure traversal ----------

def _traverse(node: Any, path: PathT = ()) -> Iterable[Tuple[PathT, Any]]:
    yield (path, node)
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _traverse(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _traverse(v, path + (i,))

def _get_parent_and_key(root: Any, path: PathT):
    if not path:
        raise ValueError("Empty path")
    parent = root
    for key in path[:-1]:
        parent = parent[key]
    return parent, path[-1]

def _is_card(obj: Any) -> bool:
    return isinstance(obj, dict) and "id" in obj and "title" in obj

# ---------- Selection ----------

def _title_match_score(query_title: str, card_title: str):
    qs = _normalize_article(query_title)
    ts = _normalize_article(card_title)
    if ts == qs: return 0
    if ts.startswith(qs) or qs.startswith(ts): return 1
    if (qs in ts) or (ts in qs): return 2
    return None

def select_cards(state: Dict[str, Any], *, 
                 id: Optional[str]=None, 
                 title: Optional[str]=None,
                 zone_hint: Optional[str]=None) -> List[Tuple[PathT, Dict[str, Any]]]:
    if id is None and title is None:
        raise ValueError("Select requires id or title.")
    results: List[Tuple[PathT, Dict[str, Any]]] = []
    for path, node in _traverse(state):
        if not _is_card(node):
            continue
        if zone_hint is not None:
            dotted = ".".join(map(str, path))
            if not dotted.startswith(zone_hint):
                continue
        if id is not None and node.get("id") == id:
            results.append((path, node))
            continue
        if title is not None:
            score = _title_match_score(title, node.get("title",""))
            if score is not None:
                results.append((path + ("__score__", score), node))
    if title and id is None:
        def sort_key(item):
            path, _ = item
            if len(path) >= 2 and path[-2] == "__score__":
                return path[-1]
            return 99
        results.sort(key=sort_key)
        cleaned: List[Tuple[PathT, Dict[str, Any]]] = []
        for path, node in results:
            if len(path) >= 2 and path[-2] == "__score__":
                path = path[:-2]
            cleaned.append((path, node))
        results = cleaned
    return results

def select_one(state: Dict[str, Any], *, id: Optional[str]=None, title: Optional[str]=None, zone_hint: Optional[str]=None) -> Tuple[PathT, Dict[str, Any]]:
    matches = select_cards(state, id=id, title=title, zone_hint=zone_hint)
    if not matches:
        raise ValueError("No card matched the selector.")
    if len(matches) > 1:
        options = [f"{m[1]['title']} (id={m[1]['id']}) @ {'.'.join(map(str, m[0]))}" for m in matches]
        raise ValueError("Ambiguous selector; matches:\n- " + "\n- ".join(options))
    return matches[0]

# ---------- Elemental mutations ----------

def set_card_state(state: Dict[str, Any], selector: Dict[str, str], new_state: str) -> Dict[str, Any]:
    allowed = {"ready","exhausted","cleared","out_of_play","in_hand","discarded"}
    if new_state not in allowed:
        raise ValueError(f"Unsupported state '{new_state}'. Allowed: {sorted(allowed)}")
    path, _ = select_one(state, id=selector.get("id"), title=selector.get("title"), zone_hint=selector.get("zone"))
    new_state_obj = copy.deepcopy(state)
    parent, key = _get_parent_and_key(new_state_obj, path)
    parent[key]["state"] = new_state
    return new_state_obj

def add_tokens(state: Dict[str, Any], selector: Dict[str, str], token_delta: Dict[str, int]) -> Dict[str, Any]:
    path, _ = select_one(state, id=selector.get("id"), title=selector.get("title"), zone_hint=selector.get("zone"))
    new_state_obj = copy.deepcopy(state)
    parent, key = _get_parent_and_key(new_state_obj, path)
    tokens = parent[key].setdefault("tokens", {})
    for t, delta in token_delta.items():
        tokens[t] = int(tokens.get(t, 0)) + int(delta)
        if tokens[t] == 0:
            tokens.pop(t)
    return new_state_obj

def move_card(state: Dict[str, Any], selector: Dict[str, str], dest_path: PathT, index: Optional[int]=None) -> Dict[str, Any]:
    src_path, _ = select_one(state, id=selector.get("id"), title=selector.get("title"), zone_hint=selector.get("zone"))
    new_state_obj = copy.deepcopy(state)
    src_parent, src_key = _get_parent_and_key(new_state_obj, src_path)
    card_obj = src_parent[src_key]
    # Remove from source
    if isinstance(src_parent, list):
        src_parent.pop(src_key)
    elif isinstance(src_parent, dict):
        src_parent.pop(src_key)
    else:
        raise ValueError("Unsupported source container type.")
    # Navigate destination
    dest_parent = new_state_obj
    for k in dest_path:
        if isinstance(dest_parent, list):
            if isinstance(k, int):
                # no-op; we will insert by index later
                pass
            else:
                raise ValueError("Tried to access key on list while navigating dest path.")
        else:
            if k not in dest_parent:
                dest_parent[k] = []
            dest_parent = dest_parent[k]
    if not isinstance(dest_parent, list):
        raise ValueError("Destination is not a list.")
    if index is None:
        dest_parent.append(card_obj)
    else:
        dest_parent.insert(index, card_obj)
    return new_state_obj

def discard_card(state: Dict[str, Any], selector: Dict[str, str], *, ranger_id: str="ranger_1") -> Dict[str, Any]:
    # Remove from current zone and push to rangers[ranger_id].discard_pile with state 'discarded'
    src_path, _ = select_one(state, id=selector.get("id"), title=selector.get("title"), zone_hint=selector.get("zone"))
    new_state_obj = copy.deepcopy(state)
    src_parent, src_key = _get_parent_and_key(new_state_obj, src_path)
    card_obj = src_parent[src_key]
    if isinstance(src_parent, list):
        src_parent.pop(src_key)
    elif isinstance(src_parent, dict):
        src_parent.pop(src_key)
    card_obj["state"] = "discarded"
    r = new_state_obj.setdefault("rangers", {}).setdefault(ranger_id, {})
    r.setdefault("discard_pile", []).append(card_obj)
    return new_state_obj

# ---------- DB helpers (optional) ----------

def find_in_db_by_title(db: Union[List[Dict[str,Any]], Dict[str,Any]], title: str) -> Optional[Dict[str,Any]]:
    it = db if isinstance(db, list) else list(db.values())
    target = norm(title)
    for item in it:
        t = item.get("title") or item.get("name") or ""
        if norm(t) == target:
            return item
    # retry space-stripped
    for item in it:
        t = item.get("title") or item.get("name") or ""
        if norm(t).replace(" ", "") == target.replace(" ", ""):
            return item
    return None

def build_instance_from_db(src: Dict[str, Any], *, fallback_type: str="card", state: str="ready") -> Dict[str, Any]:
    inst = {
        "id": src.get("id") or src.get("slug") or norm(src.get("title","")),
        "title": src.get("title") or src.get("name") or "(untitled)",
        "type": src.get("card_type") or src.get("type") or fallback_type,
        "state": state,
        "rules": src.get("rules", []),
        "tokens": {},
        "data": {"card_ref_id": src.get("id") or src.get("slug")}
    }
    for k in ["traits", "presence", "harm_threshold", "progress_threshold", "approach_icons", "aspect_requirement", "energy_cost"]:
        if k in src and src[k] not in (None, {}, []):
            inst["data"][k] = src[k]
    # Seed tokens per enters_play_with (always)
    _apply_enters_play_with(inst, src)
    return inst

def _apply_enters_play_with(instance: Dict[str,Any], source: Dict[str,Any]) -> None:
    epw = source.get("enters_play_with")
    instance.setdefault("tokens", {})
    if isinstance(epw, dict):
        t = (epw.get("type") or epw.get("token") or epw.get("name") or "").strip().lower()
        n = epw.get("count") if epw.get("count") is not None else epw.get("amount")
        if t:
            instance["tokens"][t] = int(n or 0)  # exact, even zero
    elif isinstance(epw, list):
        # reset then set each listed token
        instance["tokens"].clear()
        for entry in epw:
            if not isinstance(entry, dict): 
                continue
            t = (entry.get("type") or entry.get("token") or entry.get("name") or "").strip().lower()
            n = entry.get("count") if entry.get("count") is not None else entry.get("amount")
            if t:
                instance["tokens"][t] = int(n or 0)

# Convenience: add a DB card to a zone
def add_card_from_db(state: Dict[str,Any], *, db: Union[List[Dict[str,Any]], Dict[str,Any]], title: str, dest_path: PathT, fallback_type: str="card", card_state: str="ready") -> Dict[str,Any]:
    src = find_in_db_by_title(db, title)
    if not src:
        raise ValueError(f"Card titled '{title}' not found in provided DB.")
    inst = build_instance_from_db(src, fallback_type=fallback_type, state=card_state)
    new_state = copy.deepcopy(state)
    # Navigate destination
    dest_parent = new_state
    for k in dest_path:
        if isinstance(dest_parent, list):
            if not isinstance(k, int):
                raise ValueError("Tried to access key on list while navigating dest path.")
        else:
            if k not in dest_parent:
                dest_parent[k] = []
            dest_parent = dest_parent[k]
    if not isinstance(dest_parent, list):
        raise ValueError("Destination is not a list.")
    dest_parent.append(inst)
    return new_state
