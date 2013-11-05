#!/bin/bash

BASE_DIR=$(dirname $0)/../..
BOOTSTRAP_BIN=$BASE_DIR/.python/bin
BOOTSTRAP_ENVIRONMENT=$BASE_DIR/.python/bootstrap
CACHE=$BASE_DIR/.pants.d/.pip.cache
PY=$(which python)
VENV_VERSION=1.10.1
SETUPTOOLS_VERSION=1.1.7

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
  VENV_TARBALL=virtualenv-$VENV_VERSION.tar.gz
  if ! test -f $VENV_TARBALL; then
    echo 'Installing virtualenv' 1>&2
    curl --connect-timeout 10 -O \
        https://pypi.python.org/packages/source/v/virtualenv/$VENV_TARBALL
  fi
  gzip -cd $VENV_TARBALL | tar -xf - >& /dev/null
popd >& /dev/null

function virtualenv() {
  $PYTHON $CACHE/virtualenv-$VENV_VERSION/virtualenv.py "$@"
}

if virtualenv -p $PY --distribute $BOOTSTRAP_ENVIRONMENT; then
  # Fixup pip script - in some environments the shebang line is too long leading to a  pip script
  # that will not run.
  virtualenv --relocatable $BOOTSTRAP_ENVIRONMENT
  source $BOOTSTRAP_ENVIRONMENT/bin/activate
  for pkg in pystache setuptools==$SETUPTOOLS_VERSION; do
    pip install \
      --download-cache=$CACHE \
      -f https://pypi.python.org/simple \
      -U --no-index $pkg
  done
  deactivate
fi
