#!/usr/bin/env bash
#
# creates three resources:
#   zipsafe_egg.egg
#   not_zipsafe_egg.egg
#   not_zipsafe_egg_dir

CWD=$(dirname $0)

pushd $CWD/egg_data
  PYTHON_BIN=../../../../../../../.python/bin/python
  BUILD_DIR=$(mktemp -d build.XXXXXX)
  DIST_DIR=$(mktemp -d dist.XXXXXX)

  $PYTHON_BIN setup_zipegg.py bdist_egg -b $BUILD_DIR -d $DIST_DIR
  $PYTHON_BIN setup_nonzipegg.py bdist_egg -b $BUILD_DIR -d $DIST_DIR

  mv $DIST_DIR/not_zipsafe_egg-0.0.0-py2.6.egg ../not_zipsafe_egg.egg
  mv $DIST_DIR/zipsafe_egg-0.0.0-py2.6.egg ../zipsafe_egg.egg

  rm -rf $DIST_DIR $BUILD_DIR build *.egg-info
popd

pushd $CWD
  rm -rf not_zipsafe_egg_dir.egg
  mkdir -p not_zipsafe_egg_dir.egg
  cp not_zipsafe_egg.egg not_zipsafe_egg_dir.egg

  pushd not_zipsafe_egg_dir.egg
    unzip not_zipsafe_egg.egg
    rm -f not_zipsafe_egg.egg
  popd
popd
