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

from __future__ import print_function

import os
import sys

from twitter.common import dirutil, log
from twitter.common.process import spawn_daemon
from twitter.common.quantity.parse_simple import parse_time
from twitter.pants import get_buildroot
from twitter.pants.buildtimestats import StatsUploader

STATS_COLLECTION_URL = "devprod_stats.production.devprod.service.smf1.twitter.com"
STATS_COLLECTION_PORT = 80
STATS_COLLECTION_ENDPOINT = "/buildtime_stats.json"
MAX_UPLOAD_DELAY = "6h"
DEFAULT_STATS_FILE = ".pants.stats"
PHASE_TOTAL = "phase_total"
CMD_TOTAL = "cmd_total"

__author__ = 'Tejal Desai'


class BuildTimeStats(object):

  def __init__(self, user, force_upload):
    """
    :param user: The user to be used for uploading stats. Its the current user.
    :param force_upload: [False] Uploads Stats at the end of pants run.
    """
    self._user = user
    self._force_upload = force_upload
    self._max_delay = parse_time(MAX_UPLOAD_DELAY)

  def _get_default_stats_file(self):
    return os.path.join(get_buildroot(), DEFAULT_STATS_FILE)

  def compute_stats(self, executed_goals, elapsed):
    timings_array = []
    for phase, timings in executed_goals.items():
      phase_time = None
      for goal, times in timings.items():
        #Create a new structure
        timing = dict()
        timing['phase'] = str(phase)
        timing['goal'] = goal
        timing['total'] = sum(times)
        if not phase_time:
          phase_time = 0
        phase_time += sum(times)
        #Add the timings for each sub phase in the timings array
        timings_array.append(timing)
      if len(timings) > 1:
        #Add the phase total
        timing = dict()
        timing['phase'] = str(phase)
        timing['goal'] = PHASE_TOTAL
        timing['total'] = phase_time
        timings_array.append(timing)
    #end of Loop through PHASES
    timing = {}
    timing['phase'] = CMD_TOTAL
    timing['goal'] = CMD_TOTAL
    timing['total'] = elapsed
    timings_array.append(timing)
    return timings_array

  def stats_uploader_daemon(self, stats):
    """
    Starts the StatsUploader as a daemon process if it is already not running
    """
    log.debug("Checking if the statsUploaderDaemon is already running")
    stats_pid = os.path.join("/tmp", self._user, ".pid_stats")
    stats_uploader_dir = os.path.join("/tmp", self._user)
    dirutil.safe_mkdir(stats_uploader_dir)
    if not os.path.exists(stats_pid):
      log.debug("Starting the daemon")
      stats_log_file = os.path.join("/tmp", self._user, "buildtime_uploader")
      log.debug("The logs are written to %s" % stats_log_file)
      if spawn_daemon(pidfile=stats_pid, quiet=True):
        su = StatsUploader(STATS_COLLECTION_URL, STATS_COLLECTION_PORT, STATS_COLLECTION_ENDPOINT,
                           self._max_delay, self._get_default_stats_file(), self._user,
                           self._force_upload)
        su.upload_sync(stats)

  def record_stats(self, timings, elapsed):
    """Records all the stats for -x flag
    and the network stats
    """
    timing_stats = self.compute_stats(timings, elapsed)
    stats = {}
    stats["timings"] = timing_stats
    stats["args"] = sys.argv[1:]
    self.stats_uploader_daemon(stats)
