import httplib
from multiprocessing.pool import ThreadPool
import socket
from twitter.common.contextutil import Timer


# So we don't ping the same netloc multiple times for multiple different caches
# (each Task has its own logical cache, even if they happen to share a netloc).
_global_pinger_cache = {}  # netloc -> rt time in secs.

class Pinger(object):
  UNREACHABLE = 999999

  def ping(self, netloc):
    """Time a single roundtrip to the netloc.

    Note that we don't use actual ICMP pings, because cmd-line ping is
    inflexible and platform-dependent, so shelling out to it is annoying,
    and the ICMP python lib can only be called by the superuser.
    """
    if netloc in _global_pinger_cache:
      return _global_pinger_cache[netloc]

    host, colon, portstr = netloc.partition(':')
    port = int(portstr) if portstr else None
    try:
      with Timer() as timer:
        conn = httplib.HTTPConnection(host, port, timeout=1)
        conn.request('HEAD', '/')   # Doesn't actually matter if this exists.
        conn.getresponse()
      rt_secs = timer.elapsed
    except socket.timeout:
      rt_secs = Pinger.UNREACHABLE
    _global_pinger_cache[netloc] = rt_secs
    return rt_secs

  def pings(self, netlocs):
    pool = ThreadPool(processes=len(netlocs))
    rt_secs = pool.map(self.ping, netlocs, chunksize=1)
    pool.close()
    pool.join()
    return zip(netlocs, rt_secs)


if __name__ == '__main__':
  print Pinger().pings(['pantscache', '10.100.10.20'])
