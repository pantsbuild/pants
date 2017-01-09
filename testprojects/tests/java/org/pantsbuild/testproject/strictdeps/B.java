// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.strictdeps;

public class B {
  public void foo_b() {
    C c = new C();
    c.foo_c();
  }
}
