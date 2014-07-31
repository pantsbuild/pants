# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.lang import Compatibility

from pants.base.exceptions import TargetDefinitionException
from pants.base.validation import assert_list
from pants.backend.jvm.targets.java_library import JavaLibrary


class JavaAgent(JavaLibrary):
  """Defines a java agent entrypoint."""

  def __init__(self,
               name,
               sources=None,
               excludes=None,
               resources=None,
               exclusives=None,
               premain=None,
               agent_class=None,
               can_redefine=False,
               can_retransform=False,
               can_set_native_method_prefix=False,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    :param string premain: When an agent is specified at JVM launch time this attribute specifies
      the agent class. Exactly one of ``premain`` or ``agent_class`` must be specified.
    :param string agent_class: If an implementation supports a mechanism to start agents sometime
      after the VM has started then this attribute specifies the agent class. Exactly one of
      ``premain`` or ``agent_class`` must be specified.
    :param bool can_redefine: `True` if the ability to redefine classes is needed by this agent;
      `False` by default.
    :param bool can_retransform: `True` if the ability to retransform classes is needed by this
      agent; `False` by default.
    :param bool can_set_native_method_prefix: `True` if the ability to set he native method prefix
      is needed by this agent; `False` by default.
    """

    super(JavaAgent, self).__init__(
        name=name,
        sources=self.assert_list(sources),
        provides=None,
        excludes=self.assert_list(excludes),
        resources=self.assert_list(resources),
        exclusives=exclusives,
        **kwargs)

    if not (premain or agent_class):
      raise TargetDefinitionException(self, "Must have at least one of 'premain' or 'agent_class' "
                                            "defined.")
    if premain and not isinstance(premain, Compatibility.string):
      raise TargetDefinitionException(self, 'The premain must be a fully qualified class name, '
                                            'given %s of type %s' % (premain, type(premain)))

    if agent_class and not isinstance(agent_class, Compatibility.string):
      raise TargetDefinitionException(self,
                                      'The agent_class must be a fully qualified class name, given '
                                      '%s of type %s' % (agent_class, type(agent_class)))

    self._premain = premain
    self._agent_class = agent_class
    self._can_redefine = can_redefine
    self._can_retransform = can_retransform
    self._can_set_native_method_prefix = can_set_native_method_prefix

    self.add_labels('java_agent')

  @property
  def premain(self):
    """The launch time agent fully qualified class name.

    Either ``agent_class`` or ``premain`` will be defined and the other will be `None`.
    """
    return self._premain

  @property
  def agent_class(self):
    """The post-launch-time agent fully qualified class name.

    Either ``agent_class`` or ``premain`` will be defined and the other will be `None`.
    """
    return self._agent_class

  @property
  def can_redefine(self):
    """Returns `True` if the ability to redefine classes is needed by this agent."""
    return self._can_redefine

  @property
  def can_retransform(self):
    """Returns `True` if the ability to retransform classes is needed by this agent."""
    return self._can_retransform

  @property
  def can_set_native_method_prefix(self):
    """Returns `True` if the ability to set he native method prefix is needed by this agent."""
    return self._can_set_native_method_prefix
