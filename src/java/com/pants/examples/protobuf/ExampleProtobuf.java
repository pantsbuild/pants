// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.protobuf;

import com.pants.examples.distance.Distances;
import com.pants.examples.trip.Trips;

class ExampleProtobuf {

  private ExampleProtobuf() {
  }

  public static void main(String[] args) {
      Distances.Distance d = Distances.Distance.newBuilder().setNumber(12).setUnit("parsecs").build()); 
      System.out.println(d);
      System.out.println(Trips.Trip.newBuilder().setDestination("Atlanta").setDistance(d).build());
  }
}
