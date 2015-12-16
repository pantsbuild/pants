// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.usejaxb;

import org.junit.Assert;
import org.junit.Test;

import org.pantsbuild.example.jaxb.api.SimpleVegetable;
import org.pantsbuild.example.jaxb.reader.VegetableReader;

import java.io.IOException;

/**
 * Tests Jaxb code generation in pants, using reader.VegetableReader and the sample.xml file
 * under org/pantsbuild/example/names/simple.xml
 */
public class UseJaxbTest {

  @Test
  public void veggieTest() {
    try {
      SimpleVegetable veggie = VegetableReader.getInstance()
          .read("/org/pantsbuild/example/names/simple.xml");
      Assert.assertTrue("Name", "Broccoli".equals(veggie.getCommonName()));
      Assert.assertTrue("Species",  "Brassica oleracea".equals(veggie.getScientificName()));
      Assert.assertTrue("Color", 0x00FF00 == (veggie.getColorRGB().longValue()));
      Assert.assertTrue("Tasty:", veggie.isTasty());
    } catch (Exception e) {
      System.err.println("Exception reading vegetable: " + e);
      e.printStackTrace();
    }
  }
}
