package com.pants.testproject.missingdepswhitelist2;

import com.pants.examples.hello.greet.Greeting;

public class MissingDepsWhitelist2 {
  public String doStuff() {
    return Greeting.greet("weep");
  }
}