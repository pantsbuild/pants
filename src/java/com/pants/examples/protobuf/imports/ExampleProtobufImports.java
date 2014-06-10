// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.protobuf.imports;

import com.pants.examples.imports.TestImports;

class ExampleProtobufImports {

  private ExampleProtobufImports() {
  }

  public static void main(String[] args) {
      System.out.println(TestImports.TestImport.newBuilder().setTestNum(12).setTestStr("very test")
          .build());
  }
}
