# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.base.specs import (
    FilesystemGlobSpec,
    FilesystemLiteralSpec,
    FilesystemMergedSpec,
    FilesystemResolvedGlobSpec,
    FilesystemSpecs,
    SingleAddress,
)
from pants.engine.addresses import Address, Addresses, AddressesWithOrigins, AddressWithOrigin
from pants.engine.fs import SourcesSnapshot
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Sources,
    Target,
    Targets,
    TransitiveTarget,
    TransitiveTargets,
    WrappedTarget,
)
from pants.init.specs_calculator import SpecsCalculator
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import FrozenOrderedSet


class MockTarget(Target):
    alias = "target"
    core_fields = (Dependencies, Sources)


class GraphTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            RootRule(Addresses),
            RootRule(WrappedTarget),
            RootRule(FilesystemSpecs),
        )

    @classmethod
    def target_types(cls):
        return (MockTarget,)

    def test_transitive_targets(self) -> None:
        self.add_to_build_file(
            "",
            dedent(
                """\
                target(name='t1')
                target(name='t2', dependencies=[':t1'])
                target(name='d1', dependencies=[':t1'])
                target(name='d2', dependencies=[':t2'])
                target(name='d3')
                target(name='root', dependencies=[':d1', ':d2', ':d3'])
                """
            ),
        )

        def get_target(name: str) -> Target:
            return self.request_single_product(WrappedTarget, Address.parse(f"//:{name}")).target

        t1 = get_target("t1")
        t2 = get_target("t2")
        d1 = get_target("d1")
        d2 = get_target("d2")
        d3 = get_target("d3")
        root = get_target("root")

        direct_deps = self.request_single_product(
            Targets, Params(DependenciesRequest(root[Dependencies]), create_options_bootstrapper())
        )
        assert direct_deps == Targets([d1, d2, d3])

        transitive_target = self.request_single_product(
            TransitiveTarget, Params(WrappedTarget(root), create_options_bootstrapper())
        )
        assert transitive_target.root == root
        assert {
            dep_transitive_target.root for dep_transitive_target in transitive_target.dependencies
        } == {d1, d2, d3}

        transitive_targets = self.request_single_product(
            TransitiveTargets,
            Params(Addresses([root.address, d2.address]), create_options_bootstrapper()),
        )
        assert transitive_targets.roots == (root, d2)
        # NB: `//:d2` is both a target root and a dependency of `//:root`.
        assert transitive_targets.dependencies == FrozenOrderedSet([d1, d2, d3, t2, t1])
        assert transitive_targets.closure == FrozenOrderedSet([root, d2, d1, d3, t2, t1])

    def test_resolve_generated_subtarget(self) -> None:
        self.add_to_build_file("demo", "target(sources=['f1.txt', 'f2.txt'])")
        generated_target_addresss = Address(
            "demo", target_name="f1.txt", generated_base_target_name="demo"
        )
        generated_target = self.request_single_product(
            WrappedTarget, generated_target_addresss
        ).target
        assert generated_target == MockTarget(
            {Sources.alias: ["f1.txt"]}, address=generated_target_addresss
        )

    def test_resolve_sources_snapshot(self) -> None:
        """This tests that convert filesystem specs and/or address specs into a single snapshot.

        Some important edge cases:
        - When a filesystem spec refers to a file without any owning target, it should be included
          in the snapshot.
        - If a file is covered both by an address spec and by a filesystem spec, we should merge it
          so that the file only shows up once.
        """
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        specs = SpecsCalculator.parse_specs(["demo:demo", "demo/f1.txt", "demo/BUILD"])
        result = self.request_single_product(
            SourcesSnapshot, Params(specs, create_options_bootstrapper())
        )
        assert result.snapshot.files == ("demo/BUILD", "demo/f1.txt", "demo/f2.txt")

    def test_owners_source_file_does_not_exist(self) -> None:
        """Test when a source file belongs to a target, even though the file does not actually
        exist.

        This happens, for example, when the file is deleted and we're computing `--changed-since`.
        In this case, we should not attempt to generate a subtarget and should use the original
        target.
        """
        self.create_file("demo/f.txt")
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        result = self.request_single_product(Owners, OwnersRequest(("demo/deleted.txt",)))
        assert result == Owners([Address("demo", "demo")])
        # For files that do exist, we should still use a generated subtarget, though.
        result = self.request_single_product(Owners, OwnersRequest(("demo/f.txt",)))
        assert result == Owners(
            [Address("demo", target_name="f.txt", generated_base_target_name="demo")]
        )
        # However, if a sibling file must use the original target, then we should always use
        # the original target to avoid redundancy.
        result = self.request_single_product(
            Owners, OwnersRequest(("demo/f.txt", "demo/deleted.txt"))
        )
        assert result == Owners([Address("demo", "demo")])

    def test_owners_multiple_owners(self) -> None:
        """This tests that we do not use generated subtargets when there are multiple owners.

        There are two edge cases:
        - There are two owners of the file in question.
        - The file in question only has one owner, but its sibling from the same target does have
          >1 owner. In this case, we use the original owning target because it would be
          redundant to include the generated subtarget.
        """
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file(
            "demo",
            dedent(
                """\
                target(name='all', sources=['*.txt'])
                target(name='f2', sources=['f2.txt'])
                """
            ),
        )

        one_owner_result = self.request_single_product(Owners, OwnersRequest(("demo/f1.txt",)))
        assert one_owner_result == Owners(
            [Address("demo", target_name="f1.txt", generated_base_target_name="all")]
        )

        two_owners_result = self.request_single_product(Owners, OwnersRequest(("demo/f2.txt",)))
        assert two_owners_result == Owners([Address("demo", "f2"), Address("demo", "all")])

        sibling_has_two_owners_result = self.request_single_product(
            Owners, OwnersRequest(("demo/f1.txt", "demo/f2.txt"))
        )
        assert sibling_has_two_owners_result == Owners(
            [Address("demo", "f2"), Address("demo", "all")]
        )

    def test_filesystem_specs_literal_file(self) -> None:
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        spec = FilesystemLiteralSpec("demo/f1.txt")
        result = self.request_single_product(
            AddressesWithOrigins, Params(FilesystemSpecs([spec]), create_options_bootstrapper())
        )
        assert len(result) == 1
        assert result[0] == AddressWithOrigin(
            Address("demo", target_name="f1.txt", generated_base_target_name="demo"), origin=spec
        )

    def test_filesystem_specs_glob(self) -> None:
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        result = self.request_single_product(
            AddressesWithOrigins,
            Params(
                FilesystemSpecs([FilesystemGlobSpec("demo/*.txt")]), create_options_bootstrapper()
            ),
        )
        expected_origin = FilesystemResolvedGlobSpec(
            glob="demo/*.txt", files=("demo/f1.txt", "demo/f2.txt")
        )
        assert result == AddressesWithOrigins(
            [
                AddressWithOrigin(
                    Address("demo", target_name="f1.txt", generated_base_target_name="demo"),
                    origin=expected_origin,
                ),
                AddressWithOrigin(
                    Address("demo", target_name="f2.txt", generated_base_target_name="demo"),
                    origin=expected_origin,
                ),
            ]
        )

    def test_filesystem_specs_merge_when_same_address(self) -> None:
        """Test that two filesystem specs resulting in the same address will merge into one result.

        This is a tricky edge case to trigger. First, we must be using the original owning targets,
        rather than generated subtargets, which means that there must be multiple owning targets.
        Then, we must have two specs that resulted in the same original address.
        """
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file(
            "demo",
            dedent(
                """\
                target(name='one', sources=['*.txt'])
                target(name='two', sources=['*.txt'])
                """
            ),
        )
        specs = [FilesystemLiteralSpec("demo/f1.txt"), FilesystemLiteralSpec("demo/f2.txt")]
        result = self.request_single_product(
            AddressesWithOrigins, Params(FilesystemSpecs(specs), create_options_bootstrapper())
        )
        expected_origin = FilesystemMergedSpec.create(specs)
        assert result == AddressesWithOrigins(
            [
                AddressWithOrigin(Address("demo", "two"), expected_origin),
                AddressWithOrigin(Address("demo", "one"), expected_origin),
            ]
        )

    def test_filesystem_specs_nonexistent_file(self) -> None:
        specs = FilesystemSpecs([FilesystemLiteralSpec("demo/fake.txt")])
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(
                AddressesWithOrigins, Params(specs, create_options_bootstrapper()),
            )
        assert 'Unmatched glob from file arguments: "demo/fake.txt"' in str(exc.value)
        ignore_errors_result = self.request_single_product(
            AddressesWithOrigins,
            Params(specs, create_options_bootstrapper(args=["--owners-not-found-behavior=ignore"])),
        )
        assert not ignore_errors_result

    def test_filesystem_specs_no_owner(self) -> None:
        self.create_file("no_owners/f.txt")
        # Error for literal specs.
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(
                AddressesWithOrigins,
                Params(
                    FilesystemSpecs([FilesystemLiteralSpec("no_owners/f.txt")]),
                    create_options_bootstrapper(),
                ),
            )
        assert "No owning targets could be found for the file `no_owners/f.txt`" in str(exc.value)

        # Do not error for glob specs.
        glob_file_result = self.request_single_product(
            AddressesWithOrigins,
            Params(
                FilesystemSpecs([FilesystemGlobSpec("no_owners/*.txt")]),
                create_options_bootstrapper(),
            ),
        )
        assert not glob_file_result

    def test_resolve_addresses(self) -> None:
        """This tests that we correctly merge addresses resolved from address specs with those
        resolved from filesystem specs.

        Some important edge cases:
        - If a filesystem spec resulted in a normal target, and that target is already in the
          address specs, then we should deduplicate to only use the target one time.
        - If a filesystem spec resulted in a generated subtarget, and that subtarget is generated
          from an original target that is already in the address specs, then we should not use the
          generated subtarget.
        """
        self.create_file("fs_spec/f.txt")
        self.add_to_build_file("fs_spec", "target(sources=['f.txt'])")
        self.create_file("address_spec/f.txt")
        self.add_to_build_file("address_spec", "target(sources=['f.txt'])")
        no_interaction_specs = ["fs_spec/f.txt", "address_spec:address_spec"]

        # Because there are two owners, using a filesystem spec on this should result in both
        # original targets being used, rather than generated subtargets. If we also use an address
        # spec on one of those two owners, then we should properly dedupe with the filesystem spec
        # result.
        self.create_file("two_owners/f.txt")
        self.add_to_build_file(
            "two_owners",
            dedent(
                """\
                target(name='one', sources=['f.txt'])
                target(name='two', sources=['f.txt'])
                """
            ),
        )
        two_owners_specs = ["two_owners/f.txt", "two_owners:one"]

        # If a generated subtarget's original base target is already included via an address spec,
        # then we should not include the generated subtarget because it would be redundant.
        self.create_files("multiple_files", ["f1.txt", "f2.txt"])
        self.add_to_build_file("multiple_files", "target(sources=['*.txt'])")
        multiple_files_specs = ["multiple_files/f2.txt", "multiple_files:multiple_files"]

        specs = SpecsCalculator.parse_specs(
            [*no_interaction_specs, *two_owners_specs, *multiple_files_specs]
        )
        result = self.request_single_product(
            AddressesWithOrigins, Params(specs, create_options_bootstrapper())
        )
        assert set(result) == {
            AddressWithOrigin(
                Address("fs_spec", target_name="f.txt", generated_base_target_name="fs_spec"),
                origin=FilesystemLiteralSpec("fs_spec/f.txt"),
            ),
            AddressWithOrigin(
                Address("address_spec", "address_spec"),
                origin=SingleAddress("address_spec", "address_spec"),
            ),
            AddressWithOrigin(
                Address("two_owners", "one"), origin=SingleAddress("two_owners", "one")
            ),
            AddressWithOrigin(
                Address("two_owners", "two"), origin=FilesystemLiteralSpec("two_owners/f.txt"),
            ),
            AddressWithOrigin(
                Address("multiple_files", "multiple_files"),
                origin=SingleAddress("multiple_files", "multiple_files"),
            ),
        }
