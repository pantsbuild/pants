// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.javadepsonscala;

public class Java {

  public String doStuff() {
      // This should not trigger a missing dependency warning
      // since we actually depend on the scala library.
      return new Scala().toString();
  }

}
