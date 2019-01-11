// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.javadepsonscalatransitive;

public class Java {

  public String doStuff() {
      // This should not trigger a missing dependency warning
      // since we actually depend on the scala library.
    Scala scala = new Scala();
    Scala2 scala2 = new Scala2();
    return scala.toString() + scala2.toString();
  }

}
