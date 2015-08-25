package org.pantsbuild.testproject.printversion;

/**
 * This is used in test_distribution_integration.py to make sure
 * Distribution.locate finds the correct java installation.
 */
public class PrintVersion {

  public static void main(String[] args) {
    System.out.println("java.version:" + System.getProperty("java.version"));
    System.out.println("java.home:" + System.getProperty("java.home"));
  }

}
