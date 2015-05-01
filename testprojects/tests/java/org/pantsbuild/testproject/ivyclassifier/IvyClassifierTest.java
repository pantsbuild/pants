// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.ivyclassifier;

import java.io.InputStream;
import org.apache.avro.RandomData;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericData;
import org.apache.avro.generic.GenericRecord;
import org.junit.Test;

import static org.junit.Assert.assertNotNull;

/**
 * This test exercises the ability to specify two jars that are distinguished only by classifier
 * in the jar() specification.
 *
 * The Avro project has 2 jars.  The runtime jar has no classifier. There is an additional 'tests'
 * jar you can use with some test classes.
 */
public class IvyClassifierTest {

  private Schema getSchema() throws Exception {
    InputStream avroExampleDesc = IvyClassifierTest.class.getResourceAsStream(
        "example.avsc");
    assertNotNull(avroExampleDesc);
    Schema schema = new Schema.Parser().parse(avroExampleDesc);
    return schema;
  }

  /**
   * Reference symbols in the avro main jar
   * @throws Exception
   */
  @Test
  public void testAvroJar() throws Exception {
    GenericRecord avroRec = new GenericData.Record(getSchema());
    assertNotNull(avroRec);
  }

  /**
   * Reference a symbol in the avro-tests jar.
   */
  @Test
  public void testAvroTestJar() throws Exception {
    RandomData randomData = new RandomData(getSchema(), 10);
    assertNotNull(randomData);
  }
}
