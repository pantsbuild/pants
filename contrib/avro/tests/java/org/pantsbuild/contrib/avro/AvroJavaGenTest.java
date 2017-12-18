// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.avro;

import java.util.ArrayList;
import java.util.List;

import org.junit.Test;
import org.pantsbuild.contrib.avro.User;
import org.pantsbuild.contrib.avro.MD5;
import org.pantsbuild.contrib.avro.TestRecord;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

public class AvroJavaGenTest {
  @Test
  public void testSchemaGen() {
    User user = User.newBuilder()
      .setName("Test User")
      .setFavoriteColor("blue")
      .setFavoriteNumber(10)
      .build();

    assertEquals("Test User", user.getName());
    assertEquals("blue", user.getFavoriteColor());
    assertEquals(10, user.getFavoriteNumber().intValue());
  }

  @Test
  public void testIdlGen() {
    List<Long> arrayOfLongs = new ArrayList();
    arrayOfLongs.add(1L);
    arrayOfLongs.add(2L);
    arrayOfLongs.add(3L);

    TestRecord testRecord = TestRecord.newBuilder()
      .setName("Name")
      .setKind(Kind.BAR)
      .setHash(new MD5(new byte[] {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}))
      .setNullableHash(null)
      .setArrayOfLongs(arrayOfLongs)
      .build();

    assertEquals("Name", testRecord.getName());
    assertEquals(Kind.BAR, testRecord.getKind());
    assertArrayEquals(new byte[] {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
      testRecord.getHash().bytes());
    assertNull(testRecord.getNullableHash());
    assertEquals(arrayOfLongs, testRecord.getArrayOfLongs());
  }
}
