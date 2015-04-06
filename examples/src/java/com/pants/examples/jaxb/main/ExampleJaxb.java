// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.jaxb.main;

import com.pants.examples.jaxb.api.SimpleVegetable;
import com.pants.examples.jaxb.reader.VegetableReader;

import java.io.IOException;

/**
 * Tests Jaxb code generation in pants, using reader.VegetableReader and the sample.xml file
 * under com/pants/example/names/simple.xml
 */
class ExampleJaxb {
  private ExampleJaxb() {
  }

  public static void main(String[] args) {
    try {
      SimpleVegetable veggie = VegetableReader.getInstance()
          .read("/com/pants/example/names/simple.xml");
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
