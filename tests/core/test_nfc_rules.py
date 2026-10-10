"""NFC rules preserve stable identities and compile native exclusive branches."""

import unittest
from copy import deepcopy

from custom_components.charge_tally.nfc_rules import (
    compile_automation,
    execution_config,
    validate_draft,
)


class NfcRuleTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "points": [{"id": "p", "name": "Garage"}],
            "identities": [
                {"id": "a", "name": "Alice"},
                {"id": "b", "name": "Bob"},
                {"id": "unassigned", "name": "Unassigned"},
            ],
            "tags": [{"id": "t", "name": "Tag"}],
            "devices": [{"id": "d1", "name": "Phone"}, {"id": "d2", "name": "Phone"}],
        }
        self.draft = {
            "point_id": "p",
            "tag_id": "t",
            "device_bindings": [{"device_id": "d1", "identity_id": "a"}],
            "default_identity_id": "b",
        }
        self.copy = {"name": "Managed NFC", "description": "Edit in Charge Tally"}

    def test_duplicate_device_is_rejected_but_shared_identity_is_allowed(self):
        self.draft["device_bindings"].append({"device_id": "d1", "identity_id": "b"})
        with self.assertRaisesRegex(ValueError, "duplicate_device"):
            validate_draft(self.draft, self.catalog)
        self.draft["device_bindings"][-1] = {"device_id": "d2", "identity_id": "a"}
        self.assertEqual(
            len(validate_draft(self.draft, self.catalog)["device_bindings"]), 2
        )

    def test_invalid_references_and_empty_rule_are_rejected(self):
        for field in ("point_id", "tag_id", "default_identity_id"):
            with self.subTest(field=field):
                draft = {**self.draft, field: "missing"}
                with self.assertRaisesRegex(ValueError, "invalid_reference"):
                    validate_draft(draft, self.catalog)
        self.draft.update(device_bindings=[], default_identity_id=None)
        with self.assertRaisesRegex(ValueError, "empty_rule"):
            validate_draft(self.draft, self.catalog)
        self.draft["default_identity_id"] = "unassigned"
        self.assertEqual(validate_draft(self.draft, self.catalog), self.draft)

    def test_inactive_identity_and_unregistered_device_are_rejected(self):
        self.catalog["identities"][0]["active"] = False
        with self.assertRaisesRegex(ValueError, "invalid_reference"):
            validate_draft(self.draft, self.catalog)
        self.catalog["identities"][0]["active"] = True
        self.draft["device_bindings"][0]["device_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "invalid_reference"):
            validate_draft(self.draft, self.catalog)

    def test_compile_uses_exclusive_native_branches_and_stable_action_ids(self):
        config = compile_automation("r", "auto-id", self.draft, 2, self.copy)
        self.assertEqual(config["triggers"], [{"trigger": "tag", "tag_id": "t"}])
        self.assertEqual(config["mode"], "queued")
        self.assertNotIn("initial_state", config)
        self.assertNotIn("max", config)
        branch = config["actions"][0]
        self.assertEqual(len(branch["choose"]), 1)
        action = branch["choose"][0]["sequence"][0]
        self.assertEqual(
            action,
            {
                "action": "charge_tally.select_identity",
                "data": {
                    "point_id": "p",
                    "identity_id": "a",
                    "rule_id": "r",
                    "rule_version": 2,
                },
            },
        )
        self.assertEqual(branch["default"][0]["data"]["identity_id"], "b")
        self.draft["default_identity_id"] = None
        self.assertEqual(
            compile_automation("r", "auto-id", self.draft, 3, self.copy)["actions"][0][
                "default"
            ],
            [],
        )

    def test_names_and_device_ids_never_become_template_source(self):
        self.draft["device_bindings"][0]["device_id"] = "phone'{{ 1 / 0 }}<script>"
        config = compile_automation("r", "auto-id", self.draft, 1, self.copy)
        template = config["actions"][0]["choose"][0]["conditions"][0]["value_template"]
        self.assertNotIn("<script>", template)
        self.assertEqual(
            config["variables"]["nfc_devices"], ["phone'{{ 1 / 0 }}<script>"]
        )

    def test_execution_fingerprint_ignores_copy_but_not_behavior(self):
        config = compile_automation("r", "auto-id", self.draft, 1, self.copy)
        renamed = {
            **config,
            "alias": "Renamed",
            "description": "",
            "trace": {"stored_traces": 10},
        }
        self.assertEqual(execution_config(config), execution_config(renamed))
        for key, value in (
            ("initial_state", True),
            ("mode", "parallel"),
            ("unknown", 1),
            ("conditions", [{"condition": "template", "value_template": False}]),
        ):
            changed = deepcopy(config)
            changed[key] = value
            self.assertNotEqual(execution_config(config), execution_config(changed))
        legacy = deepcopy(config)
        legacy["trigger"] = legacy.pop("triggers")
        legacy["action"] = legacy.pop("actions")
        self.assertEqual(execution_config(config), execution_config(legacy))
