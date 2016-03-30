// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.runtime;

public class RuntimeReference {

  public static void main(String[] args) throws Exception {
    Class.forName("com.google.gson.FieldAttributes");
  }

}