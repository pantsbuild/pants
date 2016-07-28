#!/usr/bin/env bash
set -o xtrace
$PYTHON_DIR=$HOME/python27-ucs4/python
if [ -f $PYTHON_DIR ];
then
  exit 0
fi

wget https://www.python.org/ftp/python/2.7.10/Python-2.7.10.tgz
tar xvf Python-2.7.10.tgz
cd Python-2.7.10
./configure --enable-unicode=ucs4 --prefix=$PYTHON_DIR
make
make install
 
alias python2.7=$PYTHON_DIR/python
