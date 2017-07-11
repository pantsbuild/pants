// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.strictdeps;

public class C {
  public void foo_c() {
    D d = new D();
    d.foo_d();
  }
}
