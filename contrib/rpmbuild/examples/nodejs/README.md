
## Node RPM Instructions
This is built from a node source tarball. Generally we try to consume these from our mirror of the upstream Pants tools.
See [tool bootstrapping README](/build-support/README.md) for details if you need to update to a version not yet supported by Pants binaries.


#### Build Instructions

1. Download the desired version [here](https://github.com/nodejs/node/releases) (packaged as a tar.gz).
1. Upload to Bodega, mimicking the existing directory structure and stable file name:
    * e.g. `/data/appdata/bodega/4sq-dev/pants/fs-bootstrap/bin/node/${OS}/${ARCH}/${VERSION}/node.tar.gz`
1. Update the `defines` in the nodejs BUILD file
    * set `version` to your version
    * set `release` to "0" and increment every time you push an RPM.
1. Build with the Pants `rpmbuild` command.
   We need RPMs for both centos6 and centos7


       ./pants rpmbuild src/redhat/foursquare/node::
       ./pants rpmbuild --platform=centos6 src/redhat/foursquare/node::

   Note that each platform outputs 4 rpms, but only 3 should be added to the RPM repo.

      - dist/rpmbuild/RPMS/x86_64/nodejs-distribution-debuginfo-v8.8.1-0.el7.centos.x86_64.rpm
      - dist/rpmbuild/RPMS/x86_64/nodejs-distribution-devel-v8.8.1-0.el7.centos.x86_64.rpm
      - dist/rpmbuild/RPMS/x86_64/nodejs-distribution-npm-v8.8.1-0.el7.centos.x86_64.rpm
      - dist/rpmbuild/RPMS/x86_64/nodejs-distribution-v8.8.1-0.el7.centos.x86_64.rpm

   You should not add the debuginfo RPM to the rpm repo, you can ignore it.
