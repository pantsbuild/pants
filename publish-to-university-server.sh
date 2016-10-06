#!/bin/bash

./build-support/bin/publish_docs.sh

if [ $? -eq 0 ]; then
  rsync -azh dist/docsite/* lperkins@university.twitter.biz:~/public_html/pants
  echo "Successfully published to university server"
  exit 0
else
  echo "Build failed!"
  exit 1
fi
