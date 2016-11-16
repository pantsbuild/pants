# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='none',
  sources=['NoWarnings.java']
)

java_library(
  name='empty',
  sources=['Empty.java']
)

java_library(
  name='low',
  sources=['LowWarning.java']
)

java_library(
  name='normal',
  sources=['NormalWarning.java']
)

java_library(
  name='high',
  sources=['HighWarning.java']
)

java_library(
  name='no_sources',
  sources=[],
  dependencies=[
    ':low',
    ':normal',
    ':high',
  ]
)

target(
  name='all',
  dependencies=[
    ':none',
    ':low',
    ':normal',
    ':high',
  ]
)
