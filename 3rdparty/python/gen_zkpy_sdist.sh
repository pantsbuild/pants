#!/bin/bash
#
# Generate a standalone sdist for building statically compiled Zookeeper Python eggs/installs.
# Usage: gen_zkpy_sdist.sh <version number>
#
# This will download the source tarball of Apache Zookeeper and rearrange the zkpython bindings
# in a fashion such that they can be built in a standalone manner.  e.g.
#    ./gen_zkpy_sdist.sh 3.4.3
#    Generated zkpython sdist into /tmp/zkpy.B9R3s2/ZooKeeper-3.4.3.tar.gz
#    pushd /tmp/zkpy.B9R3s2
#      gzip -cd ZooKeeper-3.4.3.tar.gz
#      pushd ZooKeeper-3.4.3
#        python setup.py bdist_egg
#      popd
#    popd

if (( $# != 1 && $# != 2 )); then
  echo "Usage: $0 MAJOR.MINOR.PATCH [PackageName]"
  echo "  e.g. $0 3.4.3 tc.zookeeper"
  echo "If no PackageName supplied, it will default to ZooKeeper"
  exit 1
fi

if (( $# == 2 )); then
  ZKPKG=$2
else
  ZKPKG=ZooKeeper
fi

ZKVER=$1
if ! echo $ZKVER | grep -q '^[[:digit:]]\.[[:digit:]]\.[[:digit:]]$'; then
  echo "Malformed version number: $ZKVER.  Must match MAJ.MIN.PATCH"
  exit 1
fi

ZKDL=$(mktemp -d /tmp/zkdl.XXXXXX)
trap "rm -rf $ZKDL" EXIT

pushd $ZKDL >/dev/null
  echo "Downloading zookeeper-$ZKVER"
  ZKURL=http://apache.cs.utah.edu/zookeeper/zookeeper-$ZKVER/zookeeper-$ZKVER.tar.gz
  if ! curl -f -O $ZKURL >& /dev/null; then
    echo "Version $ZKVER does not appear to be available!"
    rm -rf $ZKDL
    exit 1
  fi

  echo "Unpacking zookeeper-$ZKVER"
  tar -xzf zookeeper-$ZKVER.tar.gz
  ZK=$ZKDL/zookeeper-$ZKVER
popd >/dev/null

ZKCONTRIB=$ZK/contrib/zkpython
ZKPY=$(mktemp -d /tmp/zkpy.XXXXXX)
ZKPY=$ZKPY/$ZKPKG-$ZKVER
mkdir -p $ZKPY

cat <<EOF > $ZKPY/setup.py.in
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with this
# work for additional information regarding copyright ownership.  The ASF
# licenses this file to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the
# License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
# License for the specific language governing permissions and limitations
# under the License.

import os
from setuptools import setup, Extension
from setuptools.command.build_py import build_py as _build_py

# TODO(wickman) Do something smarter here.
import subprocess

zookeeper_basedir = "c"
CONFIGURE_MAKE_SCRIPT="""
pushd {0};
  chmod +x configure
  ./configure --enable-static
  make
popd;""".format(zookeeper_basedir)

assert subprocess.call(CONFIGURE_MAKE_SCRIPT, shell=True) == 0, "Build failed!"

def zookeeper_path(path):
  return os.path.join(os.path.abspath(zookeeper_basedir), path)

zookeepermodule = Extension(
  "zookeeper",
  sources=["src/c/zookeeper.c"],
  include_dirs=[zookeeper_path("include"),
                zookeeper_path("generated")],
  extra_compile_args=['-static'],
  extra_link_args=[zookeeper_path('.libs/libzookeeper_mt.a')],
  library_dirs=[zookeeper_path(".libs")]
)

setup(name="%%package%%",
      version = "%%version%%",
      description = "ZooKeeper Python bindings",
      ext_modules=[zookeepermodule])
EOF

echo "Rearranging deck chairs"
cat $ZKPY/setup.py.in | sed s/%%version%%/$ZKVER/ | sed s/%%package%%/$ZKPKG/ > $ZKPY/setup.py
mkdir -p $ZKPY/src
cp -a $ZK/src/c $ZKPY/c
cp -a $ZKCONTRIB/src/{c,python,test} $ZKPY/src
cp -a $ZKCONTRIB/README $ZKPY/README

pushd $(dirname $ZKPY) >/dev/null
  tar -czf $(basename $ZKPY).tar.gz $(basename $ZKPY)
  rm -rf $(basename $ZKPY)
popd >/dev/null

echo "Generated zkpython sdist into $ZKPY.tar.gz"
