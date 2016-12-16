// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.strictdeps;

public class A {
  public void foo_b() {
    B b = new B();
    b.foo_b();
  }
}
