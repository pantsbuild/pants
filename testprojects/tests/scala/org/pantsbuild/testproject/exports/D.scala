// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.exports;

class D {
  def foo_d() {
    val c = new C();
    c.foo_c();
  }
}
