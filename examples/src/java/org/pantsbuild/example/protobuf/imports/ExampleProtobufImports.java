// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.protobuf.imports;

import org.pantsbuild.example.imports.TestImports;

class ExampleProtobufImports {

  private ExampleProtobufImports() {
  }

  public static void main(String[] args) {
      System.out.println(TestImports.TestImport.newBuilder().setTestNum(12).setTestStr("very test")
          .build());
  }
}
