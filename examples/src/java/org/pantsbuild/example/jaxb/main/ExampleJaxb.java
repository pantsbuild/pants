// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.jaxb.main;

import org.pantsbuild.example.jaxb.api.SimpleVegetable;
import org.pantsbuild.example.jaxb.reader.VegetableReader;

import java.io.IOException;

/**
 * Tests Jaxb code generation in pants, using reader.VegetableReader and the sample.xml file
 * under org/pantsbuild/example/names/simple.xml
 */
class ExampleJaxb {
  private ExampleJaxb() {
  }

  public static void main(String[] args) {
    try {
      SimpleVegetable veggie = VegetableReader.getInstance()
          .read("/org/pantsbuild/example/names/simple.xml");
      System.out.println("Name: " + veggie.getCommonName());
      System.out.println("Species: " + veggie.getScientificName());
      System.out.println("Color: " + Long.toHexString(veggie.getColorRGB().longValue()));
      System.out.println("Tasty: " + veggie.isTasty());
    } catch (Exception e) {
      System.err.println("Exception reading vegetable: " + e);
      e.printStackTrace();
    }
  }
}