// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

import java.util.Enumeration;
import java.util.Properties;

/**
 * Emits all the java system properties for the current jvm to standard out as [key]=[value] pairs,
 * one per line.
 */
public class SystemProperties {
  public static void main(String[] args) {
    Properties properties = System.getProperties();
    Enumeration keys = properties.propertyNames();
    while(keys.hasMoreElements()) {
      String key = (String) keys.nextElement();
      String value = properties.getProperty(key);
      System.out.println(key + "=" + value);
    }
  }
}
