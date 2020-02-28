# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.base.build_file import BuildFile
from pants.base.exceptions import ResolveError
from pants.base.specs import AddressSpecs, DescendantAddresses, SiblingAddresses
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.address_mapper import AddressMapper
from pants.engine.addressable import BuildFileAddresses
from pants.util.dirutil import fast_relpath

logger = logging.getLogger(__name__)


class LegacyAddressMapper(AddressMapper):
    """Provides an implementation of AddressMapper using v2 engine.

    This allows tasks to use the context's address_mapper when the v2 engine is enabled.
    """

    def __init__(self, scheduler, build_root):
        self._scheduler = scheduler
        self._build_root = build_root

    def scan_build_files(self, base_path):
        build_file_addresses = self._internal_scan_specs(
            [DescendantAddresses(base_path)], missing_is_fatal=False
        )

        return {bfa.rel_path for bfa in build_file_addresses}

    @staticmethod
    def any_is_declaring_file(address, file_paths):
        try:
            # A precise check for BuildFileAddress
            return address.rel_path in file_paths
        except AttributeError:
            pass
        # NB: this will cause any BUILD file, whether it contains the address declaration or not to be
        # considered the one that declared it. That's ok though, because the spec path should be enough
        # information for debugging most of the time.
        return any(
            address.spec_path == os.path.dirname(fp)
            for fp in file_paths
            if BuildFile._is_buildfile_name(os.path.basename(fp))
        )

    @staticmethod
    def is_declaring_file(address, file_path):
        return LegacyAddressMapper.any_is_declaring_file(address, [file_path])

    def addresses_in_spec_path(self, spec_path):
        return self.scan_address_specs([SiblingAddresses(spec_path)])

    def scan_address_specs(self, specs, fail_fast=True):
        return self._internal_scan_specs(specs, fail_fast=fail_fast, missing_is_fatal=True)

    def _specs_string(self, specs):
        return ", ".join(s.to_spec_string() for s in specs)

    def _internal_scan_specs(self, specs, fail_fast=True, missing_is_fatal=True):
        # TODO: This should really use `product_request`, but on the other hand, we need to
        # deprecate the entire `AddressMapper` interface anyway. See #4769.
        request = self._scheduler.execution_request(
            [BuildFileAddresses], [AddressSpecs(tuple(specs))]
        )
        returns, throws = self._scheduler.execute(request)

        if throws:
            _, state = throws[0]
            if isinstance(state.exc, (AddressLookupError, ResolveError)):
                if missing_is_fatal:
                    raise self.BuildFileScanError(
                        "AddressSpec `{}` does not match any targets.\n{}".format(
                            self._specs_string(specs), str(state.exc)
                        )
                    )
                else:
                    # NB: ignore Throws containing ResolveErrors because they are due to missing targets / files
                    return set()
            else:
                raise self.BuildFileScanError(str(state.exc))

        _, state = returns[0]
        if missing_is_fatal and not state.value.dependencies:
            raise self.BuildFileScanError(
                "AddressSpec `{}` does not match any targets.".format(self._specs_string(specs))
            )

        return set(state.value.dependencies)

    def scan_addresses(self, root=None):
        if root:
            try:
                base_path = fast_relpath(root, self._build_root)
            except ValueError as e:
                raise self.InvalidRootError(e)
        else:
            base_path = ""

        return self._internal_scan_specs([DescendantAddresses(base_path)], missing_is_fatal=False)
