// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.shading;

import java.util.Map;
import java.util.HashMap;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

/**
 * This is the main file in a tiny library just used to test 3rdparty dependency shading.
 */
public class Third {

  public static void main(String[] args) {
    Map<String, String> classNames = new HashMap<>();
    classNames.put(Third.class.getSimpleName(), Third.class.getName());
    classNames.put(Second.class.getSimpleName(), Second.class.getName());
    classNames.put(Gson.class.getSimpleName(), Gson.class.getName());

    new Second().write(42);

    Gson gson = new GsonBuilder().create();
    System.out.println(gson.toJson(classNames));
  }

}
