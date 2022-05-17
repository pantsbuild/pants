# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest

from pants.backend.helm.resolve.remotes import (
    ALL_DEFAULT_HELM_REGISTRIES,
    HelmRegistry,
    HelmRemoteAliasNotFoundError,
    HelmRemotes,
)


def test_helm_remotes() -> None:
    remotes = HelmRemotes.from_dict(
        {
            "reg1": {"address": "oci://www.example.com"},
            "reg2": {"address": "oci://www.example.com/subfolder"},
        },
    )

    assert remotes.default == ()
    assert list(remotes.get()) == []
    assert len(list(remotes.get("@reg1"))) == 1
    assert len(list(remotes.get("@reg1", "@reg2"))) == 2
    assert next(remotes.get("@reg1")).address == "oci://www.example.com"
    assert next(remotes.get("@reg2")).address == "oci://www.example.com/subfolder"

    with pytest.raises(HelmRemoteAliasNotFoundError):
        list(remotes.get("@reg3"))

    assert list(remotes.get("oci://www.example.com/charts")) == [
        HelmRegistry(address="oci://www.example.com/charts")
    ]

    # Test defaults.
    remotes = HelmRemotes.from_dict(
        {
            "default": {"address": "oci://www.example.com/default"},
            "reg1": {"address": "oci://www.example.com/charts1", "default": "false"},
            "reg2": {"address": "oci://www.example.com/charts2", "default": "true"},
            "reg3": {"address": "oci://www.example.com/charts3", "default": "true"},
        },
    )

    assert next(remotes.get("@reg2")).default is True
    assert [r.address for r in remotes.default] == [
        "oci://www.example.com/charts2",
        "oci://www.example.com/charts3",
        "oci://www.example.com/default",
    ]

    assert [r.alias for r in remotes.get(ALL_DEFAULT_HELM_REGISTRIES)] == [
        "reg2",
        "reg3",
        "default",
    ]
