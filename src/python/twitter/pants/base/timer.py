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

import time

from collections import namedtuple
from contextlib import contextmanager

from twitter.common.lang import Compatibility


Timing = namedtuple('Timing', ['label', 'times', 'overlapping'])


class Timer(object):
  def __init__(self):
    self._timings = []

  @contextmanager
  def timing(self, label):
    """Convenient timing context.

    Use like this:

    with timer.timing(label):
      ... the work that will be timed ...
    """
    start = self.now()
    yield None
    elapsed = self.now() - start
    self.log(label, [elapsed])

  def now(self):
    return time.monotonic() if Compatibility.PY3 else time.time()

  def log(self, label, times, overlapping=False):
    """Code that has to measure its own timings directly can log them here.

    If labels are of the form prefix:suffix, then the sum of all times of consecutively-logged
    timings with the same prefix will also be logged.

    Set overlapping to True if you're logging a timing that overlaps with other, already-logged
    timings.
    """
    self._timings.append(Timing(label, times, overlapping))

  def print_timings(self):
    grand_total_time = 0

    last_prefix = None
    total_time_for_prefix = 0
    num_timings_with_prefix = 0

    def maybe_print_timings_for_prefix():
      if num_timings_with_prefix > 1:
        print('[%(prefix)s] total: %(total).3fs' % {
          'prefix': last_prefix,
          'total': total_time_for_prefix
        })

    for timing in self._timings:
      total_time = sum(timing.times)
      if not timing.overlapping:
        grand_total_time += total_time

      pos = timing.label.find(':')
      if pos != -1:
        prefix = timing.label[0:pos]
        if prefix == last_prefix and not timing.overlapping:
          total_time_for_prefix += total_time
          num_timings_with_prefix += 1
        else:
          maybe_print_timings_for_prefix()
          total_time_for_prefix = total_time
          num_timings_with_prefix = 1
        last_prefix = prefix

      if len(timing.times) > 1:
        print('[%(label)s(%(numsteps)d)] %(timings)s -> %(total).3fs' % {
          'label': timing.label,
          'numsteps': len(timing.times),
          'timings': ','.join('%.3fs' % time for time in timing.times),
          'total': total_time
        })
      else:
        print('[%(label)s] %(total).3fs' % {
          'label': timing.label,
          'total': total_time
        })
    maybe_print_timings_for_prefix()
    print('total: %.3fs' % grand_total_time)
