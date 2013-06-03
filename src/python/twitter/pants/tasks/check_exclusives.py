__author__ = 'Mark Chu-Carroll (markcc@foursquare.com)'


from collections import defaultdict
from copy import copy
from itertools import chain
import string
from twitter.pants.tasks import Task, TaskError
from twitter.pants.targets import InternalTarget


class CheckExclusives(Task):
  """Task for computing transitive exclusive maps.

  This computes transitive exclusive tags for a dependency graph rooted
  with a set of build targets specified by a user. If this process produces
  any collisions where a single target contains multiple tag values for a single
  exclusives key, then it generates an error and the compilation will fail.

  The syntax of the exclusives attribute is:
      exclusives = {"id": "value", ...}

  For example, suppose that we had two java targets, jliba and jlibb,
  which used different versions of joda datetime.

    java_library(name='jliba',
       depedencies = ['joda-1.5'])
    java_library(name='jlibb',
       dependencies=['joda-2.1'])
    java_binary(name='javabin', dependencies=[':jliba', ':jlibb'])

  In this case, the binary target 'javabin' depends on both joda-1.5 and joda-2.1.
  This should be a build error, but pants doesn't know that joda-1.5 and joda-2.1 are
  different versions of the same library, and so it can't detect the error.

  With exclusives, the jar_library target for the joda libraries would declare
  exclusives tags:

    jar_library(name='joda-1.5', exclusives={'joda': '1.5'})
    jar_library(name='joda-2.1', exclusives={'joda': '2.1'})

  With the exclusives declared, pants can recognize that 'javabin' has conflicting
  dependencies, and can generate an appropriate error message.

  If the build product exclusives_partitions is required, then a map
  from exclusives keys to partitions of compatible exclusives will be
  generated.
  """


  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    Task.setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag('error_on_collision'),
                            mkflag('error_on_collision', negate=True),
                            dest='exclusives_error_on_collision', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help=("[%default] Signal an error and abort the build if an " +
                                  "exclusives collision is detected"))

  def __init__(self, context, signal_error=None):
    Task.__init__(self, context)
    self.signal_error = (context.options.exclusives_error_on_collision
                         if signal_error is None else signal_error)

  def _compute_exclusives_conflicts(self, targets):
    """Compute the set of distinct chunks of targets that are required based on exclusives.
    If two targets have different values for a particular exclusives tag,
    then those targets must end up in different chunks.
    This method computes the exclusives values that define each chunk.
    e.g.: if target a has exclusives {"x": "1", "z": "1"}, target b has {"x": "2"},
    target c has {"y", "1"}, and target d has {"y", "2", "z": "1"}, then we need to
    divide into chunks on exclusives tags "x" and "y". We don't need to include
    "z" in the chunk specification, because there are no conflicts on z.

    Parameters:
      targets: a list of the targets being built.
    Return: the set of exclusives tags that should be used for chunking.
    """
    exclusives_map = defaultdict(set)
    for t in targets:
      if t.exclusives is not None:
        for k in t.exclusives:
          exclusives_map[k] |= t.exclusives[k]
    conflicting_keys = defaultdict(set)
    for k in exclusives_map:
      if len(exclusives_map[k]) > 1:
        conflicting_keys[k] = exclusives_map[k]
    return conflicting_keys

  def execute(self, targets):
    # compute transitive exclusives
    for t in targets:
      t._propagate_exclusives()
    # Check for exclusives collision.
    for t in targets:
      excl = t.get_all_exclusives()
      for key in excl:
        if len(excl[key]) > 1:
          msg = 'target %s has more than 1 exclusives tag for key %s: %s' % (t, key, excl)
          if self.signal_error:
            raise TaskError(msg)
          else:
            print "Warning: %s" % msg
    if self.context.products.is_required_data('exclusives_groups'):
      mapping = ExclusivesMapping()
      partition_keys = self._compute_exclusives_conflicts(targets)
      for key in partition_keys:
        mapping.add_conflict(key, partition_keys[key])
      mapping._populate_target_maps(targets)
      self.context.products.add_data('exclusives_groups', mapping)

class ExclusivesMapping(object):
  def __init__(self):
    self.conflicting_exclusives = {}
    self.key_to_targets = defaultdict(set)
    self.target_to_key = {}
    self.ordering = None
    self.group_classpaths = {}

  def add_conflict(self, key, values):
    self.conflicting_exclusives[key] = values

  def get_targets_for_group_key(self, key):
    return self.key_to_targets[key]

  def get_group_key_for_target(self, target):
    return self.target_to_key[target]

  def get_group_keys(self):
    if len(self.conflicting_exclusives) == 0:
      return ["<none>"]
    else:
      return self.key_to_targets.keys()

  def get_ordered_group_keys(self):
    # Compute the correct order in which to compile groups.
    # For compilation to work correctly, things must be compiled in dependency order.
    # That ordering is enforced in several stages:
    # - goal execution ordering: a goal is invoked on sets of targets, after the goals it depends on.
    # - group chunk ordering:  Group divides targets into groups (terrible terminology there), which
    #     are compiled in dependency ordering.
    # - compilation partition ordering: compiler tasks can subdivide compilation into
    #   sub-group partitions, which are compiled in dependency ordering.
    #
    # In group, we already do group-based ordering. But that ordering is done separately on
    # each exclusives group. If we have a grouping:
    # a(exclusives={x: 1, y:2}, dependencies=[ ':b', ':c' ])
    # b(exclusives={x:"<none>", y: "<none>"}, dependencies=[])
    # c(exclusives={x:<none>, y:2}, dependencies=[':b'])
    #
    # If we were to do grouping in the exclusives ordering {x:<none>, y:2}, {x: <none>, y:<none>},
    #  {x:1, y:2}, then we'd be compiling the group containing c before the group containing b; but
    # c depends on b.
    def number_of_emptys(key):
      return string.count(key, "<none>")

    if self.ordering is not None:
      return self.ordering
    # The correct order is from least exclusives to most exclusives - a target can only depend on
    # other targets with fewer exclusives than itself.
    keys_by_empties = [ [] for l in range(len(self.key_to_targets)) ]
    for k in self.key_to_targets:
      keys_by_empties[number_of_emptys(k)].append(k)
    result = []
    for i in range(len(keys_by_empties)):
      for j in range(len(keys_by_empties[i])):

        result.append(keys_by_empties[i][j])
    result.reverse()
    self.ordering = result
    return self.ordering


  def _get_exclusives_key(self, target):
    # compute an exclusives group key: a list of the exclusives values for the keys
    # in the conflicting keys list.
    target_key = []
    for k in self.conflicting_exclusives:
      if len(target.exclusives[k]) > 0:
        target_key.append("%s=%s" % (k, list(target.exclusives[k])[0]))
      else:
        target_key.append("%s=<none>" % k)
    if target_key == []:
      return "<none>"
    else:
      return ','.join(target_key)

  def _populate_target_maps(self, targets):
    all_targets = []
    workqueue = copy(targets)
    while len(workqueue) > 0:
      t = workqueue.pop()
      if t not in all_targets:
        all_targets.append(t)
        if isinstance(t, InternalTarget):
          workqueue += t.dependencies

    for t in all_targets:
      key = self._get_exclusives_key(t)
      if key not in self.group_classpaths:
        self.group_classpaths[key] = []
      self.key_to_targets[key].add(t)
      self.target_to_key[t] = key

  def get_classpath_for_group(self, group_key):
    if group_key not in self.group_classpaths:
      self.group_classpaths[group_key] = []
    # get the classpath to use for compiling targets within the group specified by group_key.
    return self.group_classpaths[group_key]

  def _key_to_map(self, key):
    result = {}
    if key == '<none>':
      return result
    pairs = key.split(',')
    for p in pairs:
      (k, v) = p.split("=")
      result[k] = v
    return result

  def _is_compatible(self, mod_key, other_key):
    # Check if a set of classpath modifications produced by compiling elements of the group
    # specified by mod_key should be added to the classpath of other_key's group.

    # A key is a list of comma separated name=value keys.
    # keys match, if and only of for all pairs k=v1 from mod, and k=v2 from other,
    # either v1 == v2 or v1 == <none>.
    mod_map = self._key_to_map(mod_key)
    other_map = self._key_to_map(other_key)
    for k in mod_map:
      vm = mod_map[k]
      vo = other_map[k]
      if not (vm == vo or vm == "<none>"):
        return False
    return True

  def update_compatible_classpaths(self, group_key, path_additions):
    # Update the classpath of all groups compatible with group_key, adding path_additions to their classpath.
    for key in self.group_classpaths:
      if group_key is None or self._is_compatible(group_key, key):
        group_classpath = self.group_classpaths[key]
        for cpel in path_additions:
          if cpel not in group_classpath:
            group_classpath.append(cpel)

  def set_base_classpath_for_group(self, group_key, classpath):
    # set the initial classpath of the elements of group_key to classpath.
    self.group_classpaths[group_key] = classpath

