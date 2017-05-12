// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.indirectprotodep;

import com.pants.testproject.indirectprotodep.Redirect;

class ExampleMain {

  public static void main(String[] args) {
    System.out.println(Redirect.Foo.newBuilder().setValue("Hello World!").build());
  }
}
