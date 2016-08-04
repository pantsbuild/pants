// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.wire.roots;

import org.pantsbuild.example.roots.Bar;

class WireRootsExample {

  public static void main(String[] args) {
    Bar bar = new Bar("one", "two");
  }
}
