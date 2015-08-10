#!/bin/bash

for i in {1..5}
do
    zip -r zipfiles/github.com/fakeuser/rlib$i.zip rlib$i
done
