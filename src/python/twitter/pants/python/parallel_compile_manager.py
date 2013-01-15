__author__ = 'Ryan Williams'

import time
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.cache_manager import VersionedTargetSet

class ParallelCompileError(Exception):
  "Error that is thrown if something goes wrong in the ParallelCompileManager"

def versioned_target_nodes_to_versioned_target_set(versioned_target_nodes):
  versioned_targets = [node.data for node in versioned_target_nodes]
  return VersionedTargetSet.from_versioned_targets(versioned_targets)


class ParallelCompileManager(object):
  """Interface for strategies for parallel compiles

  Given:

    - a DAG of invalid targets,
    - a maximum number of parallel compiles to allow,
    - a compile command that takes a VersionedTargetSet, and
    - a post-compile command that takes a VersionedTargetSet,

  this class repeatedly requests a "next set" of nodes to compile and compiles them on one of its compile "workers", in
  parallel with other sets.

  Subclasses need only implement the following method:

    def _get_next_node_sets_to_compile(self, num_compile_workers_available)

  which, given the number of "compile workers" available, returns up to that many sets of VersionedTargets. Each set of
  VersionedTargets will then be compiled on its own worker.
  """
  def __init__(self, logger, invalid_target_tree, max_num_parallel_compiles, compile_cmd, post_compile_cmd = None):
    self._logger = logger

    self._tree = invalid_target_tree

    # The maximum number of parallel compiles allowed.
    self._max_num_parallel_compiles = max_num_parallel_compiles

    # This function should take a VersionedTargetSet, start compiling it, and return the running compile process Popen.
    self._compile_cmd = compile_cmd

    # This functions should take a VersionedTargetSet and do any relevant post-processing.
    self._post_compile_cmd = post_compile_cmd

    # Tree nodes that are currently compiling. Currently only referenced when there are no more compiles to spawn (but
    # there may still be some compiles running), but seems like a good thing to keep around.
    self._in_flight_target_nodes = set([])

    # Set of nodes that can currently be compiled (i.e. that don't depend on anything that hasn't already been
    # compiled). This should always equal self._tree.leaves - self._in_flight_target_nodes.
    self._frontier_nodes = set([leaf for leaf in invalid_target_tree.leaves])

    # Processes that are currently compiling, as returned by compile_cmd.
    self._compile_processes = set([])

    # Map from each compiling process to the set of nodes that it is compiling.
    self._compiling_nodes_by_process = {}

    # Map from each compiling process to the VersionedTargetSet that it is compiling.
    self._versioned_target_sets_by_process = {}

    # List of nodes that have been "processed" (compiled, or skipped over if no compilation was necessary).
    self._processed_nodes = []

    # List of sets of nodes that have failed to compile.
    self._failed_compiles = []


  def _get_next_node_sets_to_compile(self, num_compile_workers_available):
    """Abstract: subclasses implement different strategies for selecting next nodes to be compiled.

    Return a list of sets of nodes, up to one set per available compile worker. Presumably these should be nodes that
    don't depend on anything that is currently compiling or yet to be compiled."""


  def _handle_processed_node_set(self, versioned_target_set, target_node_set, was_compiled, was_successful):
    """Add a node's parents to the frontier set, excepting any that are also ancestors of another of its parents.

    This should be called on every target set that we inspect, regardless of whether it needed to be compiled or
    not."""
    if was_compiled and was_successful and self._post_compile_cmd:
      self._post_compile_cmd(versioned_target_set)

    if was_compiled and not was_successful:
      self._failed_compiles.append(target_node_set)

    self._processed_nodes += target_node_set
    self._logger.info("Processed %d out of %d targets. " % (len(self._processed_nodes), len(self._tree.nodes)),)
    self._logger.info("In flight (%d): {%s}. " % (len(self._in_flight_target_nodes), ','.join([t.short_id for t in self._in_flight_target_nodes])),)
    self._logger.info("Frontier (%d): {%s}" % (len(self._frontier_nodes), ','.join(t.short_id for t in self._frontier_nodes)))

    new_leaves = self._tree.remove_nodes(target_node_set)
    self._frontier_nodes.update(new_leaves)


  def _spawn_target_compile(self, target_node_set):
    "Given a set of nodes, make a VersionedTargetSet and fork a compilation process."
    if not target_node_set:
      return
    self._logger.debug("\n*** Spawning compile: %s\n" % str(target_node_set))

    versioned_target_set = versioned_target_nodes_to_versioned_target_set(target_node_set)

    compile_process = self._compile_cmd(versioned_target_set)
    self._frontier_nodes -= target_node_set
    if compile_process:
      # If we've successfully forked a compilation process, do some bookkeeping.
      self._compiling_nodes_by_process[compile_process] = target_node_set
      self._versioned_target_sets_by_process[compile_process] = versioned_target_set
      self._compile_processes.add(compile_process)
      self._in_flight_target_nodes.update(target_node_set)
    else:
      # NOTE(ryan): this can happen if the targets had no sources, therefore compile_cmd did not result in a process
      # being spawned. In that case, mark these nodes as having been "processed".
      self._handle_processed_node_set(
        versioned_target_set,
        target_node_set,
        was_compiled=False,
        was_successful=True)

  def _handle_compilation_finished(self, compile_process, return_value):
    "Clean up a finished compilation process."
    if return_value == 0:
      self._logger.info(
        "Finished compiling: {%s}" % (','.join(node.data.id for node in self._compiling_nodes_by_process[compile_process])))
    else:
      self._logger.warn(
        "*** Failed compiling (%d): {%s}\n" % (return_value, ','.join(node.data.id for node in self._compiling_nodes_by_process[compile_process])))

    self._compile_processes.remove(compile_process)

    target_node_set = self._compiling_nodes_by_process[compile_process]
    versioned_target_set = self._versioned_target_sets_by_process[compile_process]
    del self._compiling_nodes_by_process[compile_process]
    del self._versioned_target_sets_by_process[compile_process]

    self._in_flight_target_nodes -= (target_node_set)

    self._handle_processed_node_set(
      versioned_target_set,
      target_node_set,
      was_compiled=True,
      was_successful=(return_value == 0))


  def _poll_compile_processes(self):
    "Clean up any compiles that have finished. Return False if any compiles failed, True otherwise."

    # If any processes have finished, map them to their return values for later processing.
    return_values = {}
    found_failure = False
    for compile_process in self._compile_processes:
      poll_value = compile_process.poll()
      if poll_value != None:
        return_values[compile_process] = poll_value
        if poll_value != 0:
          found_failure = True

    # Do this outside the loop so as to not change the size of the set the loop is iterating over
    # (self._compiling_processes) by removing finished processes from it.
    for compile_process, return_value in return_values.iteritems():
      self._handle_compilation_finished(compile_process, return_value)

    return not found_failure


  def _kill_running_compiles(self):
    """Terminate all running compile processes. Currently unused as we prefer to let all running compiles finish, even
    when we find a failure."""
    for compile_process in self._compile_processes:
      compile_process.terminate()


  def _loop_once(self):
    """Check for available workers and spawn new compiles if there are any."""

    num_compile_workers_available = self._max_num_parallel_compiles - len(self._compile_processes)

    # NOTE(ryan): a possible optimization here would be to start computing what the next-compiled partition should be,
    # while we wait for in-flight compiles to finish. Currently this computation takes a negligible amount of time,
    # however, and the next set to compile is likely to depend on which of the currently compiling sets finishes first.
    if num_compile_workers_available > 0 and len(self._frontier_nodes) > 0:
      # We have room to spawn more compiles. Fetch some sets and spawn compiles for them.
      next_target_node_sets = self._get_next_node_sets_to_compile(num_compile_workers_available)
      for next_target_node_set in next_target_node_sets:
        self._spawn_target_compile(next_target_node_set)

    if not self._poll_compile_processes():
      # Something failed.
      return False

    return True


  def execute(self):
    """Until we've processed all targets, execute the following loop:
        - spawn new compiles if we're below the limit of concurrently running compiles, and
        - poll the currently running compiles to see if any are done."""

    num_nodes = len(self._tree.nodes)
    while len(self._processed_nodes) < num_nodes:
      # Sleeping avoids losing a CPU core to just spinning through this loop.
      time.sleep(0.1)
      if not self._loop_once():
        # A compile failed. Stop looping.
        break

    result_msg = ("Nothing left to spawn"
                  if len(self._processed_nodes) == num_nodes and not self._failed_compiles
                  else "Caught failure")
    self._logger.info("\n%s after compiling %d targets out of %d:" % (
      result_msg,
      len(self._processed_nodes),
      len(self._tree.nodes)))

    for node in self._processed_nodes:
      self._logger.debug("\t%s" % node.data.target.id)
    self._logger.debug('')

    self._logger.info("%d still in flight:" % len(self._in_flight_target_nodes))
    for node in self._in_flight_target_nodes:
      self._logger.info("\t%s" % node.data.target.id)
    self._logger.info('')

    # Once the last of the targets has been sent off to compile (or we've caught a failure), wait around for
    # in-flight compiles to finish.
    success = True
    for compile_process in self._compile_processes:
      compile_process.wait()
      if compile_process.returncode != 0:
        target_node_set = self._compiling_nodes_by_process[compile_process]
        self._logger.warn("Caught compile failure: %s" % ','.join([str(t) for t in target_node_set]))
        success = False
        self._failed_compiles.append(target_node_set)

    if len(self._failed_compiles) > 0:
      raise TaskError("Failed compiles:\n%s" % "\n\t".join([str(t) for t in self._failed_compiles]))

    return success
