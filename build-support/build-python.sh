#!/usr/bin/env bash
set -o xtrace

pyenv uninstall 2.7.10
export CONFIGURE_OPTS="--enable-unicode=ucs4"
pyenv install 2.7.10

alias python2.7=/home/travis/.pyenv/versions/2.7.10
# $PYTHON_DIR=$HOME/python27-ucs4/python
# if [ -f $PYTHON_DIR ];
# then
#   exit 0
# fi

# wget https://www.python.org/ftp/python/2.7.10/Python-2.7.10.tgz
# tar xvf Python-2.7.10.tgz
# cd Python-2.7.10
# ./configure --enable-unicode=ucs4 --prefix=$PYTHON_DIR
# make
# make install
 
# alias python2.7=$PYTHON_DIR/python
