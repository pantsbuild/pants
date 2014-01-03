#!/bin/bash

BASE_DIR=$(dirname $0)/../..
BOOTSTRAP_BIN=$BASE_DIR/.python/bin
BOOTSTRAP_ENVIRONMENT=$BASE_DIR/.python/bootstrap
CACHE=$BASE_DIR/.pants.d/.pip.cache
PY=$(which python)
VIRTUALENV_VERSION=1.9.1

mkdir -p $BOOTSTRAP_BIN
mkdir -p $BOOTSTRAP_ENVIRONMENT
mkdir -p $CACHE


if [ ! $PY ]; then
  echo 'No python interpreter found on the path.  Python will not work!'
  exit 1
fi

# Get Python version. For example, Python 2.7.1 -> 27
py_version=$($PY --version 2>&1 | awk -F' ' '{ print $2 }' | awk -F. '{ print $1$2 }')
if [ "${py_version}" -lt 26 ]; then
  echo 'Python interpreter needs to be version 2.6+.'
  exit 2
fi

if ! test -f $BOOTSTRAP_BIN/bootstrap; then
  ln -s $PY $BOOTSTRAP_BIN/bootstrap
fi

PYTHON=$BOOTSTRAP_BIN/bootstrap

pushd $CACHE >& /dev/null
  VIRTUALENV_TARBALL=virtualenv-$VIRTUALENV_VERSION.tar.gz
  if ! test -f $VIRTUALENV_TARBALL; then
    echo 'Installing virtualenv' 1>&2
    curl --connect-timeout 10 -O \
        https://pypi.python.org/packages/source/v/virtualenv/$VIRTUALENV_TARBALL
  fi
  gzip -cd $VIRTUALENV_TARBALL | tar -xf - >& /dev/null
popd >& /dev/null

function virtualenv() {
  $PYTHON $CACHE/virtualenv-$VIRTUALENV_VERSION/virtualenv.py "$@"
}

if virtualenv -p $PY --distribute $BOOTSTRAP_ENVIRONMENT; then
  # Fixup pip script - in some environments the shebang line is too long leading to a  pip script
  # that will not run.
  virtualenv --relocatable $BOOTSTRAP_ENVIRONMENT
  source $BOOTSTRAP_ENVIRONMENT/bin/activate
  for pkg in distribute pystache; do
    pip install \
      --download-cache=$CACHE \
      -f https://pypi.python.org/simple \
      -U --no-index $pkg
  done
  deactivate
fi
