// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.runtime;

public class CompileReference {

  public static void main(String[] args) {
    System.out.println("GSON field attributes: "
        + com.google.gson.FieldAttributes.class.getSimpleName());
  }

}