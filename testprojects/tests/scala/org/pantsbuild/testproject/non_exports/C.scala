// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.non_exports;

class C {
  def foo_c() {
    val b = new B();
    b.foo_b();
  }
}
