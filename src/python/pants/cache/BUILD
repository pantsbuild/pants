# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='artifact',
  source='artifact.py',
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_library(
  name='artifact_cache',
  source='artifact_cache.py',
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name='cache_setup',
  source='cache_setup.py',
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/base:build_environment',
    'src/python/pants/subsystem',
    'src/python/pants/util:memo',
    ':artifact',
    ':artifact_cache',
    ':local_artifact_cache',
    ':pinger',
    ':resolver',
    ':restful_artifact_cache',
  ]
)

python_library(
  name='local_artifact_cache',
  source='local_artifact_cache.py',
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    ':artifact',
    ':artifact_cache',
  ]
)

python_library(
  name='pinger',
  source='pinger.py',
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:requests',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    ':artifact_cache',
  ]
)

python_library(
  name='resolver',
  source='resolver.py',
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:requests',
    'src/python/pants/base:validation',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name='restful_artifact_cache',
  source='restful_artifact_cache.py',
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:requests',
    ':artifact_cache',
  ]
)
