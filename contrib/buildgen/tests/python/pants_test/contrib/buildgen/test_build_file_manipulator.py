# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.build_graph.address import Address
from pants_test.base_test import BaseTest

from pants.contrib.buildgen.build_file_manipulator import (BuildFileManipulator,
                                                           BuildTargetParseError)


class BuildFileManipulatorTest(BaseTest):

  def setUp(self):
    super(BuildFileManipulatorTest, self).setUp()
    self.complicated_dep_comments = dedent(
      """\
      target_type(
        # This comment should be okay
        name = 'no_bg_no_cry',  # Side comments here will stay
        # This comment should be okay
        dependencies = [
          # nbgbc_above1
          # nbgnc_above2
          'really/need/this:dep', #nobgnc_side

          ':whitespace_above',
          ':only_side',#only_side
          #only_above
          ':only_above'
        ],
        # This comment is also fine
        thing = object()
        # And finally this comment survives
      )"""
    )

    self.multi_target_build_string = dedent(
      """\
      # This comment should stay
      target_type(
        name = 'target_top',
        dependencies = [
          ':dep_a',
        ]
      )



      target_type(
        name = 'target_middle',
        dependencies = [
          ':dep_b',
        ]
      )
      # This comment should be okay
      target_type(
        name = 'target_bottom',
      )
      # Also this one though it's weird"""
    )

  def test_malformed_targets(self):
    bad_targets = dedent(
      """
      target_type(name='name_on_line')

      target_type(
        name=
        'dangling_kwarg_value'
      )

      # TODO(pl):  Split this out.  Right now it fails
      # the test for all of the targets and masks other
      # expected failures
      # target_type(
      #   name=str('non_str_literal')
      # )

      target_type(
        name='end_paren_not_on_own_line')

      target_type(
        object(),
        name='has_non_kwarg'
      )

      target_type(
        name='non_list_deps',
        dependencies=object(),
      )

      target_type(
        name='deps_not_on_own_lines1',
        dependencies=['some_dep'],
      )

      target_type(
        name='deps_not_on_own_lines2',
        dependencies=[
          'some_dep', 'some_other_dep'],
      )

      target_type(
        name = 'sentinel',
      )
      """
    )

    build_file = self.add_to_build_file('BUILD', bad_targets)

    bad_target_names = [
      'name_on_line',
      'dangling_kwarg_value',
      # TODO(pl): See TODO above
      # 'non_str_literal',
      'end_paren_not_on_own_line',
      'name_not_in_build_file',
      'has_non_kwarg',
      'non_list_deps',
    ]
    # Make sure this exception isn't just being thrown no matter what.
    # TODO(pl): These exception types should be more granular.
    BuildFileManipulator.load(build_file, 'sentinel', set(['target_type']))
    for bad_target in bad_target_names:
      with self.assertRaises(BuildTargetParseError):
        BuildFileManipulator.load(build_file, bad_target, set(['target_type']))

  def test_simple_targets(self):
    simple_targets = dedent(
      """
      target_type(
        name = 'no_deps',
      )

      target_type(
        name = 'empty_deps',
        dependencies = [
        ]
      )

      target_type(
        name = 'empty_deps_inline',
        dependencies = []
      )
      """
    )

    build_file = self.add_to_build_file('BUILD', simple_targets)

    for no_deps_name in ['no_deps', 'empty_deps', 'empty_deps_inline']:
      no_deps = BuildFileManipulator.load(build_file, no_deps_name, {'target_type'})
      self.assertEqual(tuple(no_deps.dependency_lines()), tuple())
      no_deps.add_dependency(Address.parse(':fake_dep'))
      self.assertEqual(tuple(no_deps.dependency_lines()),
                       tuple(['  dependencies = [',
                              "    ':fake_dep',",
                              '  ],']))
      no_deps.add_dependency(Address.parse(':b_fake_dep'))
      no_deps.add_dependency(Address.parse(':a_fake_dep'))
      self.assertEqual(tuple(no_deps.dependency_lines()),
                       tuple(['  dependencies = [',
                              "    ':a_fake_dep',",
                              "    ':b_fake_dep',",
                              "    ':fake_dep',",
                              '  ],']))
      self.assertEqual(tuple(no_deps.target_lines()),
                       tuple(['target_type(',
                              "  name = '{0}',".format(no_deps_name),
                              '  dependencies = [',
                              "    ':a_fake_dep',",
                              "    ':b_fake_dep',",
                              "    ':fake_dep',",
                              '  ],',
                              ')']))

  def test_comment_rules(self):
    expected_target_str = dedent(
      """\
      target_type(
        # This comment should be okay
        name = 'no_bg_no_cry',  # Side comments here will stay
        # This comment should be okay
        dependencies = [
          # only_above
          ':only_above',
          ':only_side',  # only_side

          ':whitespace_above',
          # nbgbc_above1
          # nbgnc_above2
          'really/need/this:dep',  # nobgnc_side
        ],
        # This comment is also fine
        thing = object()
        # And finally this comment survives
      )"""
    )

    build_file = self.add_to_build_file('BUILD', self.complicated_dep_comments)

    complicated_bfm = BuildFileManipulator.load(build_file, 'no_bg_no_cry', set(['target_type']))
    target_str = '\n'.join(complicated_bfm.target_lines())
    self.assertEqual(target_str, expected_target_str)

  def test_forced_target_rules(self):
    expected_target_str = dedent(
      """\
      target_type(
        # This comment should be okay
        name = 'no_bg_no_cry',  # Side comments here will stay
        # This comment should be okay
        dependencies = [
          # only_above
          ':only_above',
          ':only_side',  # only_side
          # nbgbc_above1
          # nbgnc_above2
          'really/need/this:dep',  # nobgnc_side
        ],
        # This comment is also fine
        thing = object()
        # And finally this comment survives
      )"""
    )

    build_file = self.add_to_build_file('BUILD', self.complicated_dep_comments)

    complicated_bfm = BuildFileManipulator.load(build_file, 'no_bg_no_cry', set(['target_type']))
    complicated_bfm.clear_unforced_dependencies()
    target_str = '\n'.join(complicated_bfm.target_lines())
    self.assertEqual(target_str, expected_target_str)

  def test_target_insertion_bottom(self):
    expected_build_string = dedent(
      """\
      # This comment should stay
      target_type(
        name = 'target_top',
        dependencies = [
          ':dep_a',
        ]
      )



      target_type(
        name = 'target_middle',
        dependencies = [
          ':dep_b',
        ]
      )
      # This comment should be okay
      target_type(
        name = 'target_bottom',
        dependencies = [
          ':new_dep',
        ],
      )
      # Also this one though it's weird"""
    )

    build_file = self.add_to_build_file('BUILD', self.multi_target_build_string)

    multi_targ_bfm = BuildFileManipulator.load(build_file, 'target_bottom', {'target_type'})
    multi_targ_bfm.add_dependency(Address.parse(':new_dep'))
    build_file_str = '\n'.join(multi_targ_bfm.build_file_lines())
    self.assertEqual(build_file_str, expected_build_string)

  def test_target_insertion_top(self):
    expected_build_string = dedent(
      """\
      # This comment should stay
      target_type(
        name = 'target_top',
        dependencies = [
          ':dep_a',
          ':new_dep',
        ],
      )



      target_type(
        name = 'target_middle',
        dependencies = [
          ':dep_b',
        ]
      )
      # This comment should be okay
      target_type(
        name = 'target_bottom',
      )
      # Also this one though it's weird"""
    )

    build_file = self.add_to_build_file('BUILD', self.multi_target_build_string)

    multi_targ_bfm = BuildFileManipulator.load(build_file, 'target_top', {'target_type'})
    multi_targ_bfm.add_dependency(Address.parse(':new_dep'))
    build_file_str = '\n'.join(multi_targ_bfm.build_file_lines())
    self.assertEqual(build_file_str, expected_build_string)

  def test_target_insertion_middle(self):
    expected_build_string = dedent(
      """\
      # This comment should stay
      target_type(
        name = 'target_top',
        dependencies = [
          ':dep_a',
        ]
      )



      target_type(
        name = 'target_middle',
        dependencies = [
          ':dep_b',
          ':new_dep',
        ],
      )
      # This comment should be okay
      target_type(
        name = 'target_bottom',
      )
      # Also this one though it's weird"""
    )

    build_file = self.add_to_build_file('BUILD', self.multi_target_build_string)

    multi_targ_bfm = BuildFileManipulator.load(build_file, 'target_middle', {'target_type'})
    multi_targ_bfm.add_dependency(Address.parse(':new_dep'))
    build_file_str = '\n'.join(multi_targ_bfm.build_file_lines())
    self.assertEqual(build_file_str, expected_build_string)

  def test_target_write(self):
    expected_build_string = dedent(
      """\
      # This comment should stay
      target_type(
        name = 'target_top',
        dependencies = [
          ':dep_a',
        ]
      )



      target_type(
        name = 'target_middle',
        dependencies = [
          ':dep_b',
          ':new_dep',
        ],
      )
      # This comment should be okay
      target_type(
        name = 'target_bottom',
      )
      # Also this one though it's weird
      """
    )

    build_file = self.add_to_build_file('BUILD', self.multi_target_build_string + '\n')

    multi_targ_bfm = BuildFileManipulator.load(build_file, 'target_middle', {'target_type'})
    multi_targ_bfm.add_dependency(Address.parse(':new_dep'))
    multi_targ_bfm.write(dry_run=False)

    with open(build_file.full_path, 'r') as bf:
      self.assertEqual(bf.read(), expected_build_string)
