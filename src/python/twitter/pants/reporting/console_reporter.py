import sys

from collections import namedtuple

from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.reporting.report import Report
from twitter.pants.reporting.reporter import Reporter


try:
  from colors import cyan, green, red, yellow
  _colorfunc_map = {
    Report.FATAL: red,
    Report.ERROR: red,
    Report.WARN: yellow,
    Report.INFO: green,
    Report.DEBUG: cyan
  }
except ImportError:
  _colorfunc_map = {}


class ConsoleReporter(Reporter):
  """Plain-text reporting to stdout."""

  # Console reporting settings.
  #   color: use ANSI colors in output.
  #   indent: Whether to indent the reporting to reflect the nesting of workunits.
  #   timing: Show timing report at the end of the run.
  #   cache_stats: Show artifact cache report at the end of the run.
  Settings = namedtuple('Settings',
                        Reporter.Settings._fields + ('color', 'indent', 'timing', 'cache_stats'))

  def __init__(self, run_tracker, settings):
    Reporter.__init__(self, run_tracker, settings)

  def open(self):
    """Implementation of Reporter callback."""
    pass

  def close(self):
    """Implementation of Reporter callback."""
    if self.settings.timing:
      print('\n')
      print('Cumulative Timings')
      print('==================')
      print(self._format_aggregated_timings(self.run_tracker.cumulative_timings))
      print('\n')
      print('Self Timings')
      print('============')
      print(self._format_aggregated_timings(self.run_tracker.self_timings))
    if self.settings.cache_stats:
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
                        workunit.name if self.settings.indent else workunit.path()))
      if workunit.has_label(WorkUnit.TEST):
        # So that emitted output from test frameworks starts on a new line (see below).
        sys.stdout.write(self._prefix(workunit, '\n'))
    sys.stdout.flush()

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit.outcome() != WorkUnit.SUCCESS:
      # Emit the workunit output, if any, to aid in debugging the problem.
      for name, outbuf in workunit.outputs().items():
        sys.stdout.write(self._prefix(workunit, '\n==== %s ====\n' % name))
        sys.stdout.write(self._prefix(workunit, outbuf.read_from(0)))
        sys.stdout.flush()

  def do_handle_log(self, workunit, level, *msg_elements):
    """Implementation of Reporter callback."""
    # If the element is a (msg, detail) pair, we ignore the detail. There's no
    # useful way to display it on the console.
    elements = [e if isinstance(e, basestring) else e[0] for e in msg_elements]
    msg = '\n' + ''.join(elements)
    if self.settings.color:
      msg = _colorfunc_map.get(level, lambda x: x)(msg)
    sys.stdout.write(self._prefix(workunit, msg))

  def handle_output(self, workunit, label, s):
    """Implementation of Reporter callback."""
    # Emit output from test frameworks, but not from other tools.
    # This is an arbitrary choice, but one that turns out to be useful to users in practice.
    if workunit.has_label(WorkUnit.TEST) or \
       workunit.has_label(WorkUnit.REPL) or \
       workunit.has_label(WorkUnit.RUN):
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
    if self.settings.indent:
      return s.replace('\n', '\n' + ConsoleReporter._time_string_filler + self._indent(workunit))
    else:
      return ConsoleReporter._time_string_filler + s

