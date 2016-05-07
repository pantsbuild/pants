#!/usr/bin/env bash

IP=169.254.169.254

export TERM=${TERM:-xterm}
c_blue=$(tput setaf 4)
c_bold=$(tput bold)
c_reset=$(tput sgr0)

function instance_data() {
  local item="$1"
  curl -sSL "${IP}/latest/meta-data/${item}"
}

if curl --max-time 1 ${IP} &>/dev/null; then
  # We're in EC2.
  cat << INFO
${c_bold}${c_blue}Running on:${c_reset}${c_blue}
      node id: ${c_bold}${NODE_NAME}${c_reset}${c_blue}
       ami id: ${c_bold}$(instance_data "ami-id")${c_reset}${c_blue}
  instance id: ${c_bold}$(instance_data "instance-id")${c_reset}${c_blue}
         host: ${c_bold}$(instance_data "public-ipv4")${c_reset}${c_blue}
           os: ${c_bold}$(uname -a)${c_reset}
INFO
else
  # We're on some other node.
  cat << INFO
${c_bold}${c_blue}Running on:${c_reset}${c_blue}
           os: ${c_bold}$(uname -a)${c_reset}
INFO
fi
