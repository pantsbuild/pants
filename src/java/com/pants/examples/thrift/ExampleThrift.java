package com.pants.examples.thrift;

import com.pants.examples.distance.thriftjava.Distance;

/**
 * Driver to test Thrift code generation functionality.
 * Imports generated code (Distance.java), sets its fields,
 * and gets back the set values with toString().
 */
class ExampleThrift {

  private ExampleThrift() {
  }

  /**
   * Print out a sample Distance
   * @param args
   */
  public static void main(String[] args) {
    Distance distance = new Distance();
    distance.setUnit("parsecs");
    distance.setNumber(30000);
    System.out.println("Width of the Milky Way: " + distance);
  }
}
