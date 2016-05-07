#!/bin/bash
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -o errexit
set -o pipefail

# Add some helpful info to the MOTD, cull some Ubuntu cruft.
# ===
cat << MOTD_SCRIPT | sudo tee /etc/update-motd.d/05-pantsbuild
#!/bin/sh
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
cat << MOTD

*** This is a pantsbuild.org Jenkins Slave ***

To configure, see:
  https://github.com/pantsbuild/pants/blob/master/build-support/packer/README.md
MOTD
MOTD_SCRIPT
sudo chmod +x /etc/update-motd.d/05-pantsbuild
sudo rm /etc/update-motd.d/10-help-text /etc/update-motd.d/51-cloudguest

# Setup a jenkins user and data dir to run slave builds with.
# ===
sudo adduser --system --group --home /home/jenkins --shell /bin/bash jenkins

# See: http://cloudinit.readthedocs.io/en/latest/index.html
cat << R3XLARGE_FIX | sudo tee /etc/cloud/cloud.cfg.d/99_fix_ephemeral_mounting.cfg
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This is a fix for the r3.xlarge instances we use as described here:
#   https://forums.aws.amazon.com/thread.jspa?threadID=156342
#
# These instances come with unformatted local SSDs with TRIM support as outlined here:
#   http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/InstanceStorage.html
#
# Although the fstab has an entry that mounts the local SSD epehemeral device to /mnt
# this fails since the device is unformatted, so we format it here on 1st boot.
#
# Formatting advice taken from:
#   http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ssd-instance-store.html
bootcmd:
- [ cloud-init-per, once, format_instance_storage, mkfs.ext4, '-E', nodiscard, /dev/xvdb ]
- [ cloud-init-per, once, make_instance_storage_mount_point, mkdir, '-p', /mnt/xvdb ]

mounts:
- [ xvdb, /mnt/xvdb, ext4, 'defaults,nofail,discard', 0, 2 ]
R3XLARGE_FIX
# The symlink target does not exist yet but will be filled in by the jenkins-slave-connect.service
# Before it attempts to use it.  See UNIT_FILE section below.
sudo ln -s /mnt/xvdb/jenkins /jenkins

# Install a small service that attempts to connect to the Jenkins master via JNLP.
# ===
sudo -u jenkins mkdir -p /home/jenkins/bin
cat << JNLP_SERVICE | sudo -u jenkins tee /home/jenkins/bin/jenkins-slave-connect
#!/usr/bin/python2.7
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Based on http://[JENKINS_URL]/plugin/ec2/AMI-Scripts/ubuntu-init.py

from __future__ import print_function

import base64
import os
import re
import shutil
import string
import sys

import xml.etree.ElementTree as ET

import requests


def die(message, *args, **kwargs):
  print(message.format(*args, **kwargs), file=sys.stderr)
  sys.exit(1)


if len(sys.argv) != 2:
  die('Usage: {} WORKDIR', sys.argv[0])
workdir = sys.argv[1]

# This IP/HTTP endpoint is EC2 magic avaialable on every EC2 node and its used by
# the Jenkins EC2 plugin.  See here for more details:
#   http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html
response = requests.get('http://169.254.169.254/latest/user-data')
if response.status_code != requests.codes.ok:
  die('Failed to retrieve /latest/user-data: {}', response.status_code)
args = string.split(response.text, '&')

# The Jenkins Amazon EC2 plugin arranges JENKINS_URL and SLAVE_NAME automatically
# and we configure 'User Data' in the plugin which populates USER_DATA.
required_keys = ('JENKINS_URL', 'SLAVE_NAME', 'USER_DATA')
params = {'workdir': workdir}
username, password = None, None
for arg in args:
  key, value = arg.split('=', 1)
  if key == 'JENKINS_URL':
    params[key] = re.sub(r'/$', '', value)
  elif key == 'USER_DATA':
    value = base64.b64decode(value)
    username, password = value.split(':', 1)
  params[key] = value

missing_keys = sorted(k for k in required_keys if k not in params)
if missing_keys:
  die('The following required EC2 /latest/user-data keys are missing:\n\t{}',
      '\n\t'.join(missing_keys))

response = requests.get('{JENKINS_URL}/jnlpJars/slave.jar'.format(**params), stream=True)
if response.status_code != requests.codes.ok:
  die('Failed to fetch slave.jar: {}', response.status_code)
with open('{workdir}/slave.jar'.format(**params), 'wb') as fp:
  response.raw.decode_content = True
  shutil.copyfileobj(response.raw, fp)

response = requests.get('{JENKINS_URL}/computer/{SLAVE_NAME}/config.xml'.format(**params),
                        auth=(username, password))
# This is optional data for Jenkinsfile nodes, so only process it if available.
if response.status_code == requests.codes.ok:
  labels = ' '.join(l.text for l in ET.fromstring(response.text).findall('label'))
  os.putenv('JENKINS_LABELS', labels)

os.system('java -jar {workdir}/slave.jar -noReconnect'
          ' -jnlpUrl {JENKINS_URL}/computer/{SLAVE_NAME}/slave-agent.jnlp'
          ' -jnlpCredentials {USER_DATA}'
          .format(**params))
JNLP_SERVICE
sudo -u jenkins chmod +x /home/jenkins/bin/jenkins-slave-connect

cat << UNIT_FILE | sudo tee /etc/systemd/system/jenkins-slave-connect.service
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# See systemd unit file docs for more info:
#   https://www.freedesktop.org/software/systemd/man/systemd.unit.html
#   https://www.freedesktop.org/software/systemd/man/systemd.service.html
#   https://www.freedesktop.org/software/systemd/man/systemd.special.html

[Unit]
Description=Starts Jenkins Master JNLP connector.
After=network-online.target mnt-xvdb.mount
Requires=network-online.target mnt-xvdb.mount

# This disables re-start rate-limiting.  Since our slave instances
# are dedicated to this service and this service alone, it makes sense
# to allow the JNLP connector to restart as much as it needs until it
# connects or the Jenkins master kills the slave on timeout from its end.
StartLimitInterval=0

[Service]
Type=simple

# These run as root and in sequence; importantly they are idempotent.
PermissionsStartOnly=true
ExecStartPre=/bin/mkdir -p /mnt/xvdb/jenkins
ExecStartPre=/bin/chown jenkins:jenkins /mnt/xvdb/jenkins

# This runs as jenkins.
User=jenkins
ExecStart=/home/jenkins/bin/jenkins-slave-connect /mnt/xvdb/jenkins

# Ideally we'd use on-failure but the jenkins.jar exits 0 for error conditions.
# Since a Jenkins Slave should always be JNLP connected to the master to be useful,
# this is probably a fine setting as a result.
Restart=always

[Install]
WantedBy=multi-user.target
UNIT_FILE
# Make sure the service auto-starts.
sudo systemctl enable jenkins-slave-connect.service

