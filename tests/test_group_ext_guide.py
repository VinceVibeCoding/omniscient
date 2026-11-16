"""The guide written by `ext init` stays valid: its JSON examples pass the validator."""

from __future__ import annotations

import json
import re

from omniscient.group.ext_guide import EXAMPLES, build_guide, scaffold_manifest
from omniscient.group.ext_schema import THEME_VARS, parse_manifest


def test_guide_examples_validate() -> None:
    blocks = re.findall(r"```json\n(.*?)\n```", build_guide(), re.DOTALL)
    assert len(blocks) == 3
    for block in blocks:
        parse_manifest(json.loads(block))
    assert [json.loads(b) for b in blocks] == list(EXAMPLES)


def test_guide_lists_the_allowlist_and_the_rules() -> None:
    guide = build_guide()
    assert all(f"`{v}`" in guide for v in THEME_VARS)
    assert "/reload" in guide and "extension.json" in guide and "LICENSE" in guide


def test_scaffold_is_valid() -> None:
    assert (
        parse_manifest(scaffold_manifest("mon-ext"), "mon-ext").commands[0].name
        == "bonjour"
    )
