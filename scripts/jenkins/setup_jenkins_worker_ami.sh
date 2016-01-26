#!/bin/sh

sudo yum update -y
sudo yum install -y \
  automake \
  gcc \
  gcc-c++ \
  git \
  htop \
  iotop \
  java-1.7.0-openjdk-devel \
  java-1.8.0-openjdk-devel \
  make \
  tmux

sudo useradd --home /jenkins -M jenkins

sudo mkdir -p /usr/local/jenkins
sudo mkdir /usr/local/jenkins/supervisor
sudo chown $(whoami) /usr/local/jenkins/supervisor
virtualenv /usr/local/jenkins/supervisor
/usr/local/jenkins/supervisor/bin/pip install supervisor

/usr/local/jenkins/supervisor/bin/echo_supervisord_conf > /tmp/supervisord.conf
cat <<EOL >> /tmp/supervisord.conf

[program:agent]
command=/usr/local/jenkins/run.sh
user=jenkins
environment=HOME="/jenkins",USER="jenkins"

EOL

sudo mv /tmp/supervisord.conf /usr/local/jenkins/supervisord.conf

# echo "/usr/local/jenkins/supervisor/bin/supervisord -c /usr/local/jenkins/supervisord.conf" | sudo tee -a /etc/rc.local
# sudo mkfs.ext4 -E nodiscard /dev/sdb
# sudo mkdir /jenkins
# sudo mount -o discard /dev/sdb /jenkins
# sudo chown jenkins:jenkins /jenkins

sudo mkdir /usr/local/jenkins/scripts
sudo chown $(whoami) /usr/local/jenkins/scripts

cat <<EOL > /usr/local/jenkins/scripts/get_jenkins_url.py
#!/usr/bin/python
import os
import httplib
import string
import sys

conn = httplib.HTTPConnection("169.254.169.254")
conn.request("GET", "/latest/user-data")
userdata = conn.getresponse().read()

for arg in string.split(userdata, "&"):
    if arg.split("=")[0] == "JENKINS_URL":
        sys.stdout.write(arg.split("=")[1])
        sys.exit(0)

raise Exception("Couldn't find JENKINS_URL.  userdata: {}".format(userdata))
EOL

chmod +x /usr/local/jenkins/scripts/get_jenkins_url.py

cat <<EOL > /usr/local/jenkins/scripts/get_slave_name.py
#!/usr/bin/python
import os
import httplib
import string
import sys

conn = httplib.HTTPConnection("169.254.169.254")
conn.request("GET", "/latest/user-data")
userdata = conn.getresponse().read()

for arg in string.split(userdata, "&"):
    if arg.split("=")[0] == "SLAVE_NAME":
        sys.stdout.write(arg.split("=")[1])
        sys.exit(0)

raise Exception("Couldn't find SLAVE_NAME.  userdata: {}".format(userdata))
EOL

chmod +x /usr/local/jenkins/scripts/get_slave_name.py
