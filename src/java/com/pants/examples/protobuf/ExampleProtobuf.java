package com.pants.examples.protobuf;

import com.pants.examples.distance.Distances;

class ExampleProtobuf {

  private ExampleProtobuf() {
  }

  public static void main(String[] args) {
      System.out.println(Distances.Distance.newBuilder().setNumber(12).setUnit("parsecs").build());
  }
}
