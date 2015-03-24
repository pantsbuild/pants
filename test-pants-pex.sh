#!/usr/bin/env bash

PANTS_DEV=1 ./pants setup-py --recursive contrib/scrooge/src/python/pants/contrib/scrooge:plugin && \
curl -O https://pypi.python.org/packages/source/v/virtualenv/virtualenv-12.0.7.tar.gz && \
tar -xzf virtualenv-12.0.7.tar.gz && \
cd virtualenv-12.0.7 && \
python2.7 virtualenv.py ../pex && \
cd .. && \
source ./pex/bin/activate && \
pip install pex && \
pex \
  --no-wheel \
  --python=python2.7 \
  --repo=./dist/ \
  -r pantsbuild.pants==0.0.31 \
  -r pantsbuild.pants.contrib.scrooge==0.0.31 \
  -r twitter.common.pants==0.8.2 \
  -r "beautifulsoup4>=4.3.2,<4.4" \
  -e pants.bin.pants_exe:main \
  -o pants.pex && \
zipinfo -1 pants.pex && \
./pants.pex && \
./pants.pex goals && \
./pants.pex list && \
./pants.pex compile compile testprojects/src/thrift/com/pants/::

