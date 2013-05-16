import sys
import threading

from collections import defaultdict

from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.reporting.reporter import Reporter


class ConsoleReporter(Reporter):
  """Plain-text reporting to stdout."""

  def __init__(self, run_tracker, indenting):
    """If indenting is True, we indent the reporting to reflect the nesting of workunits."""
    Reporter.__init__(self, run_tracker)
    self._indenting = indenting
    # We don't want spurious newlines between nested workunits, so we only emit them
    # when we need to write content to the workunit. This is a bit hacky, but effective.
    self._lock = threading.Lock()  # Protects self._needs_newline, in caseof parallel workunits.
    self._needs_newline = defaultdict(bool)  # workunit id -> bool.

  def open(self):
    """Implementation of Reporter callback."""
    pass

  def close(self):
    """Implementation of Reporter callback."""
    # TODO(benjy): Find another way to get this setting. This is the only reason we need
    # RunTracker to have a reference to options, and it would be much nicer to get rid of it.
    if self.run_tracker.options.time:
      print('\n')
      print('Cumulative Timings')
      print('==================')
      print(self._format_aggregated_timings(self.run_tracker.cumulative_timings))
      print('\n')
      print('Self Timings')
      print('============')
      print(self._format_aggregated_timings(self.run_tracker.self_timings))
      print('\n')
      print('Artifact Cache Stats')
      print('====================')
      print(self._format_artifact_cache_stats(self.run_tracker.artifact_cache_stats))
    print('')

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit.parent and workunit.parent.has_label(WorkUnit.MULTITOOL):
      # For brevity, we represent each consecutive invocation of a multitool with a dot.
      sys.stdout.write('.')
    else:
      sys.stdout.write('\n%s %s %s[%s]' %
                       (workunit.start_time_string(),
                        workunit.start_delta_string(),
                        self._indent(workunit),
                        workunit.name if self._indenting else workunit.path()))
    sys.stdout.flush()

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit.outcome() != WorkUnit.SUCCESS:
      # Emit the workunit output, if any, to aid in debugging the problem.
      for name, outbuf in workunit.outputs().items():
        sys.stdout.write(self._prefix(workunit, '\n==== %s ====\n' % name))
        sys.stdout.write(self._prefix(workunit, outbuf.read_from(0)))
        sys.stdout.flush()
    if workunit.parent:
      with self._lock:
        self._needs_newline[workunit.parent.id] = False

  def handle_message(self, workunit, *msg_elements):
    """Implementation of Reporter callback."""
    # If the element is a (msg, detail) pair, we ignore the detail. There's no
    # useful way to display it on the console.
    elements = [e if isinstance(e, basestring) else e[0] for e in msg_elements]
    with self._lock:
      if not self._needs_newline[workunit.id]:
        elements.insert(0, '\n')
        self._needs_newline[workunit.id] = True
    sys.stdout.write(self._prefix(workunit, ''.join(elements)))

  def handle_output(self, workunit, label, s):
    """Implementation of Reporter callback."""
    # Emit output from test frameworks, but not from other tools.
    # This is an arbitrary choice, but one that turns out to be useful to users in practice.
    if workunit.has_label(WorkUnit.TEST):
      with self._lock:
        if not self._needs_newline[workunit.id]:
          s = '\n' + s
          self._needs_newline[workunit.id] = True
      sys.stdout.write(self._prefix(workunit, s))
      sys.stdout.flush()

  def _format_aggregated_timings(self, aggregated_timings):
    return '\n'.join(['%(timing).3f %(label)s' % x for x in aggregated_timings.get_all()])

  def _format_artifact_cache_stats(self, artifact_cache_stats):
    stats = artifact_cache_stats.get_all()
    return 'No artifact cache reads.' if not stats else \
    '\n'.join(['%(cache_name)s - Hits: %(num_hits)d Misses: %(num_misses)d' % x
               for x in stats])

  def _indent(self, workunit):
    return '  ' * (len(workunit.ancestors()) - 1)

  _time_string_filler = ' ' * len('HH:MM:SS mm:ss ')
  def _prefix(self, workunit, s):
    if self._indenting:
      return s.replace('\n', '\n' + ConsoleReporter._time_string_filler + self._indent(workunit))
    else:
      return ConsoleReporter._time_string_filler + s

