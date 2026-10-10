"""Validate NFC bindings and compile them to native Home Assistant automations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict


class DeviceBinding(TypedDict):
    device_id: str
    identity_id: str


class RuleDraft(TypedDict):
    point_id: str
    tag_id: str
    device_bindings: list[DeviceBinding]
    default_identity_id: str | None


class Catalog(TypedDict):
    points: list[dict[str, Any]]
    identities: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    devices: list[dict[str, Any]]


class RuleVersion(TypedDict):
    version: int
    draft: RuleDraft
    automation_config: dict[str, Any]
    tag_epoch: int


class PreparedChange(TypedDict):
    operation_id: str
    rule_id: str
    revision: int
    automation_id: str
    kind: str
    expected_config: dict[str, Any] | None
    desired_config: dict[str, Any] | None
    draft: RuleDraft | None
    version: int
    tag_epoch: int


class ManagedRule(TypedDict):
    rule_id: str
    automation_id: str
    revision: int
    applied: RuleVersion | None
    pending: PreparedChange | None
    deleting: bool


class Inspection(TypedDict):
    config_status: str
    runtime_status: str
    automation_entity_id: str | None
    pending_state: str | None


def validate_draft(draft: RuleDraft, catalog: Catalog) -> RuleDraft:
    """Require current, unambiguous references before persisting a rule."""
    if not isinstance(draft, dict) or set(draft) != {
        "point_id",
        "tag_id",
        "device_bindings",
        "default_identity_id",
    }:
        raise ValueError("invalid_request")
    valid = {
        key: {item["id"] for item in values if item.get("active", True)}
        for key, values in catalog.items()
    }
    for field, category in (("point_id", "points"), ("tag_id", "tags")):
        if not isinstance(draft[field], str) or draft[field] not in valid[category]:
            raise ValueError("invalid_reference")
    default = draft["default_identity_id"]
    if default is not None and (
        not isinstance(default, str) or default not in valid["identities"]
    ):
        raise ValueError("invalid_reference")
    bindings = draft["device_bindings"]
    if not isinstance(bindings, list):
        raise ValueError("invalid_request")
    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {
            "device_id",
            "identity_id",
        }:
            raise ValueError("invalid_request")
        device, identity = binding["device_id"], binding["identity_id"]
        if (
            not isinstance(device, str)
            or not isinstance(identity, str)
            or device not in valid["devices"]
            or identity not in valid["identities"]
        ):
            raise ValueError("invalid_reference")
        if device in seen:
            raise ValueError("duplicate_device")
        seen.add(device)
    if not bindings and default is None:
        raise ValueError("empty_rule")
    return deepcopy(draft)


def compile_automation(
    rule_id: str,
    automation_id: str,
    draft: RuleDraft,
    version: int,
    copy: dict[str, str],
) -> dict[str, Any]:
    """Let HA route one event to at most one identity action."""

    def action(identity):
        return {
            "action": "charge_tally.select_identity",
            "data": {
                "point_id": draft["point_id"],
                "identity_id": identity,
                "rule_id": rule_id,
                "rule_version": version,
            },
        }

    return {
        "id": automation_id,
        "alias": copy["name"],
        "description": copy["description"],
        "triggers": [{"trigger": "tag", "tag_id": draft["tag_id"]}],
        "variables": {
            "nfc_devices": [item["device_id"] for item in draft["device_bindings"]]
        },
        "mode": "queued",
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [
                            {
                                "condition": "template",
                                "value_template": (
                                    "{{ trigger.event.data.get('device_id') == nfc_devices["
                                    + str(index)
                                    + "] }}"
                                ),
                            }
                        ],
                        "sequence": [action(item["identity_id"])],
                    }
                    for index, item in enumerate(draft["device_bindings"])
                ],
                "default": (
                    [action(draft["default_identity_id"])]
                    if draft["default_identity_id"] is not None
                    else []
                ),
            }
        ],
    }


def execution_config(config: dict[str, Any]) -> dict[str, Any]:
    """Compare executable settings conservatively, retaining unknown fields."""
    result = deepcopy(config)
    for key in ("id", "alias", "description", "trace"):
        result.pop(key, None)
    for legacy, current in (
        ("trigger", "triggers"),
        ("condition", "conditions"),
        ("action", "actions"),
    ):
        if legacy in result and current not in result:
            result[current] = result.pop(legacy)
    if result.get("conditions") == []:
        result.pop("conditions")
    return result
