__author__ = 'Tejal Desai'

import json
import mox
import psutil
import socket
import sys
from textwrap import dedent
import unittest

from twitter.common.contextutil import temporary_file
from twitter.common import dirutil, log
from twitter.common.util.command_util import CommandUtil
from twitter.common.quantity import Amount, Time

from twitter.pants.buildtimestats import BuildTimeStats as RealBuildTimeStats
from twitter.pants.buildtimestats import StatsUploader as RealStatsUploader


class StatsUploader(RealStatsUploader):
  def __init__(self, host, port, endpoint, max_delay, stats_file, user):
    self._calls = []
    RealStatsUploader.__init__(self,host, port, endpoint, max_delay, stats_file, user)

  def _append_to_file(self, src, target):
    if not self._calls:
      self._calls = []
    self._calls.append({src :target})
  def get_calls(self):
    return self._calls



class BuildTimeStats(RealBuildTimeStats):
  def __init__(self, file_nm):
    self._file = file_nm

  def stats_uploader_daemon(self, stats):
    """
    This method calls uploader in sync
    """
    self._su = StatsUploader("locahost", "80", "buildtime.json", Amount(6, Time.HOURS),
                              self._file, "dummy")
    self._su.upload_sync(stats)

  def get_log_append_calls(self):
    return self._su.get_calls()


class BuildTimeStatsTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()


  def tearDown(self):
    self.mox.UnsetStubs()

  def test_compute_stats(self):
    executed_goals = {'resolve-idl':{ 'idl': [0.00072813034057617188],
                                      'extract': [3.0994415283203125e-06] },
                      "thriftstore-codegen": {'thriftstore-codegen': [0.0001010894775390625] },
                      "gen": {'tweetypie-fetch': [0.028632879257202148], 'thrift': [0.016566991806030273],
                              'protoc': [0.0038318634033203125], 'antlr': [0.0020389556884765625],
                              'thriftstore-dml-gen': [0.0022170543670654297],
                              'tweetypie-clean': [0.0054290294647216797] },
                      "resolve": {'ivy': [0.00097703933715820312] },
                      "compile": {'checkstyle': [0.00057005882263183594]},
                      "test": {'junit': [9.1075897216796875e-05], 'specs': [0.0015749931335449219]}
                    }
    with temporary_file() as temp_fd:
      bs = BuildTimeStats(temp_fd.name)
      actual_timings = bs.compute_stats(executed_goals, 100)
      expected_timings =[{'phase': 'resolve', 'total': 0.00097703933715820312, 'goal': 'ivy'},
                       {'phase': 'resolve-idl', 'total': 0.00072813034057617188, 'goal': 'idl'},
                       {'phase': 'resolve-idl', 'total': 3.0994415283203125e-06, 'goal': 'extract'},
                       {'phase': 'resolve-idl', 'total': 0.00073122978210449219, 'goal': 'phase_total'},
                       {'phase': 'compile', 'total': 0.00057005882263183594, 'goal': 'checkstyle'},
                       {'phase': 'thriftstore-codegen', 'total': 0.0001010894775390625, 'goal': 'thriftstore-codegen'},
                       {'phase': 'test', 'total': 9.1075897216796875e-05, 'goal': 'junit'},
                       {'phase': 'test', 'total': 0.0015749931335449219, 'goal': 'specs'},
                       {'phase': 'test', 'total': 0.0016660690307617188, 'goal': 'phase_total'},
                       {'phase': 'gen', 'total': 0.0038318634033203125, 'goal': 'protoc'},
                       {'phase': 'gen', 'total': 0.0020389556884765625, 'goal': 'antlr'},
                       {'phase': 'gen', 'total': 0.028632879257202148, 'goal': 'tweetypie-fetch'},
                       {'phase': 'gen', 'total': 0.0054290294647216797, 'goal': 'tweetypie-clean'},
                       {'phase': 'gen', 'total': 0.0022170543670654297, 'goal': 'thriftstore-dml-gen'},
                       {'phase': 'gen', 'total': 0.016566991806030273, 'goal': 'thrift'},
                       {'phase': 'gen', 'total': 0.058716773986816406, 'goal': 'phase_total'},
                       {'phase': 'cmd_total', 'total': 100, 'goal': 'cmd_total'}]
      self.assertEqual(actual_timings, expected_timings )


  def test_record_stats(self):
    timings =  {"compile": {'checkstyle': [0.00057005882263183594]}}
    self.set_up_mocks()
    with temporary_file() as temp_fd:
      temp_filename = temp_fd.name
      bs = BuildTimeStats(temp_filename)
      bs.record_stats(timings, 100)
      with open(temp_filename, 'r') as stats_file:
        stats = json.load(temp_fd)
        self.assertTrue(stats.has_key("cpu_time"))
        self.assertTrue(stats.has_key("timings"))
        self.assertTrue(stats.has_key("ip"))
        self.assertTrue(stats.has_key("env"))
        self.assertTrue(stats.has_key("network_counter"))
        self.assertEquals(stats["no_of_cpus"], 5)
        self.assertEquals(stats['git']['push'], "https://git.twitter.biz/science")
        self.assertEquals(stats['git']['branch'], "test_br")
    self.mox.VerifyAll()
    exp_calls = [{"/tmp/test/current_run.DEBUG": "/tmp/dummy/buildtime_uploader.global.DEBUG"},
                 {"/tmp/test/current_run.INFO": "/tmp/dummy/buildtime_uploader.global.INFO"},
                 {"/tmp/test/current_run.FATAL": "/tmp/dummy/buildtime_uploader.global.FATAL"},
                 {"/tmp/test/current_run.ERROR": "/tmp/dummy/buildtime_uploader.global.ERROR"},
                 {"/tmp/test/current_run.WARNING": "/tmp/dummy/buildtime_uploader.global.WARNING"}]
    self.assertEqual(bs.get_log_append_calls(), exp_calls)

  def test_record_stats_written(self):
    timings =  {"compile": {'checkstyle': [0.00057005882263183594]}}
    with temporary_file() as temp_fd:
      temp_filename = temp_fd.name
      bs = BuildTimeStats(temp_filename)
      self.set_up_mocks()

      bs.record_stats(timings, 100)
      self.mox.VerifyAll()
      self.mox.UnsetStubs()
      self.set_up_mocks()
      #Test append
      timings =  {"compile": {'checkstyle': [0.00057005882263183594]}}
      bs.record_stats(timings, 100)
      with open(temp_filename, 'r') as stats_file:
        lines = stats_file.readlines()
      self.assertEquals(len(lines), 2)
    self.mox.VerifyAll()
    exp_calls = [{"/tmp/test/current_run.DEBUG": "/tmp/dummy/buildtime_uploader.global.DEBUG"},
                 {"/tmp/test/current_run.INFO": "/tmp/dummy/buildtime_uploader.global.INFO"},
                 {"/tmp/test/current_run.FATAL": "/tmp/dummy/buildtime_uploader.global.FATAL"},
                 {"/tmp/test/current_run.ERROR": "/tmp/dummy/buildtime_uploader.global.ERROR"},
                 {"/tmp/test/current_run.WARNING": "/tmp/dummy/buildtime_uploader.global.WARNING"}]
    self.assertEqual(bs.get_log_append_calls(), exp_calls)

  def set_up_mocks(self, su=None):
    self.mox.StubOutWithMock(dirutil, 'safe_mkdtemp')
    dirutil.safe_mkdtemp().AndReturn('/tmp/test')
    self.mox.StubOutWithMock(log, 'init')
    log.init('/tmp/test/current_run').AndReturn(0)

    self.mox.StubOutWithMock(CommandUtil, 'execute_and_get_output')
    stub = CommandUtil.execute_and_get_output(['git','remote', '-v'])
    stub.AndReturn((0, dedent("""origin  https://git.twitter.biz/science (fetch)
    origin  https://git.twitter.biz/science (push)""")))
    stub2 = CommandUtil.execute_and_get_output(['git','rev-parse', '--abbrev-ref', 'HEAD'])
    stub2.AndReturn((0,"test_br"))

    self.mox.StubOutWithMock(psutil, 'cpu_percent')
    psutil.cpu_percent(interval=1).AndReturn(1.0)
    self.mox.StubOutWithMock(psutil, 'network_io_counters')
    psutil.network_io_counters().AndReturn("1000,10000,1000")
    self.mox.StubOutWithMock(psutil, 'NUM_CPUS')
    psutil.NUM_CPUS = 5

    self.mox.StubOutWithMock(socket, 'gethostname')
    socket.gethostname().AndReturn("localhost")
    self.mox.StubOutWithMock(socket, 'gethostbyname')
    socket.gethostbyname("localhost").AndReturn("localhost")

    self.mox.StubOutWithMock(sys, 'exit')
    sys.exit(0).AndReturn(0)
    self.mox.ReplayAll()
