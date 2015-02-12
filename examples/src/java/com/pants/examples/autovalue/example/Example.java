// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).


package com.pants.examples.autovalue.example;

import com.google.auto.value.AutoValue;

@AutoValue
abstract class Example {
  static Example create(String name) {
      return new AutoValue_Example(name);
  }

  abstract String name();
}
