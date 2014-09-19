package com.pants.testproject.missingdirectdepswhitelist2;

import com.pants.testproject.publish.hello.greet.Greeting;

public class MissingDirectDepsWhitelist2 {
  public String doStuff() {
    return Greeting.greet("weep");
  }
}