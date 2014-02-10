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

__author__ = 'Tejal Desai'

import httplib
import json
import os
import socket
import sys
import urllib
import time

from twitter.common import dirutil, log
from twitter.common.contextutil import temporary_file
from twitter.common.dirutil import safe_open, safe_mkdtemp
from twitter.common.dirutil.fileset import Fileset
from twitter.common.quantity import Amount, Time
from twitter.common.quantity.parse_simple import parse_time, InvalidTime
from twitter.common.util.command_util import CommandUtil


MAX_RECORDS = 100
LOG_FILES = {
              "DEBUG" : ".global.DEBUG",
              "ERROR" : ".global.ERROR",
              "FATAL" : ".global.FATAL",
              "INFO" : ".global.INFO",
              "WARNING" : ".global.WARNING"
            }

class StatsHttpClient(object):
  def __init__(self, host=None, port=None, http_endpoint=None, stats_dir=None):
    self._client = None
    self._host = host
    self._port = port
    self._http_endpoint = http_endpoint
    self._stats_dir = stats_dir

  def _get_client(self):
    if self._client is None:
      self._client = httplib.HTTPConnection(self._host, self._port, timeout=2)
    return self._client

  def push_stats(self, json_stats):
    log.debug("Uploading pants stats to %s" % self._host)
    client = self._get_client()
    params = urllib.urlencode({"json": json_stats})
    headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
    client.request("POST", self._http_endpoint, params, headers)
    resp = client.getresponse()
    resp_type = resp.status / 100
    client.close()
    if resp_type not in [2, 3]:
      log.debug("There was an error uploading the stats")

  def process_stats_file(self):
    for filename in Fileset.walk(self._stats_dir):
      try :
        with open(os.path.join(self._stats_dir, filename), 'r') as stats_file:
          lines = stats_file.readlines()
          tmp_str = ",".join(lines)
          tmp_str.strip(',')
          self.push_stats("[" + tmp_str + "]")
        os.remove(os.path.join(self._stats_dir, filename))
      except httplib.HTTPException as e:
        log.debug("HTTPException %s" % e)
      except OSError as e:
        log.debug("Error reading or deleting a stats file %s" % e)


class StatsUploader():
  def __init__(self, host, port, endpoint, max_delay, stats_file, user, force_stats_upload=False):
    self.force_stats_upload = force_stats_upload
    self._stats_log_dir = dirutil.safe_mkdtemp()
    self._stats_log_file = os.path.join(self._stats_log_dir, "current_run")
    log.init(self._stats_log_file)
    self._stats_dir = os.path.join("/tmp", user, "stats_uploader_dir")
    self._stats_http_client = StatsHttpClient(host, port, endpoint, self._stats_dir)
    self._max_delay = max_delay
    self._pants_stat_file = stats_file
    self._user = user

  def upload_sync(self, stats):
    try:
      last_modified = self.collect_host_env_info(stats)
      if not last_modified:
        last_modified = int(os.path.getmtime(self._pants_stat_file))

      with safe_open(self._pants_stat_file, 'r') as stats_file:
        lines = stats_file.readlines()
      #Just want to make sure, we do not wait for MAX_RECORDS but also upload when
      #the last time we uploaded is less than configured value in the pants.ini
      last_uploaded = Amount(int(time.time()) - last_modified, Time.SECONDS)
      if (self.force_stats_upload or len(lines) >= MAX_RECORDS or last_uploaded > self._max_delay):
        #Put the file in the right place.
        dirutil.safe_mkdir(self._stats_dir)
        with temporary_file(self._stats_dir, False) as stats_uploader_tmpfile:
          os.rename(self._pants_stat_file, stats_uploader_tmpfile.name)
        self._stats_http_client.process_stats_file()
      #Merge Logs so that user /tmp is not cluttered with too many log files for each run.
      self.merge_logs()
      sys.exit(0)
    except OSError as e:
      log.debug("Error manipulating stats files for upload %s" % e)

  def collect_host_env_info(self,stats):
    #Get Environment Variable
    stats["env"] = os.environ.data
    stats["timestamp"] = int(time.time())
    try:
      #Get the System info
      import psutil
      stats["cpu_time"] = psutil.cpu_percent(interval=1)
      stats["network_counter"] = psutil.net_io_counters()
      stats["no_of_cpus"] = psutil.NUM_CPUS
    except Exception as e:
      log.debug("Exception %s. Cannot collect psutil stats" % e)

    #Get Git info
    stats["git"] = {}
    (ret, git_origin) = CommandUtil().execute_and_get_output(["git", "remote", "-v"])
    if ret == 0:
      for url in git_origin.splitlines():
        origin = url.split()
        str1 = origin[2].strip("(").strip(")")
        if origin:
          stats["git"][str1] = origin[1]

    #Get git branch
    (ret, git_branch) = CommandUtil().execute_and_get_output(["git", "rev-parse", "--abbrev-ref",
                                                              "HEAD"])
    if ret == 0:
      stats["git"]["branch"] = git_branch.strip()
    #Network IP
    try:
      stats["ip"] = socket.gethostbyname(socket.gethostname())
    except Exception as e:
      log.debug("Exception %s. Cannot get ip stats" % e)
    log.debug("Done collecting stats")

    #get the last modified time for the File so that we can upload the stats if they havent being
    #Uploaded for last 6 hours.
    last_modified = None
    if os.path.exists(self._pants_stat_file):
      last_modified = int(os.path.getmtime(self._pants_stat_file))
    try:
      with open(self._pants_stat_file , 'a') as stats_file:
        json_response = json.dumps(stats, cls=PythonObjectEncoder)
        stats_file.write(json_response + "\n")
      return last_modified
    except IOError as e:
      log.debug("Could not write the pants stats %s" % e)

  def merge_logs(self):
    prefix = os.path.join("/tmp", self._user, "buildtime_uploader")
    self.append_log_file("DEBUG")
    self.append_log_file("INFO")
    self.append_log_file("FATAL")
    self.append_log_file("ERROR")
    self.append_log_file("WARNING")

  def append_log_file(self, log_level):
    target_file = os.path.join("/tmp", self._user, "buildtime_uploader" + LOG_FILES[log_level])
    source_file = self._stats_log_file + "." + log_level
    self._append_to_file(source_file, target_file)

  def _append_to_file(self, source_file, target_file):
    with open(target_file, 'a') as target_fh:
      with open(source_file, "r") as source_fh:
        target_fh.write(source_fh.read())

class PythonObjectEncoder(json.JSONEncoder):
  def default(self, obj):
    try:
     return json.JSONEncoder.default(self, obj)
    except TypeError as e:
      log.warn("Could not encode %s" % obj)
      pass
