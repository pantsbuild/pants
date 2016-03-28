// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.provided.subc;

// This shouldn't even compile.
import org.pantsbuild.testproject.provided.suba.A;

public class C {

  public static void main(String[] args) {
    System.out.println("C should not see " + A.class.getSimpleName());
    System.out.println("You should never see this.");
  }

}