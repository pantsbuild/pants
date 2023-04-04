# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.javascript.dependency_inference.import_parser.rules import (
    InstalledJavascriptImportParser,
    JSImportStrings,
    ParseJsImportStrings,
)
from pants.backend.javascript.dependency_inference.import_parser.rules import (
    rules as import_parser_rules,
)
from pants.backend.javascript.target_types import (
    JSSourceField,
    JSSourcesGeneratorTarget,
    JSSourceTarget,
)
from pants.build_graph.address import Address
from pants.engine.internals.native_engine import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *import_parser_rules(),
            QueryRule(JSImportStrings, (ParseJsImportStrings,)),
            QueryRule(InstalledJavascriptImportParser, ()),
        ],
        target_types=[JSSourceTarget, JSSourcesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_installs_parser_modules(rule_runner: RuleRunner) -> None:
    result = rule_runner.request(InstalledJavascriptImportParser, ())

    snapshot = rule_runner.request(Snapshot, (result.digest,))
    assert "node_modules" in snapshot.dirs


def test_parses_require_imports(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "javascript_sources()\n",
            "src/a.js": dedent(
                """\
                const mod = require("@a-special-module/for-me");
                const fs = require('fs').promises;
                const { someVar } = require('./local');

                require("no-assignment"); // for side-effects
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src", target_name="src", relative_file_path="a.js"))
    imports = rule_runner.request(JSImportStrings, (ParseJsImportStrings(tgt[JSSourceField]),))
    assert set(imports) == {"fs", "@a-special-module/for-me", "no-assignment", "./local"}


def test_parses_module_imports(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "javascript_sources()\n",
            "src/a.js": dedent(
                """\
                import { promises as fs } from 'fs';
                import * as mod from "@a-special-module/for-me";
                import { someVar } from "./local";

                const dynamicModule = await import("./maybe.wasm");
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src", target_name="src", relative_file_path="a.js"))
    imports = rule_runner.request(JSImportStrings, (ParseJsImportStrings(tgt[JSSourceField]),))
    assert set(imports) == {"fs", "@a-special-module/for-me", "./local", "./maybe.wasm"}


def test_parses_modules_from_not_valid_js_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "javascript_sources()\n",
            "src/a.js": dedent(
                """\
                import { promises as fs } from 'fs';
                import * as mod from "@a-special-module/for-me";

                a b // invalid js
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src", target_name="src", relative_file_path="a.js"))
    imports = rule_runner.request(JSImportStrings, (ParseJsImportStrings(tgt[JSSourceField]),))
    assert set(imports) == {"fs", "@a-special-module/for-me"}
