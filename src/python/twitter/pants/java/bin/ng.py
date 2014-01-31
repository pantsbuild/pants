# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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
import re
import sys

from twitter.common import app
from twitter.common.log import LogOptions

from twitter.pants.java import NailgunClient


# TODO(John Sirois): Extract this to a file a release toolchain can edit.
VERSION = '0.0.2'


app.add_option('--nailgun-version',
               dest='just_version',
               default=False,
               action='store_true',
               help='print product version and exit')

app.add_option('--nailgun-showversion',
               dest='show_version',
               default=False,
               action='store_true',
               help='print product version and continue')

app.add_option('--nailgun-server',
               dest='ng_host',
               metavar='HOST',
               default=NailgunClient.DEFAULT_NG_HOST,
               help='to specify the address of the nailgun server (default is %default)')

app.add_option('--nailgun-port',
               dest='ng_port',
               metavar='PORT',
               default=NailgunClient.DEFAULT_NG_PORT,
               type='int',
               help='to specify the port of the nailgun server (default is %default)')

app.add_option('--nailgun-help',
               dest='show_help',
               default=False,
               action='store_true',
               help='print this message and exit')

app.set_usage('''%(command)s class [--nailgun-options] [args]
        (to execute a class)
 or: %(command)s alias [options] [args]
        (to execute an aliased class)
 or: alias [options] [args]
        (to execute an aliased class, where "alias"
         is both the alias for the class and a symbolic
         link to the ng client)
''' % dict(command=sys.argv[0]))


def main(args):
  options = app.get_options()
  if options.show_help:
    app.help()

  if options.show_version or options.just_version:
    print('Python NailGun client version %s' % VERSION)
    if options.just_version:
      sys.exit(0)

  # Assume ng.pex has been aliased to the command name
  command = re.compile('.pex$').sub('', os.path.basename(sys.argv[0]))
  args_index = 0

  # Otherwise the command name is the 1st arg
  if command == 'ng':
    if not args:
      app.help()

    command = args[0]
    args_index = 1

  ng = NailgunClient(host=options.ng_host, port=options.ng_port)
  try:
    result = ng(command, *args[args_index:], **os.environ)
    sys.exit(result)
  except ng.NailgunError as e:
    print('Problem executing command: %s' % e, file=sys.stderr)
    sys.exit(1)


LogOptions.disable_disk_logging()
app.main()
