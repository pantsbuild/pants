#!/bin/bash

BASE_DIR=$(dirname $0)/../..
BOOTSTRAP_BIN=$BASE_DIR/.python/bin
BOOTSTRAP_ENVIRONMENT=$BASE_DIR/.python/bootstrap
CACHE=$BASE_DIR/.pants.d/.pip.cache
PY=$(which python)

mkdir -p $BOOTSTRAP_BIN
mkdir -p $BOOTSTRAP_ENVIRONMENT
mkdir -p $CACHE


if [ ! $PY ]; then
  echo No python interpreter found on the path.  Python will not work\!
  exit 1
fi

# Get Python version. For example, Python 2.7.1 -> 27
py_version=$(python --version 2>&1 | awk -F' ' '{ print $2 }' | awk -F. '{ print $1$2 }')
if [ "${py_version}" -lt 26 ]; then
  echo 'Python interpreter needs to be version 2.6+.'
  exit 2
fi

if ! test -f $BOOTSTRAP_BIN/bootstrap; then
  ln -s $PY $BOOTSTRAP_BIN/bootstrap
fi

PYTHON=$BOOTSTRAP_BIN/bootstrap

pushd $CACHE >& /dev/null
  if ! test -f virtualenv-1.7.1.2.tar.gz; then
    echo Installing virtualenv
    for url in \
      http://pypi.python.org/packages/source/v/virtualenv/virtualenv-1.7.1.2.tar.gz \
      https://svn.twitter.biz/science-binaries/home/third_party/python/virtualenv-1.7.1.2.tar.gz; do
      if curl --connect-timeout 10 -O $url; then
        break
      fi
    done
  fi
  gzip -cd virtualenv-1.7.1.2.tar.gz | tar -xf - >& /dev/null
popd >& /dev/null

if $PYTHON $CACHE/virtualenv-1.7.1.2/virtualenv.py -p $PY --distribute $BOOTSTRAP_ENVIRONMENT; then
  source $BOOTSTRAP_ENVIRONMENT/bin/activate
  for pkg in mako distribute; do
    pip install \
      --download-cache=$CACHE \
      -f https://svn.twitter.biz/science-binaries/home/third_party/python \
      -f http://pypi.python.org/simple \
      -U --no-index $pkg
  done
  deactivate
fi
