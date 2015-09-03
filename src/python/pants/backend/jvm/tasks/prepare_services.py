# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.resources_task import ResourcesTask
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.payload_field import stable_json_sha1
from pants.util.dirutil import safe_open


class JvmServiceFingerprintStrategy(DefaultFingerprintStrategy):
  """Fingerprints a JvmTarget for its service provider configuration."""

  def compute_fingerprint(self, target):
    return stable_json_sha1(target.services)


class PrepareServices(ResourcesTask):
  """Generates service provider configuration for targets that host service implementations.

  This automates maintenance of jvm service provider configuration files as described here:
  https://docs.oracle.com/javase/6/docs/api/java/util/ServiceLoader.html
  """

  @staticmethod
  def service_info_path(service):
    return os.path.join('META-INF', 'services', service)

  def find_all_relevant_resources_targets(self):
    def may_have_jvm_services(target):
      return isinstance(target, JvmTarget)
    return self.context.targets(predicate=may_have_jvm_services)

  def create_invalidation_strategy(self):
    # Service provider configuration has no dependency on target sources, deps or any other payload.
    # We just care about the services mapping.
    return JvmServiceFingerprintStrategy()

  def prepare_resources(self, target, chroot):
    for service, impls in target.services.items():
      if impls:
        service_provider_configuration_file = os.path.join(chroot, self.service_info_path(service))
        # NB: provider configuration files must be UTF-8 encoded, see the mini-spec:
        # https://docs.oracle.com/javase/6/docs/api/java/util/ServiceLoader.html
        with safe_open(service_provider_configuration_file, 'wb') as fp:
          def write_line(line):
            fp.write((line + '\n').encode('utf-8'))
          write_line('# Generated from pants target {}'.format(target.address.spec))
          for impl in impls:
            write_line(impl)

  def relative_resource_paths(self, target, chroot):
    return [self.service_info_path(service) for service, impls in target.services.items() if impls]
