// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.spindle.test

import com.foursquare.rogue.spindle._
import com.foursquare.rogue.spindle.SpindleRogue._
import org.apache.thrift.protocol.TBinaryProtocol
import org.apache.thrift.TSerializer
import org.bson.types.ObjectId
import org.junit.Assert._
import org.junit.Test
import org.pantsbuild.contrib.spindle.TvListingEntry


class ThriftCodegenTest {
  @Test
  def testRogue(): Unit = {
    assertEquals(SpindleQuery(TvListingEntry).where(_.startTime eqs "now").toString, "db.tv.find({ \"st\" : \"now\"})")
  }

  @Test
  def testSerialize(): Unit = {
    val serializer = new TSerializer(new TBinaryProtocol.Factory())
    val struct = TvListingEntry.newBuilder.startTime("now").contentid(ObjectId.get).result()
    val serialized = serializer.serialize(struct)
    assertEquals(serialized.size, 30)
  }
}
