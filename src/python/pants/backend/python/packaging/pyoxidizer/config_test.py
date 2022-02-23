# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.packaging.pyoxidizer.config import PyOxidizerConfig


def test_run_module_without_entry_point() -> None:
    config = PyOxidizerConfig(executable_name="my-output", wheels=[], entry_point=None)
    assert config.run_module == ""


def test_run_module_with_entry_point() -> None:
    config = PyOxidizerConfig(executable_name="my-output", wheels=[], entry_point="helloworld.main")
    assert config.run_module == "python_config.run_module = 'helloworld.main'"


def test_render_without_template_uses_default() -> None:
    config = PyOxidizerConfig(
        executable_name="my-output",
        wheels=["wheel1", "wheel2"],
        entry_point="helloworld.main",
        unclassified_resources=["resource1", "resource2"],
    )

    rendered_config = config.render()
    assert "resolve_targets" in rendered_config
    assert all(
        item in rendered_config
        for item in (
            "my-output",
            "wheel1",
            "wheel2",
            "helloworld.main",
            "resource1",
            "resource2",
        )
    )


def test_render_with_template() -> None:
    config = PyOxidizerConfig(
        executable_name="my-output",
        wheels=["wheel1", "wheel2"],
        entry_point="helloworld.main",
        unclassified_resources=["resource1", "resource2"],
        template="$NAME | $WHEELS | $RUN_MODULE | $UNCLASSIFIED_RESOURCE_INSTALLATION",
    )

    rendered_config = config.render()
    assert "resolve_targets" not in rendered_config
    assert all(
        item in rendered_config
        for item in (
            "my-output",
            "wheel1",
            "wheel2",
            "helloworld.main",
            "resource1",
            "resource2",
        )
    )
