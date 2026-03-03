"""State machine JSON validation.

Validates the structure and integrity of a state machine definition
before the TransitionEngine accepts it. Catches configuration errors
early instead of at runtime.
"""

from typing import Any, Dict, List, Set


def validate_state_machine(sm: Dict[str, Any]) -> List[str]:
    """Validate a state machine definition. Returns list of errors (empty = valid).

    Checks:
        1. Required top-level keys present (states, transitions).
        2. Every transition references defined states.
        3. At least one terminal state exists.
        4. No orphan states (unreachable and no outbound transitions).
        5. No duplicate transition IDs.
        6. Each transition has required keys.
        7. Terminal states have no outbound transitions.
    """
    errors: List[str] = []

    # 1. Required top-level keys
    if "states" not in sm:
        errors.append("Missing required key: 'states'")
    if "transitions" not in sm:
        errors.append("Missing required key: 'transitions'")

    if errors:
        return errors  # Can't continue without both keys

    states: Dict[str, Any] = sm["states"]
    transitions: List[Dict[str, Any]] = sm["transitions"]

    if not isinstance(states, dict) or not states:
        errors.append("'states' must be a non-empty dict")
        return errors

    if not isinstance(transitions, list):
        errors.append("'transitions' must be a list")
        return errors

    state_names: Set[str] = set(states.keys())
    for name, defn in states.items():
        if not isinstance(name, str) or not name.strip():
            errors.append("State names must be non-empty strings")
        if not isinstance(defn, dict):
            errors.append(f"State '{name}' definition must be an object")
            continue
        if "terminal" in defn and not isinstance(defn.get("terminal"), bool):
            errors.append(f"State '{name}': 'terminal' must be boolean")

    # 3. At least one terminal state
    terminal_states = {name for name, defn in states.items()
                       if isinstance(defn, dict) and defn.get("terminal")}
    if not terminal_states:
        errors.append("No terminal state defined (need at least one state with 'terminal': true)")

    # 6. Each transition has required keys + 5. No duplicate IDs
    required_keys = {"id", "from_state", "to_state", "allowed_roles"}
    seen_ids: Set[str] = set()

    from_states: Set[str] = set()
    to_states: Set[str] = set()

    for i, t in enumerate(transitions):
        if not isinstance(t, dict):
            errors.append(f"Transition at index {i} is not a dict")
            continue

        # Required keys
        missing = required_keys - set(t.keys())
        if missing:
            errors.append(f"Transition at index {i} missing keys: {sorted(missing)}")
            continue

        tid = t["id"]
        if not isinstance(tid, str) or not tid.strip():
            errors.append(f"Transition at index {i}: 'id' must be a non-empty string")
            continue

        # Duplicate ID check
        if tid in seen_ids:
            errors.append(f"Duplicate transition ID: '{tid}'")
        seen_ids.add(tid)

        # 2. Valid state references
        fs = t["from_state"]
        ts = t["to_state"]
        if not isinstance(fs, str) or not fs.strip():
            errors.append(f"Transition '{tid}': 'from_state' must be a non-empty string")
        if not isinstance(ts, str) or not ts.strip():
            errors.append(f"Transition '{tid}': 'to_state' must be a non-empty string")

        if fs not in state_names:
            errors.append(f"Transition '{tid}': from_state '{fs}' not in defined states")
        if ts not in state_names:
            errors.append(f"Transition '{tid}': to_state '{ts}' not in defined states")

        allowed_roles = t.get("allowed_roles")
        if not isinstance(allowed_roles, list) or not allowed_roles:
            errors.append(f"Transition '{tid}': 'allowed_roles' must be a non-empty list")
        else:
            bad_roles = [r for r in allowed_roles if not isinstance(r, str) or not r.strip()]
            if bad_roles:
                errors.append(f"Transition '{tid}': all 'allowed_roles' must be non-empty strings")

        guards = t.get("guards", [])
        if not isinstance(guards, list):
            errors.append(f"Transition '{tid}': 'guards' must be a list")
        else:
            for g in guards:
                if isinstance(g, str):
                    continue
                if isinstance(g, dict):
                    guard_id = g.get("guard_id")
                    check = g.get("check", "")
                    if not isinstance(guard_id, str) or not guard_id.strip():
                        errors.append(f"Transition '{tid}': inline guard missing string 'guard_id'")
                    if check and not isinstance(check, str):
                        errors.append(f"Transition '{tid}': inline guard 'check' must be a string")
                    continue
                errors.append(f"Transition '{tid}': each guard must be string or object")

        temporal_fields = t.get("temporal_fields")
        if temporal_fields is not None:
            if not isinstance(temporal_fields, dict):
                errors.append(f"Transition '{tid}': 'temporal_fields' must be an object")
            else:
                for key in ("set", "clear", "increment", "reset"):
                    values = temporal_fields.get(key)
                    if values is None:
                        continue
                    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                        errors.append(
                            f"Transition '{tid}': temporal_fields.{key} must be a list of non-empty strings"
                        )

        events = t.get("events")
        if events is not None:
            if not isinstance(events, list):
                errors.append(f"Transition '{tid}': 'events' must be a list")
            else:
                for idx, event in enumerate(events):
                    if not isinstance(event, dict):
                        errors.append(f"Transition '{tid}': event at index {idx} must be an object")
                        continue
                    if "type" in event and not isinstance(event.get("type"), str):
                        errors.append(f"Transition '{tid}': event.type must be a string")
                    if "event_id" in event and not isinstance(event.get("event_id"), str):
                        errors.append(f"Transition '{tid}': event.event_id must be a string")
                    if "config" in event and not isinstance(event.get("config"), dict):
                        errors.append(f"Transition '{tid}': event.config must be an object")

        from_states.add(fs)
        to_states.add(ts)

    # 7. Terminal states have no outbound transitions
    for ts in terminal_states:
        if ts in from_states:
            errors.append(f"Terminal state '{ts}' has outbound transitions (terminals must be sinks)")

    # 4. Orphan state detection (no inbound AND no outbound)
    connected_states = from_states | to_states
    for name in state_names:
        if name not in connected_states and name not in terminal_states:
            errors.append(f"Orphan state '{name}': no inbound or outbound transitions and not terminal")

    return errors
