# Pantsbuild Jenkins Runbook

This runbook collects important facts and commands used to set up, administer and debug the
[Jenkins CI](https://jenkins.io/) infrastructure run by pantsbuild organization.

## Overview

Pantsbuild runs its own Jenkins cluster to service CI runs for its [github repos]
(https://github.com/pantsbuild) with `Jenkinsfile`s checked in to their root (currently only the
[pants](https://github.com/pantsbuild/pants/blob/master/Jenkinsfile) repo). It services both
`origin/master` commits and pull requests using a single Jenkins [multibranch]
(https://jenkins.io/doc/pipeline/#creating-multibranch-pipelines) [job]
(http://jenkins.pantsbuild.org/job/pantsbuild/).

## Jenkins master

The Jenkins master runs on `jenkins.pantsbuild.org`, a dedicated Amazon Linux machine running in
Amazon EC2. This machine is currently hand-configured. [Phabricator](http://phabricator.org/) is
[hosted](http://phabricator.pantsbuild.org/) on this machine in addition to Jenkins, but its
administration is not yet described here.

### Access

Access is via either the admin UI or ssh.

If your github account id has been added to the Jenkins ['Admin User Names']
(http://jenkins.pantsbuild.org/configureSecurity/) list you should be able to find management tools
at [Jenkins > Manage Jenkins](http://jenkins.pantsbuild.org/manage). These include tools to install
and upgrade plugins, manage plugin configuration, run arbitrary groovy scripts on the server and
more.

For ssh access, you can contact [#infra](https://pantsbuild.slack.com/messages/infra/) to add your
ssh public key to the `ec2-user`'s `~/.ssh/authorized_keys`. Once added you can ssh to the machine
with:

        $ ssh ec2-user@jenkins.pantsbuild.org

### Debugging

The Jenkins master runs on Amazon Linux (an rpm-based distribution), and debugging is via standard
linux tools and packages available in the rpm ecosystem (`ps`, `top`, `vmstat`, `iostat`, ...). If a
tool is missing during a debug session feel free to install it via `sudo yum install`, but generally
be cautious since this machine is singly homed with no current backup and as such is a single point
of failure and information loss.

### Maintenance

Packages can be upgraded using `sudo yum update` but care should be taken as noted above. Services
can be controlled via the `initctl` suite of tools (`sudo service stop`, `sudo service start`,
etc...) and logs can be found as plain text files under `/var/log/`.

#### nginx

[Nginx](https://www.nginx.com/) is used to serve Jenkins static content and act as a reverse proxy
for the jenkins java service. Although the Apache httpd is installed on the machine, it is disabled
and can be ignored.

The nginx logs are found under `/var/log/nginx/` and the service name is `nginx`; so
`sudo service nginx ...` can be used to control the service:

        $ sudo service nginx
        Usage: /etc/init.d/nginx {start|stop|reload|configtest|status|force-reload|upgrade|restart|reopen_logs}

The serving configuration for Jenkins is found in `/etc/nginx/conf.d/pants-jenkins.conf`.

The `nginx` package is also named `nginx`; so upgrades can be done via `sudo yum update nginx`. As
noted above, care should be taken to read through change logs before upgrading.

#### jenkins java service

This service runs the Jenkins master and its [web UI](http://jenkins.pantsbuild.org). Logs are found
under `/var/log/jenkins/` and in the UI at [Jenkins > Manage Jenkins > System Log > All Logs]
(http://jenkins.pantsbuild.org/log/all). The service name is `jenkins`; so
`sudo service jenkins ...` can be used to control the service:

        $ sudo service jenkins
        Usage: /etc/init.d/jenkins {start|stop|status|try-restart|restart|force-reload|reload|probe}

The package is also named `jenkins`; so upgrades can be done via `sudo yum update jenkins`. As noted
above, care should be taken; so read through change logs before upgrading.

## Jenkins slaves

We use both ephemeral linux slaves run in Amazon EC2 and dedicated mac slave(s) hosted by
[macstadium.com](http://macstadium.com). All slaves are configured with a `jenkins` user that runs
the CI job shards allocated to the slave. Slaves all are configured with a workdir of `/jenkins`
where the shard workspaces can be found.

### Linux (Amazon EC2)

The linux slaves are ephemeral and automatically controlled by the Jenkins [Amazon EC2 plugin]
(https://wiki.jenkins-ci.org/display/JENKINS/Amazon+EC2+Plugin). As such, these slaves can be
treated, to some degree, roughly. If you kill a slave, another one will be launched by the plugin
after it notices the slave is non-responsive. The cost is just the failure of the individual CI jobs
running on the slaves you kill. Users will need to re-run those CI jobs.

#### Access

You can access slaves over ssh, but you'll need the slave host name or IP address and an appropriate
ssh key. You can contact [#infra](https://pantsbuild.slack.com/messages/infra/) for access to the
key.

You can find the slave host name or IP address from the [AWS EC2 instances console]
(https://console.aws.amazon.com/ec2/v2/home?region=us-east-1#Instances:sort=instanceState), the
Jenkins node detail page or from the CI job shard console logs.

To find the host from the Jenkins node detail page, navigate to
[Jenkins > Manage Jenkins > Manage Nodes](http://jenkins.pantsbuild.org/computer/). Here you can
click on the 'Pants Ephemeral EC2 Worker' node of interest's main page and then click on the 'Log'
link in the left-hand pane. You'll find log lines like the following showing the Jenkins master
attempting to connect to the slave:

        INFO: Connecting to ec2-52-91-244-208.compute-1.amazonaws.com on port 22, with timeout 10000.
        May 11, 2016 7:24:48 PM null
        INFO: Failed to connect via ssh: There was a problem while connecting to ec2-52-91-244-208.compute-1.amazonaws.com:22
        May 11, 2016 7:24:48 PM null
        INFO: Waiting for SSH to come up. Sleeping 5.

You can use the host name listed, in this case `ec2-52-91-244-208.compute-1.amazonaws.com`.

To find the host from the CI job shard logs, click on the 'Pipeline Steps' link in the left hand
pane of a CI job. Scroll to a shard of interest and click on its 'Shell Script' terminal icon. You
should see something like this at the top of the logs:

        [PR-3402] Running shell script
        + ./build-support/ci/print_node_info.sh
        Running on:
              node id: (Production) Pants Ephemeral EC2 Worker (sir-029m8twl)
               ami id: ami-158c6078
          instance id: i-5c6f3ddb
                 host: 54.243.18.161
                   os: Linux ip-172-31-14-35 4.4.0-21-generic #37-Ubuntu SMP Mon Apr 18 18:33:37 UTC 2016 x86_64 x86_64 x86_64 GNU/Linux
        + ./build-support/bin/ci.sh -cjlpn

        [== 00:00 CI BEGINS ==]
        ...

Here the IP address can be found in the `host` field, `54.243.18.161` in this case.

Once you have the key and host you can ssh to the machine with:

        $ ssh -i ~/.ssh/pantsbuild-jenkins-bot.pem ubuntu@host

#### Debugging

The linux slaves run on Ubuntu 16.04 LTS and as such, debugging is via standard linux tools and
packages available in the Ubuntu/Debian ecosystem (`ps`, `top`, `vmstat`, `iostat`, ...). If a tool
is missing during a debug session on a slave, feel free to install it via `sudo apt-get install`.
Since the slaves are ephemeral your tool installation will be as well.  If the tool is important
enough you think it should be readily available in the future, feel free to [modify the AMI]
(/build-support/aws/ec2/packer/README.md).

The slaves run no special services needed by Jenkins save for an ssh server which is part of the
base image.

#### Maintenance

Our linux slaves run on a custom AMI that includes all the necessary pants dependencies and the
setup needed for the Jenkins master to connect and run jobs. AMI modification is described [here]
(/build-support/aws/ec2/packer/README.md). These slaves are launched on-demand by the
[Jenkins Amazon EC2 plugin](https://wiki.jenkins-ci.org/display/JENKINS/Amazon+EC2+Plugin) which
automatically tears down instances (to save on AWS charges) when demand drops.

### Mac (macstadium.com)

The mac slave(s) are dedicated instances hosted at [macstadium.com](http://macstadium.com). These
machines are currently hand-configured, and as such maintenance should be treated with extra care.

#### Access

You can access mac slaves over ssh or via remote desktop. You'll need the slave host name or IP
address for both and an appropriate ssh key if using ssh. You can contact [#infra]
(https://pantsbuild.slack.com/messages/infra/) for access to the key.

You can find the mac node ip using the [Jenkins > Manage Jenkins > Manage Nodes]
(http://jenkins.pantsbuild.org/computer/) UI as described above for linux nodes.

Once you have the key and host you can ssh to the machine with:

        $ ssh -i ~/.ssh/pantsbuild-jenkins-bot.pem administrator@mac-mini1

Remote desktop access will require the administrator password which you can ask for access to in
[#infra](https://pantsbuild.slack.com/messages/infra/).

#### Debugging

The mac slaves run OSX 10.10 and are configured with a working brew install and no XCode install. As
such debugging is via standard unix/BSD tools (`ps`, `top`, `launchctl`, ...) as well as
OSX-specific tooling (`sysadminctl`, `plutil`, ...). If a tool is missing during a debug session on
a slave, feel free to install it (`brew install` or `brew cask install`). For consistency sake,
please install the tool on all mac slaves.

The slaves have a power control panel at [macstadium.com](http://macstadium.com) that can be
accessed with our account to power-cycle nodes.  Contact [#infra]
(https://pantsbuild.slack.com/messages/infra/) for account info.

#### Maintenance

Packages can be inspected, installed and upgraded with [`brew`](http://brew.sh/). The current
package list is the minimal set needed to support basic pants CI runs:

        $ brew list
        brew-cask	gdbm		git		openssl		python		readline	sqlite		wget
        $ brew cask list
        java
