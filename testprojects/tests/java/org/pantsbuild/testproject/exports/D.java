// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.exports;

public class D {
  public void foo_d() {
    C c = new C();
    c.foo_c();
  }
}
