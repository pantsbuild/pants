# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import BaseHTTPServer
import itertools
import json
import logging
import mimetypes
import os
import pkgutil
import re
import urllib
import urlparse
from collections import namedtuple
from datetime import date, datetime

import pystache
from six.moves import range

from pants.base.build_environment import get_buildroot
from pants.base.mustache import MustacheRenderer
from pants.base.run_info import RunInfo
from pants.pantsd.process_manager import ProcessManager
from pants.stats.statsdb import StatsDBFactory


logger = logging.getLogger(__name__)

# Google Prettyprint plugin files.
PPP_RE = re.compile("""^lang-.*\.js$""")


class PantsHandler(BaseHTTPServer.BaseHTTPRequestHandler):
  """A handler that demultiplexes various pants reporting URLs."""

  def __init__(self, settings, renderer, request, client_address, server):
    self._settings = settings  # An instance of ReportingServer.Settings.
    self._root = self._settings.root
    self._renderer = renderer
    self._client_address = client_address
    # The underlying handlers for specific URL prefixes.
    self._GET_handlers = [
      ('/runs/', self._handle_runs),  # Show list of known pants runs.
      ('/run/', self._handle_run),  # Show a report for a single pants run.
      ('/stats/', self._handle_stats),  # Show a stats analytics page.
      ('/statsdata/', self._handle_statsdata),  # Get JSON stats data.
      ('/browse/', self._handle_browse),  # Browse filesystem under build root.
      ('/content/', self._handle_content),  # Show content of file.
      ('/assets/', self._handle_assets),  # Statically serve assets (css, js etc.)
      ('/poll', self._handle_poll),  # Handle poll requests for raw file content.
      ('/latestrunid', self._handle_latest_runid),  # Return id of latest pants run.
      ('/favicon.ico', self._handle_favicon)  # Return favicon.
    ]
    BaseHTTPServer.BaseHTTPRequestHandler.__init__(self, request, client_address, server)

  def do_GET(self):
    """GET method implementation for BaseHTTPRequestHandler."""
    if not self._client_allowed():
      return

    try:
      (_, _, path, query, _) = urlparse.urlsplit(self.path)
      params = urlparse.parse_qs(query)
      # Give each handler a chance to respond.
      for prefix, handler in self._GET_handlers:
        if self._maybe_handle(prefix, handler, path, params):
          return
      # If no path specified, default to showing the list of all runs.
      if path == '/':
        self._handle_runs('', {})
        return

      self._send_content('Invalid GET request {}'.format(self.path), 'text/html', code=400)
    except (IOError, ValueError):
      pass  # Printing these errors gets annoying, and there's nothing to do about them anyway.
      #sys.stderr.write('Invalid GET request {}'.format(self.path))

  def _handle_runs(self, relpath, params):
    """Show a listing of all pants runs since the last clean-all."""
    runs_by_day = self._partition_runs_by_day()
    args = self._default_template_args('run_list')
    args['runs_by_day'] = runs_by_day
    self._send_content(self._renderer.render_name('base', args), 'text/html')

  def _handle_run(self, relpath, params):
    """Show the report for a single pants run."""
    args = self._default_template_args('run')
    run_id = relpath
    run_info = self._get_run_info_dict(run_id)
    if run_info is None:
      args['no_such_run'] = relpath
      if run_id == 'latest':
        args['is_latest'] = 'none'
    else:
      report_abspath = run_info['default_report']
      report_relpath = os.path.relpath(report_abspath, self._root)
      report_dir = os.path.dirname(report_relpath)
      self_timings_path = os.path.join(report_dir, 'self_timings')
      cumulative_timings_path = os.path.join(report_dir, 'cumulative_timings')
      artifact_cache_stats_path = os.path.join(report_dir, 'artifact_cache_stats')
      run_info['timestamp_text'] = \
        datetime.fromtimestamp(float(run_info['timestamp'])).strftime('%H:%M:%S on %A, %B %d %Y')
      args.update({'run_info': run_info,
                   'report_path': report_relpath,
                   'self_timings_path': self_timings_path,
                   'cumulative_timings_path': cumulative_timings_path,
                   'artifact_cache_stats_path': artifact_cache_stats_path})
      if run_id == 'latest':
        args['is_latest'] = run_info['id']
      args.update({
        'collapsible': lambda x: self._renderer.render_callable('collapsible', x, args)
      })
    self._send_content(self._renderer.render_name('base', args), 'text/html')

  def _handle_stats(self, relpath, params):
    """Show stats for pants runs in the statsdb."""
    args = self._default_template_args('stats')
    self._send_content(self._renderer.render_name('base', args), 'text/html')

  def _handle_statsdata(self, relpath, params):
    """Show stats for pants runs in the statsdb."""
    statsdb = StatsDBFactory.global_instance().get_db()
    statsdata = list(statsdb.get_aggregated_stats_for_cmd_line('cumulative_timings', '%'))
    self._send_content(json.dumps(statsdata), 'application/json')

  def _handle_browse(self, relpath, params):
    """Handle requests to browse the filesystem under the build root."""
    abspath = os.path.normpath(os.path.join(self._root, relpath))
    if not abspath.startswith(self._root):
      raise ValueError  # Prevent using .. to get files from anywhere other than root.
    if os.path.isdir(abspath):
      self._serve_dir(abspath, params)
    elif os.path.isfile(abspath):
      self._serve_file(abspath, params)

  def _handle_content(self, relpath, params):
    """Render file content for pretty display."""
    abspath = os.path.normpath(os.path.join(self._root, relpath))
    if os.path.isfile(abspath):
      with open(abspath, 'r') as infile:
        content = infile.read()
    else:
      content = 'No file found at {}'.format(abspath)
    content_type = mimetypes.guess_type(abspath)[0] or 'text/plain'
    if not content_type.startswith('text/') and not content_type == 'application/xml':
      # Binary file. Display it as hex, split into lines.
      n = 120  # Display lines of this max size.
      content = repr(content)[1:-1]  # Will escape non-printables etc, dropping surrounding quotes.
      content = '\n'.join([content[i:i + n] for i in range(0, len(content), n)])
      prettify = False
      prettify_extra_langs = []
    else:
      prettify = True
      if self._settings.assets_dir:
        prettify_extra_dir = os.path.join(self._settings.assets_dir, 'js', 'prettify_extra_langs')
        prettify_extra_langs = [{'name': x} for x in os.listdir(prettify_extra_dir)]
      else:
        # TODO: Find these from our package, somehow.
        prettify_extra_langs = []
    linenums = True
    args = {'prettify_extra_langs': prettify_extra_langs, 'content': content,
            'prettify': prettify, 'linenums': linenums}
    self._send_content(self._renderer.render_name('file_content', args), 'text/html')

  def _handle_assets(self, relpath, params):
    """Statically serve assets: js, css etc."""
    if self._settings.assets_dir:
      abspath = os.path.normpath(os.path.join(self._settings.assets_dir, relpath))
      with open(abspath, 'r') as infile:
        content = infile.read()
    else:
      content = pkgutil.get_data(__name__, os.path.join('assets', relpath))
    content_type = mimetypes.guess_type(relpath)[0] or 'text/plain'
    self._send_content(content, content_type)

  def _handle_poll(self, relpath, params):
    """Handle poll requests for raw file contents."""
    request = json.loads(params.get('q')[0])
    ret = {}
    # request is a polling request for multiple files. For each file:
    #  - id is some identifier assigned by the client, used to differentiate the results.
    #  - path is the file to poll.
    #  - pos is the last byte position in that file seen by the client.
    for poll in request:
      _id = poll.get('id', None)
      path = poll.get('path', None)
      pos = poll.get('pos', 0)
      if path:
        abspath = os.path.normpath(os.path.join(self._root, path))
        if os.path.isfile(abspath):
          with open(abspath, 'r') as infile:
            if pos:
              infile.seek(pos)
            content = infile.read()
            ret[_id] = content
    self._send_content(json.dumps(ret), 'application/json')

  def _handle_latest_runid(self, relpath, params):
    """Handle request for the latest run id.

    Used by client-side javascript to detect when there's a new run to display.
    """
    latest_runinfo = self._get_run_info_dict('latest')
    if latest_runinfo is None:
      self._send_content('none', 'text/plain')
    else:
      self._send_content(latest_runinfo['id'], 'text/plain')

  def _handle_favicon(self, relpath, params):
    """Statically serve the favicon out of the assets dir."""
    self._handle_assets('favicon.ico', params)

  def _partition_runs_by_day(self):
    """Split the runs by day, so we can display them grouped that way."""
    run_infos = self._get_all_run_infos()
    for x in run_infos:
      ts = float(x['timestamp'])
      x['time_of_day_text'] = datetime.fromtimestamp(ts).strftime('%H:%M:%S')

    def date_text(dt):
      delta_days = (date.today() - dt).days
      if delta_days == 0:
        return 'Today'
      elif delta_days == 1:
        return 'Yesterday'
      elif delta_days < 7:
        return dt.strftime('%A')  # Weekday name.
      else:
        d = dt.day % 10
        suffix = 'st' if d == 1 else 'nd' if d == 2 else 'rd' if d == 3 else 'th'
        return dt.strftime('%B %d') + suffix  # E.g., October 30th.

    keyfunc = lambda x: datetime.fromtimestamp(float(x['timestamp']))
    sorted_run_infos = sorted(run_infos, key=keyfunc, reverse=True)
    return [{'date_text': date_text(dt), 'run_infos': [x for x in infos]}
            for dt, infos in itertools.groupby(sorted_run_infos, lambda x: keyfunc(x).date())]

  def _get_run_info_dict(self, run_id):
    """Get the RunInfo for a run, as a dict."""
    run_info_path = os.path.join(self._settings.info_dir, run_id, 'info')
    if os.path.exists(run_info_path):
      # We copy the RunInfo as a dict, so we can add stuff to it to pass to the template.
      return RunInfo(run_info_path).get_as_dict()
    else:
      return None

  def _get_all_run_infos(self):
    """Find the RunInfos for all runs since the last clean-all."""
    info_dir = self._settings.info_dir
    if not os.path.isdir(info_dir):
      return []
    paths = [os.path.join(info_dir, x) for x in os.listdir(info_dir)]

    # We copy the RunInfo as a dict, so we can add stuff to it to pass to the template.
    # We filter only those that have a timestamp, to avoid a race condition with writing
    # that field.
    return filter(lambda d: 'timestamp' in d, [RunInfo(os.path.join(p, 'info')).get_as_dict()
            for p in paths if os.path.isdir(p) and not os.path.islink(p)])

  def _serve_dir(self, abspath, params):
    """Show a directory listing."""
    relpath = os.path.relpath(abspath, self._root)
    breadcrumbs = self._create_breadcrumbs(relpath)
    entries = [{'link_path': os.path.join(relpath, e), 'name': e} for e in os.listdir(abspath)]
    args = self._default_template_args('dir')
    args.update({'root_parent': os.path.dirname(self._root),
                 'breadcrumbs': breadcrumbs,
                 'entries': entries,
                 'params': params})
    self._send_content(self._renderer.render_name('base', args), 'text/html')

  def _serve_file(self, abspath, params):
    """Show a file.

    The actual content of the file is rendered by _handle_content.
    """
    relpath = os.path.relpath(abspath, self._root)
    breadcrumbs = self._create_breadcrumbs(relpath)
    link_path = urlparse.urlunparse([None, None, relpath, None, urllib.urlencode(params), None])
    args = self._default_template_args('file')
    args.update({'root_parent': os.path.dirname(self._root),
                 'breadcrumbs': breadcrumbs,
                 'link_path': link_path})
    self._send_content(self._renderer.render_name('base', args), 'text/html')

  def _send_content(self, content, content_type, code=200):
    """Send content to client."""
    self.send_response(code)
    self.send_header('Content-Type', content_type)
    self.send_header('Content-Length', str(len(content)))
    self.end_headers()
    self.wfile.write(content)

  def _client_allowed(self):
    """Check if client is allowed to connect to this server."""
    client_ip = self._client_address[0]
    if not client_ip in self._settings.allowed_clients and \
       not 'ALL' in self._settings.allowed_clients:
      self._send_content('Access from host {} forbidden.'.format(client_ip), 'text/html')
      return False
    return True

  def _maybe_handle(self, prefix, handler, path, params, data=None):
    """Apply the handler if the prefix matches."""
    if path.startswith(prefix):
      relpath = path[len(prefix):]
      if data:
        handler(relpath, params, data)
      else:
        handler(relpath, params)
      return True
    else:
      return False

  def _create_breadcrumbs(self, relpath):
    """Create filesystem browsing breadcrumb navigation.

    That is, make each path segment into a clickable element that takes you to that dir.
    """
    if relpath == '.':
      breadcrumbs = []
    else:
      path_parts = [os.path.basename(self._root)] + relpath.split(os.path.sep)
      path_links = ['/'.join(path_parts[1:i + 1]) for i, name in enumerate(path_parts)]
      breadcrumbs = [{'link_path': link_path, 'name': name}
                     for link_path, name in zip(path_links, path_parts)]
    return breadcrumbs

  def _default_template_args(self, content_template):
    """Initialize template args."""
    def include(text, args):
      template_name = pystache.render(text, args)
      return self._renderer.render_name(template_name, args)
    # Our base template calls include on the content_template.
    ret = {'content_template': content_template}
    ret['include'] = lambda text: include(text, ret)
    return ret

  def log_message(self, fmt, *args):
    """Silence BaseHTTPRequestHandler's logging."""


class ReportingServer(object):
  """Reporting Server HTTP server."""

  class Settings(namedtuple('Settings', ['info_dir', 'template_dir', 'assets_dir', 'root',
                                         'allowed_clients'])):
    """Reporting server settings.

       info_dir: path to dir containing RunInfo files.
       template_dir: location of mustache template files. If None, the templates
                     embedded in our package are used.
       assets_dir: location of assets (js, css etc.) If None, the assets
                   embedded in our package are used.
       root: build root.
       allowed_clients: list of ips or ['ALL'].
    """

  def __init__(self, port, settings):
    renderer = MustacheRenderer(settings.template_dir, __name__)

    class MyHandler(PantsHandler):

      def __init__(self, request, client_address, server):
        PantsHandler.__init__(self, settings, renderer, request, client_address, server)

    self._httpd = BaseHTTPServer.HTTPServer(('', port), MyHandler)
    self._httpd.timeout = 0.1  # Not the network timeout, but how often handle_request yields.

  def server_port(self):
    return self._httpd.server_port

  def start(self):
    self._httpd.serve_forever()


class ReportingServerManager(ProcessManager):

  def __init__(self, context=None, options=None):
    ProcessManager.__init__(self, name='reporting_server')
    self.context = context
    self.options = options

  def post_fork_child(self):
    """Post-fork() child callback for ProcessManager.daemonize()."""
    # The server finds run-specific info dirs by looking at the subdirectories of info_dir,
    # which is conveniently and obviously the parent dir of the current run's info dir.
    info_dir = os.path.dirname(self.context.run_tracker.run_info_dir)

    settings = ReportingServer.Settings(info_dir=info_dir,
                                        root=get_buildroot(),
                                        template_dir=self.options.template_dir,
                                        assets_dir=self.options.assets_dir,
                                        allowed_clients=self.options.allowed_clients)

    server = ReportingServer(self.options.port, settings)

    self.write_socket(server.server_port())

    # Block forever.
    server.start()
