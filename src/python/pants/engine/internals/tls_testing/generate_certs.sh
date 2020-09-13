#!/bin/sh

# Run this script in this dir to generate the certs and keys needed for this test.
# Note that on MacOS you will need a recent-ish homebrewed openssl, not the system one.

set -xeuo pipefail

rm -rf rsa/
mkdir rsa/

openssl req -nodes \
          -x509 \
          -days 3650 \
          -newkey rsa:4096 \
          -keyout rsa/root_ca.key \
          -out rsa/root_ca.crt \
          -sha256 \
          -batch \
          -subj "/CN=Root CA for testing"

openssl req -nodes \
          -newkey rsa:3072 \
          -keyout rsa/intermediate_ca.key \
          -out rsa/intermediate_ca.req \
          -sha256 \
          -batch \
          -subj "/CN=Intermediate CA for testing"

openssl req -nodes \
          -newkey rsa:2048 \
          -keyout rsa/server.key \
          -out rsa/server.req \
          -sha256 \
          -batch \
          -subj "/CN=Server for testing"

openssl x509 -req \
          -in rsa/intermediate_ca.req \
          -out rsa/intermediate_ca.crt \
          -CA rsa/root_ca.crt \
          -CAkey rsa/root_ca.key \
          -sha256 \
          -days 3650 \
          -set_serial 123 \
          -extensions v3_intermediate_ca -extfile openssl.cnf

openssl x509 -req \
          -in rsa/server.req \
          -out rsa/server.crt \
          -CA rsa/intermediate_ca.crt \
          -CAkey rsa/intermediate_ca.key \
          -sha256 \
          -days 3000 \
          -set_serial 456 \
          -extensions v3_server -extfile openssl.cnf

cat rsa/intermediate_ca.crt rsa/root_ca.crt > rsa/server.chain

# Clean up intermediate files.
rm -f rsa/root_ca.*
rm -f rsa/intermediate_ca.*
rm -f rsa/server.req
