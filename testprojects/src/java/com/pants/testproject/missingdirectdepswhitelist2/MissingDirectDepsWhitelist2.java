package com.pants.testproject.missingdirectdepswhitelist2;

import com.pants.examples.hello.greet.Greeting;

public class MissingDirectDepsWhitelist2 {
  public String doStuff() {
    return Greeting.greet("weep");
  }
}