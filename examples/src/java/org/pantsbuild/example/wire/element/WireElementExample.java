// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.wire.element;

import org.pantsbuild.example.element.Element;
import org.pantsbuild.example.temperature.Temperature;

/**
 * Simple example of creating a message with Wire and printing out its contents.
 */
class WireElementExample {

  private WireElementExample() {
  }

  public static void main(String[] args) {
    Temperature meltingPoint = new Temperature.Builder().unit("celsius").number((long)-39).build();
    Temperature boilingPoint = new Temperature.Builder().unit("celsius").number((long)357).build();
    Element mercury = new Element.Builder().symbol("Hg").name("Mercury").atomic_number(80)
      .melting_point(meltingPoint).boiling_point(boilingPoint).build();
    System.out.println(mercury.toString());
  }
}
