from multiprocessing.pool import ThreadPool
import re
import subprocess

_float_pattern = r'\d+.?\d*'
_ping_pattern = r'round-trip min/avg/max/stddev = (%(flt)s)/(%(flt)s)/(%(flt)s)/(%(flt)s) ms' % \
                { 'flt': _float_pattern }
_ping_re = re.compile(_ping_pattern)


class Pinger(object):
  def ping(self, host):
    proc = subprocess.Popen(["ping", "-t", "1", "-c", "1", "-q", host],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, error = proc.communicate()
    out = out.strip()
    mo = _ping_re.search(out.strip())
    if mo:
      return float(mo.group(2))
    else:
      return None

  def pings(self, hosts):
    pool = ThreadPool(processes=len(hosts))
    res = pool.map(self.ping, hosts, chunksize=1)
    pool.close()
    pool.join()
    return zip(hosts, res)


if __name__ == '__main__':
  print pings(['pantscache', '10.100.10.20'])
