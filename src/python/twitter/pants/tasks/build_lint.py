# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================
import os

__author__ = 'Benjy Weinberger'

import difflib
import re

from collections import defaultdict

from twitter.pants.tasks import Task


class BuildLint(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    Task.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
      dest="buildlint_transitive", default=False,
      action="callback", callback=mkflag.set_bool,
      help="[%default] apply lint rules transitively to all dependency buildfiles.")

    option_group.add_option(mkflag("include-intransitive-deps"),
      mkflag("include-intransitive-deps", negate=True),
      dest="buildlint_include_intransitive", default=False,
      action="callback", callback=mkflag.set_bool,
      help="[%default] correct both simple missing dependencies and intransitive missing deps")


    option_group.add_option(mkflag("action"), dest="buildlint_actions", default=[],
      action="append", type="choice", choices=['diff', 'rewrite'],
      help="diff=print out diffs, rewrite=apply changes to BUILD files directly.")

  def __init__(self, context):
    Task.__init__(self, context)
    context.products.require('missing_deps')
    self.transitive = context.options.buildlint_transitive
    self.actions = set(context.options.buildlint_actions)
    self.include_intransitive = context.options.buildlint_include_intransitive
    # Manually apply the default. Can't use flag default, because action is 'append', so
    # diffs would always be printed, even if we only wanted to rewrite.
    if not self.actions:
      self.actions.add('diff')

  def execute(self, targets):
    # Map from buildfile path to map of target name -> missing deps for that target.
    buildfile_paths = defaultdict(lambda: defaultdict(list))
    genmap_trans = self.context.products.get('missing_deps')
    genmap_intrans = self.context.products.get('missing_intransitive_deps')

    def add_buildfile_for_target(target, genmap):
      missing_dep_map = genmap[target]
      missing_deps = missing_dep_map[self.context._buildroot] if missing_dep_map else defaultdict(list)
      buildfile_paths[target.address.buildfile.full_path][target.name] += missing_deps

    if self.transitive:
      for target in targets:
        add_buildfile_for_target(target, genmap_trans)
        if self.include_intransitive:
          add_buildfile_for_target(target, genmap_intrans)
    else:
      for target in self.context.target_roots:
        add_buildfile_for_target(target, genmap_trans)
        if self.include_intransitive:
          add_buildfile_for_target(target, genmap_intrans)

    for buildfile_path, missing_dep_map in buildfile_paths.items():
      self._fix_lint(buildfile_path, missing_dep_map)


  # We use heuristics to find target names and their list of dependencies.
  # Attempts to use the Python AST proved to be extremely complex and not worth the trouble.
  NAMES_RE = re.compile('^\w+\(\s*name\s*=\s*["\']((?:\w|-)+)["\']', flags=re.DOTALL|re.MULTILINE)
  DEPS_RE = re.compile(r'^\s*dependencies\s*=\s*\[([^\]]*)\s*\]', flags=re.DOTALL|re.MULTILINE)
  INLINE_SINGLE_DEP_RE = re.compile(r'^ *dependencies *= *\[[^\n,\]]* *\]')

  def _fix_lint(self, buildfile_path, missing_dep_map):
    if os.path.exists(buildfile_path):
      with open(buildfile_path, 'r') as infile:
        old_buildfile_source = infile.read()
      names = []
      for m in BuildLint.NAMES_RE.finditer(old_buildfile_source):
        names.append(m.group(1))

      # We'll step through this to find the name of the target whose deps we're currently looking at.
      nameiter = iter(names)

      def sort_deps(m):
        try:
          name = nameiter.next()
        except StopIteration:
          name = '-UNKNOWN-'
        deps = m.group(1).split('\n')
        deps = filter(lambda x: x, [x.strip().replace('"', "'") for x in deps])
        missing_deps = ["'%s'," % x for x in missing_dep_map[name]]
        deps.extend(missing_deps)
        if deps:  # Add comma if needed. We must do this before sorting.
          # Allow a single dep on a single line, if that's what the file already had.
          # This is common in 3rdparty/BUILD files.
          if len(deps) == 1 and BuildLint.INLINE_SINGLE_DEP_RE.match(m.group(0)):
            return '  dependencies = [%s]' % deps[0]
          parts = [x.strip() for x in deps[-1].split('#')]
          if not parts[0].rstrip().endswith(','):
            deps[-1] = '%s,%s' % (parts[0], ' #' + parts[1] if len(parts) > 1 else '')

        # The key hack is to make sure local imports (those starting with a colon) come last.
        deps = sorted(deps, key=lambda x: 'zzz' + x if (x.startswith("':") or x.startswith("pants(':")) else x)
        res = '  dependencies = [\n    %s\n  ]' % ('\n    '.join(deps)) if deps else 'dependencies = []'
        return res

      new_buildfile_source = BuildLint.DEPS_RE.sub(sort_deps, old_buildfile_source)
      if new_buildfile_source != old_buildfile_source:
        if 'rewrite' in self.actions:
          with open(buildfile_path, 'w') as outfile:
            outfile.write(new_buildfile_source)
        if 'diff' in self.actions:
          diff = '\n'.join(difflib.unified_diff(old_buildfile_source.split('\n'),
            new_buildfile_source.split('\n'), buildfile_path))
          print(diff)
