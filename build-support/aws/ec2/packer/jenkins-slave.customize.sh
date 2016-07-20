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
  https://github.com/pantsbuild/pants/blob/master/build-support/aws/ec2/packer/README.md
MOTD
MOTD_SCRIPT
sudo chmod +x /etc/update-motd.d/05-pantsbuild
sudo rm /etc/update-motd.d/10-help-text /etc/update-motd.d/51-cloudguest

# Setup a jenkins user and data dir to run slave builds with.
# See: http://cloudinit.readthedocs.io/en/latest/index.html
cat << JENKINS_CLOUD_INIT | sudo tee /etc/cloud/cloud.cfg.d/99_jenkins_cloud_init.cfg
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

users:
- default
- name: jenkins
  ssh_authorized_keys:
  - ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCWdCCh5LYbwKgFaEO2s1Hr+ONn55R+ViwDtCcLYGCdXMGFOD/0CEPYAPW2D2Cn29r1bxKryIGyA4RsAR5Op12AI9GwTXJF9nynjkeV+gKj2EMnqHzw53r1Rc5j8HMSTRXtjoRapjQ/BzNMHOkTVxwqdqnNmKlvRcFCpMCUA7Xz12q/4bhAHJ/TVnfZIDYBxNbvDfg8wKp0OHwnt2URbZJjKHll95wTJuiu72YoydiHEiCE2+Ja8l7/V54V7S8zoaJrxMDJiHJe2Yfx658D/olr83pGISytBXbhlxFFeVKnmj1l0sUpiUJSxlu2rq0tZdUJr/CYLae4r6mNKIoxxXB1

runcmd:
  - echo "$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone).fs-ff6daab6.efs.us-east-1.amazonaws.com:/ /mnt/efs nfs4 defaults" >> /etc/fstab
  - mkdir /mnt/efs
  - mount -a
  - mkdir -p /jenkins
  - chown jenkins:jenkins /jenkins
JENKINS_CLOUD_INIT
