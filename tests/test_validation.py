"""Tests for state machine JSON validation."""

import pytest

from governor.engine.validation import validate_state_machine


def _base_sm():
    """Return a minimal valid state machine."""
    return {
        "states": {
            "ACTIVE": {"description": "Working", "terminal": False},
            "DONE": {"description": "Finished", "terminal": True},
        },
        "transitions": [
            {
                "id": "T01",
                "from_state": "ACTIVE",
                "to_state": "DONE",
                "allowed_roles": ["EXECUTOR"],
                "guards": [],
            },
        ],
    }


class TestValidateStateMachine:

    def test_valid_state_machine(self):
        errors = validate_state_machine(_base_sm())
        assert errors == []

    def test_missing_states_key(self):
        sm = {"transitions": []}
        errors = validate_state_machine(sm)
        assert any("states" in e for e in errors)

    def test_missing_transitions_key(self):
        sm = {"states": {"A": {"terminal": True}}}
        errors = validate_state_machine(sm)
        assert any("transitions" in e for e in errors)

    def test_no_terminal_state(self):
        sm = {
            "states": {"A": {"terminal": False}, "B": {"terminal": False}},
            "transitions": [{"id": "T01", "from_state": "A", "to_state": "B", "allowed_roles": ["X"]}],
        }
        errors = validate_state_machine(sm)
        assert any("terminal" in e.lower() for e in errors)

    def test_invalid_from_state(self):
        sm = _base_sm()
        sm["transitions"][0]["from_state"] = "NONEXISTENT"
        errors = validate_state_machine(sm)
        assert any("NONEXISTENT" in e for e in errors)

    def test_invalid_to_state(self):
        sm = _base_sm()
        sm["transitions"][0]["to_state"] = "NOWHERE"
        errors = validate_state_machine(sm)
        assert any("NOWHERE" in e for e in errors)

    def test_duplicate_transition_ids(self):
        sm = _base_sm()
        sm["transitions"].append({
            "id": "T01",
            "from_state": "ACTIVE",
            "to_state": "DONE",
            "allowed_roles": ["REVIEWER"],
        })
        errors = validate_state_machine(sm)
        assert any("Duplicate" in e for e in errors)

    def test_terminal_state_with_outbound(self):
        sm = _base_sm()
        sm["transitions"].append({
            "id": "T02",
            "from_state": "DONE",
            "to_state": "ACTIVE",
            "allowed_roles": ["EXECUTOR"],
        })
        errors = validate_state_machine(sm)
        assert any("Terminal" in e or "terminal" in e for e in errors)

    def test_orphan_state(self):
        sm = _base_sm()
        sm["states"]["ORPHAN"] = {"description": "Disconnected", "terminal": False}
        errors = validate_state_machine(sm)
        assert any("Orphan" in e or "ORPHAN" in e for e in errors)

    def test_missing_transition_keys(self):
        sm = {
            "states": {"A": {"terminal": True}},
            "transitions": [{"id": "T01"}],
        }
        errors = validate_state_machine(sm)
        assert any("missing keys" in e for e in errors)

    def test_real_state_machine_passes(self):
        """The shipped state_machine.json should pass validation."""
        import json
        import os
        path = os.path.join(
            os.path.dirname(__file__), os.pardir, "governor", "schema", "state_machine.json"
        )
        with open(path) as f:
            sm = json.load(f)
        errors = validate_state_machine(sm)
        assert errors == [], f"Shipped state machine has errors: {errors}"

    def test_transition_allowed_roles_must_be_non_empty_list_of_strings(self):
        sm = _base_sm()
        sm["transitions"][0]["allowed_roles"] = "EXECUTOR"
        errors = validate_state_machine(sm)
        assert any("allowed_roles" in e for e in errors)

    def test_transition_requires_string_state_names(self):
        sm = _base_sm()
        sm["transitions"][0]["from_state"] = None
        errors = validate_state_machine(sm)
        assert any("from_state" in e for e in errors)

    def test_temporal_fields_must_be_string_lists(self):
        sm = _base_sm()
        sm["transitions"][0]["temporal_fields"] = {"set": [123]}
        errors = validate_state_machine(sm)
        assert any("temporal_fields.set" in e for e in errors)

    def test_inline_guard_requires_guard_id_string(self):
        sm = _base_sm()
        sm["transitions"][0]["guards"] = [{"guard_id": 99, "check": "property_set(x)"}]
        errors = validate_state_machine(sm)
        assert any("inline guard" in e for e in errors)

    def test_event_config_must_be_object(self):
        sm = _base_sm()
        sm["transitions"][0]["events"] = [{"event_id": "E1", "type": "notification", "config": "bad"}]
        errors = validate_state_machine(sm)
        assert any("event.config" in e for e in errors)
