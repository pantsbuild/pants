#!/bin/bash

SCIENCE_BASE=$(dirname $0)/../..
rm -rf $HOME/.pex
rm -rf $SCIENCE_BASE/.pants.d
rm -rf $SCIENCE_BASE/.python
rm -f  $SCIENCE_BASE/pants.pex
find $SCIENCE_BASE -name '*.pyc' | xargs rm -f
