#!/bin/bash
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -o errexit
set -o pipefail

export DEBIAN_FRONTEND=noninteractive

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
cat << JNLP_SERVICE | sudo -u jenkins tee /home/jenkins/bin/jenkins-slave-connect.sh
#!/usr/bin/python2.7
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Based on http://$JENKINS_URL/plugin/ec2/AMI-Scripts/ubuntu-init.py

from __future__ import print_function

import base64
import httplib
import os
import re
import string
import sys

if len(sys.argv) != 2:
  print('Usage: {} WORKDIR'.format(sys.argv[0]), file=sys.stderr)
  sys.exit(1)
workdir = sys.argv[1]

# This IP/HTTP endpoint is EC2 magic avaialable on every EC2 node and its used by
# the Jenkins EC2 plugin.  See here for more details:
#   http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html
conn = httplib.HTTPConnection('169.254.169.254')
conn.request('GET', '/latest/user-data')
response = conn.getresponse()
userdata = response.read()

args = string.split(userdata, '&')

# The Jenkins Amazon EC2 plugin arranges JENKINS_URL and SLAVE_NAME automatically
# and we configure 'User Data' in the plugin which populates USER_DATA.
required_keys = ('JENKINS_URL', 'SLAVE_NAME', 'USER_DATA')
params = {'workdir': workdir}
for arg in args:
  key, value = arg.split('=', 1)
  if key == 'JENKINS_URL':
    value = re.sub(r'/$', '', value)
  elif key == 'SLAVE_NAME':
    slaveName = value
  elif key == 'USER_DATA':
    value = base64.b64decode(value)
  params[key] = value

missing_keys = sorted(k for k in required_keys if k not in params)
if missing_keys:
  print('The following required EC2 /latest/user-data keys are missing:\n\t{}'
        .format('\n\t'.join(missing_keys)), file=sys.stderr)
  sys.exit(1)

os.system('wget {JENKINS_URL}/jnlpJars/slave.jar -O {workdir}/slave.jar'.format(**params))
os.system('java -jar {workdir}/slave.jar -noReconnect'
          ' -jnlpUrl {JENKINS_URL}/computer/{SLAVE_NAME}/slave-agent.jnlp'
          ' -jnlpCredentials {USER_DATA}'
          .format(**params))
JNLP_SERVICE
sudo -u jenkins chmod +x /home/jenkins/bin/jenkins-slave-connect.sh

cat << UNIT_FILE | sudo tee /etc/systemd/system/jenkins-slave-connect.service
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# See systemd unit file docs for more info:
#   https://www.freedesktop.org/software/systemd/man/systemd.unit.html
#   https://www.freedesktop.org/software/systemd/man/systemd.service.html

[Unit]
Description=Starts Jenkins Master JNLP connector.
After=network.target local-fs.target

[Service]
Type=simple

# These runs as root and in sequence; importantly they are idempotent.
PermissionsStartOnly=true
ExecStartPre=/bin/mkdir -p /mnt/xvdb/jenkins
ExecStartPre=/bin/chown jenkins:jenkins /mnt/xvdb/jenkins

# This runs as jenkins.
User=jenkins
ExecStart=/home/jenkins/bin/jenkins-slave-connect.sh /mnt/xvdb/jenkins

# Ideally we'd use on-failure but the jenkins.jar exits 0 for error conditions.
# Since a Jenkins Slave should always be JNLP connected to the master to be useful.
# this is probably a fine setting as a result.
Restart=always

[Install]
WantedBy=multi-user.target
UNIT_FILE
# Make sure the service auto-starts.
sudo systemctl enable jenkins-slave-connect.service

