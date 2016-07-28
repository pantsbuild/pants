#!/usr/bin/env bash
set -o xtrace

wget https://www.python.org/ftp/python/2.7.10/Python-2.7.10.tgz
tar xvf Python-2.7.10.tgz
cd Python-2.7.10
./configure --enable-unicode=ucs4 --prefix=/home/travis/bin
make
make install
 
which python2.7