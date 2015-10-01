# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.build_graph.target import Target


class InvalidationReport(object):
  """Creates a report of all versioned target sets seen in the build."""

  class TaskReport(object):
    class TaskEntry(namedtuple('TaskEntry', ['targets_hash', 'target_ids', 'cache_key_id',
                                             'cache_key_hash', 'phase', 'valid'])):
      """
      :param targets_hash: A manufactured id for the versioned target set
      :param target_ids: list of string target ids
      :param cache_key_id: cache key from the InvalidationCheck
      :param cache_key_hash: hash of cache_key from the InvalidationCheck
      :param valid: True if the cache_key is valid
      """

    def __init__(self, task_name, cache_manager, invocation_id):
      self._task_name = task_name
      self.cache_manager = cache_manager
      self._invocation_id = invocation_id
      self._entries = []

    def add(self, targets, cache_key, valid, phase=None):
      if not phase:
        raise ValueError('Must specify a descriptive phase= value (e.g. "init", "pre-check", ...')
      # Manufacture an id from a hash of the target ids
      targets_hash = Target.identify(targets)
      self._entries.append(self.TaskEntry(targets_hash=targets_hash,
                                          target_ids=[t.id for t in targets],
                                          cache_key_id=cache_key.id,
                                          cache_key_hash=cache_key.hash,
                                          valid=valid,
                                          phase=phase))

    def report(self, writer):
      """
      :param BufferedWriter writer: output for the report
      """
      for entry in self._entries:
        for target_id in entry.target_ids:
          writer.write(
              ('{invocation_id},{task},{targets_hash},{target_id},{cache_key_id},{cache_key_hash},'
               + '{phase},{valid}\n')
              .format(invocation_id=self._invocation_id,
                      task=self._task_name,
                      targets_hash=entry.targets_hash,
                      target_id=target_id,
                      cache_key_id=entry.cache_key_id,
                      cache_key_hash=entry.cache_key_hash,
                      phase=entry.phase,
                      valid=entry.valid))

  def __init__(self):
    self._task_reports = {}
    self._invocation_id = 0
    self._filename = None

  def set_filename(self, filename):
    self._filename = filename

  def add_task(self, cache_manager):
    self._invocation_id += 1
    task_report = self.TaskReport(cache_manager.task_name, cache_manager, self._invocation_id)
    self._task_reports[id(cache_manager)] = task_report
    return task_report

  def add_vts(self, cache_manager, targets, cache_key, valid, phase):
    """ Add a single VersionedTargetSet entry to the report.
    :param InvalidationCacheManager cache_manager:
    :param CacheKey cache_key:
    :param bool valid:
    :param string phase:
    """
    if id(cache_manager) not in self._task_reports:
      self.add_task(cache_manager)
    self._task_reports[id(cache_manager)].add(targets, cache_key, valid, phase)

  def report(self, filename=None):
    """ Write details of each versioned target to file
    :param string filename: file to write out the report to

    Fields in the report:
      invocation_id: A sequence number that increases each time a task is invoked
      task_name: The name of the task
      targets_hash: an id from a hash of all target ids to identify a VersionedTargetSet
      target_id: target id
      cache_key_id: the Id for the cache key
      cache_key_hash: computed hash for the cache key
      phase: What part of the validation check the values were captured
      valid: True if the cache is valid for the VersionedTargetSet
    """
    # TODO(zundel) set report to stream to the file
    filename = filename or self._filename
    if filename:
      with open(filename, 'w') as writer:
        writer.write(
          'invocation_id,task_name,targets_hash,target_id,cache_key_id,cache_key_hash,phase,valid'
          + '\n')
        for task_report in self._task_reports.values():
          task_report.report(writer)
