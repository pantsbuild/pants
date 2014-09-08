package com.pants.testproject.missingdirectdepswhitelist;

import com.pants.examples.hello.greet.Greeting;
import com.pants.testproject.missingdirectdepswhitelist2.MissingDirectDepsWhitelist2;

public class MissingDirectDepsWhitelist {
  public String doStuff() {
    MissingDirectDepsWhitelist2 scala = new MissingDirectDepsWhitelist2();
    return Greeting.greet("woop");
  }
}