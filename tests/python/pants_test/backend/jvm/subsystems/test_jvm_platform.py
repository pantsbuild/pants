# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.base.payload import Payload
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class HasRuntimePlatform(RuntimePlatformMixin, JvmTarget):

  def __init__(self, payload=None, runtime_platform=None, **kwargs):
    payload = payload or Payload()
    super(HasRuntimePlatform, self).__init__(payload=payload, runtime_platform=runtime_platform,
      **kwargs)


class JvmPlatformTest(TestBase):

  def test_runtime_lookup_both_defaults(self):
    init_subsystem(JvmPlatform, options={
      'jvm-platform': {
        'platforms': {
          'default-platform': {'target': '8'},
          'default-runtime-platform': {'target': '8'},
          'target-platform': {'target': '8'},
          'target-runtime-platform': {'target': '8'}
        },
        'default_platform': 'default-platform',
        'default_runtime_platform': 'default-runtime-platform'
      }
    })

    without_platforms = self.make_target('//:without-platforms', HasRuntimePlatform)
    just_platform = self.make_target('//:with-platform', HasRuntimePlatform,
      platform='target-platform')
    just_runtime_platform = self.make_target('//:with-runtime-platform', HasRuntimePlatform,
      runtime_platform='target-runtime-platform')
    both_platforms = self.make_target('//:with-platform-and-runtime-platform', HasRuntimePlatform,
      platform='target-platform',
      runtime_platform='target-runtime-platform')

    instance = JvmPlatform.global_instance()
    assert (instance.get_runtime_platform_for_target(without_platforms).name ==
            'default-runtime-platform')
    assert (instance.get_runtime_platform_for_target(just_platform).name ==
            'default-runtime-platform')
    assert (instance.get_runtime_platform_for_target(just_runtime_platform).name ==
            'target-runtime-platform')
    assert (instance.get_runtime_platform_for_target(both_platforms).name ==
            'target-runtime-platform')

  def test_runtime_lookup_no_default_runtime_platform(self):
    init_subsystem(JvmPlatform, options={
      'jvm-platform': {
        'platforms': {
          'default-platform': {'target': '8'},
          'default-runtime-platform': {'target': '8'},
          'target-platform': {'target': '8'},
          'target-runtime-platform': {'target': '8'}
        },
        'default_platform': 'default-platform',
        'default_runtime_platform': None
      }
    })

    without_platforms = self.make_target('//:without-platforms', HasRuntimePlatform)
    just_platform = self.make_target('//:with-platform', HasRuntimePlatform,
      platform='target-platform')
    just_runtime_platform = self.make_target('//:with-runtime-platform', HasRuntimePlatform,
      runtime_platform='target-runtime-platform')
    both_platforms = self.make_target('//:with-platform-and-runtime-platform', HasRuntimePlatform,
      platform='target-platform',
      runtime_platform='target-runtime-platform')

    instance = JvmPlatform.global_instance()
    assert (instance.get_runtime_platform_for_target(without_platforms).name ==
            'default-platform')
    assert (instance.get_runtime_platform_for_target(just_platform).name ==
            'default-platform')
    assert (instance.get_runtime_platform_for_target(just_runtime_platform).name ==
            'target-runtime-platform')
    assert (instance.get_runtime_platform_for_target(both_platforms).name ==
            'target-runtime-platform')

  def test_synthetic_target_runtime_platform_lookup(self):
    init_subsystem(JvmPlatform, options={
      'jvm-platform': {
        'platforms': {
          'default-platform': {'target': '8'},
          'default-runtime-platform': {'target': '8'},
          'target-platform': {'target': '8'},
          'target-runtime-platform': {'target': '8'},
          'parent-target-platform': {'target': '8'},
          'parent-target-runtime-platform': {'target': '8'},
        },
        'default_platform': 'default-platform',
        'default_runtime_platform': None
      }
    })

    just_platform = self.make_target('//:parent-with-runtime-platform', HasRuntimePlatform,
      platform='parent-target-platform')
    just_runtime_platform = self.make_target('//:parent-with-platform', HasRuntimePlatform,
      runtime_platform='parent-target-runtime-platform')

    synth_none = self.make_target('//:without-platforms', HasRuntimePlatform,
      synthetic=True,
      derived_from=just_runtime_platform)
    synth_just_platform = self.make_target('//:with-platform', HasRuntimePlatform,
      synthetic=True,
      derived_from=just_runtime_platform,
      platform='target-platform')
    synth_just_runtime = self.make_target('//:with-runtime-platform', HasRuntimePlatform,
      synthetic=True,
      derived_from=just_runtime_platform,
      runtime_platform='target-runtime-platform')
    synth_both = self.make_target('//:with-platform-and-runtime-platform', HasRuntimePlatform,
      synthetic=True,
      derived_from=just_runtime_platform,
      platform='target-platform',
      runtime_platform='target-runtime-platform')
    synth_just_platform_with_parent_same = self.make_target(
      '//:with-platform-and-platform-parent', HasRuntimePlatform,
      synthetic=True,
      derived_from=just_platform,
      platform='target-platform')

    instance = JvmPlatform.global_instance()
    assert (instance.get_runtime_platform_for_target(synth_none).name ==
            'parent-target-runtime-platform')
    assert (instance.get_runtime_platform_for_target(synth_just_platform).name ==
            'parent-target-runtime-platform')
    assert (instance.get_runtime_platform_for_target(synth_just_runtime).name ==
            'target-runtime-platform')
    assert (instance.get_runtime_platform_for_target(synth_both).name ==
            'target-runtime-platform')
    assert (instance.get_runtime_platform_for_target(
      synth_just_platform_with_parent_same).name == 'default-platform')
