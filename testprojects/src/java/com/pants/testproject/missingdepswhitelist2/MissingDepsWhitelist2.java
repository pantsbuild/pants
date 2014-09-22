package com.pants.testproject.missingdepswhitelist2;

import com.pants.testproject.publish.hello.greet.Greeting;

public class MissingDepsWhitelist2 {
  public String doStuff() {
    return Greeting.greet("weep");
  }
}
