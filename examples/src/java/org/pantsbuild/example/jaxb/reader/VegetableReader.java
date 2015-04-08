// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.jaxb.reader;

import org.pantsbuild.example.jaxb.api.ObjectFactory;
import org.pantsbuild.example.jaxb.api.SimpleVegetable;

import java.io.InputStream;
import java.io.IOException;
import javax.xml.bind.JAXBContext;
import javax.xml.bind.JAXBElement;
import javax.xml.bind.JAXBException;
import javax.xml.bind.Unmarshaller;
import javax.xml.transform.stream.StreamSource;

/**
 * Singleton to read SimpleVegetables from XML data (example class
 * made to test JAXB functionality in pants)
 */
public class VegetableReader {

  private static VegetableReader me;

  private JAXBContext context;
  private Unmarshaller unmarshaller;

  private VegetableReader() {
    try {
      context = JAXBContext.newInstance(ObjectFactory.class);
      unmarshaller = context.createUnmarshaller();
    } catch (JAXBException e) {
      throw new AssertionError(e);
    }
  }

  public static synchronized VegetableReader getInstance() {
    if (me == null)
      me = new VegetableReader();
    return me;
  }

  /**
   * Reads in the (assumedly xml) contents of the input stream and returns a
   * SimpleVegetable. Throws an IOException if JAXB has trouble unmarshalling the object.
   * <br/>
   * This method does <i>not</i> close the InputStream passed to it.
   */
  public SimpleVegetable read(InputStream in) throws IOException {
    try {
      JAXBElement<SimpleVegetable> obj = unmarshaller.unmarshal(
          new StreamSource(in), SimpleVegetable.class);
      SimpleVegetable veggie = obj.getValue();
      return veggie;
    } catch (JAXBException e) {
      throw new IOException(e);
    }
  }

  /**
   * Tries to open a stream to the given resource, passes it to read(InputStream), and returns
   * the SimpleVegetable. The given resource should (obviously) be an .xml file following
   * the SimpleVegetable specifications.
   * 
   * @throws IOException if JAXB hiccups, the resource doesn't exist, etc
   */
  public SimpleVegetable read(String resource) throws IOException {
    InputStream in = getClass().getResourceAsStream(resource);

    if (in == null) {
      throw new IOException("Failed to find resource '" + resource + "'");
    }

    SimpleVegetable veggie = null;

    try {
      veggie = read(in);
    } finally {
      in.close();
    }

    return veggie;
  }
}