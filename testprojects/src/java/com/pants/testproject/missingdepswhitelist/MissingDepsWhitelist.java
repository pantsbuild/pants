package com.pants.testproject.missingdepswhitelist;

import com.pants.testproject.publish.hello.greet.Greeting;
import com.pants.testproject.missingdepswhitelist2.MissingDepsWhitelist2;

public class MissingDepsWhitelist {
  public String doStuff() {
    MissingDepsWhitelist2 scala = new MissingDepsWhitelist2();
    return Greeting.greet("woop");
  }
}