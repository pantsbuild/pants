# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Modified scoverge plugin, which writes to classpath, currently consumed from Twitter forked scoverage here:
# https://github.com/twitter-forks/scalac-scoverage-plugin. PR for the modifications
# on original scoverage repo here: https://github.com/scoverage/scalac-scoverage-plugin/pull/267.
# In future, we should ping OSS Scoverage to get that PR merged and consume scoverage directly
# from there. Version 1.0.2 incorporates the changes in the following PR:
# https://github.com/scoverage/scalac-scoverage-plugin/pull/275.

jar_library(name='scalac-scoverage-plugin',
  jars=[
    scala_jar(org='com.twitter.scoverage', name='scalac-scoverage-plugin', rev='1.0.2-twitter'),
    ],
  )
