#!/usr/bin/env bash

IP=169.254.169.254

function instance_data() {
  local item="$1"
  curl -sSL "${IP}/latest/meta-data/${item}"
}

if curl --max-time 1 ${IP} &>/dev/null; then
  # We're in EC2.
  cat << INFO
Running on:
      node id: ${NODE_NAME}
       ami id: $(instance_data "ami-id")
  instance id: $(instance_data "instance-id")
         host: $(instance_data "public-ipv4")
           os: $(uname -a)
INFO
else
  # We're on some other node.
  cat << INFO
Running on:
           os: $(uname -a)
INFO
fi
