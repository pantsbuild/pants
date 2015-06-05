// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.wire.element;

import org.pantsbuild.example.element.Compound;
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
    Compound water = new Compound.Builder().name("Water")
            .primary_element(
                    new Element.Builder().symbol("O").name("Oxygen").atomic_number(8).build())
            .secondary_element(
                    new Element.Builder().symbol("H").name("Hydrogen").atomic_number(1).build())
            .build();
    System.out.println(mercury.toString());
    System.out.println(water.toString());
  }
}
