// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cucumber;

import java.lang.Exception;
import java.lang.RuntimeException;
import java.util.List;
import java.util.LinkedList;

import cucumber.api.java.After;
import cucumber.api.java.Before;
import cucumber.api.java.en.Given;
import cucumber.api.java.en.When;
import cucumber.api.java.en.Then;
import cucumber.runtime.java.guice.ScenarioScoped;
import static org.junit.Assert.assertArrayEquals;

@ScenarioScoped
public class BadnamesSteps {

  private List<String> theStrings;
  private List<String> theListOfStrings;

  @Before public void before() {
    theStrings = new LinkedList<String>();
    theListOfStrings = new LinkedList<String>();
  }

  @After public void after() {
    theStrings = null;
    theListOfStrings = null;
  }

  @Given("^these strings: (.*)$")
  public void theStrings(List<String> strings) {
    this.theStrings.addAll(strings);
  }

  @When("^these string are added to a %%@@%! list$")
  public void addStringsToList() {
    this.theListOfStrings.addAll(this.theStrings);
  }

  @Then("^these strings should be in the list: (.*)$")
  public void checkCart(List<String> expected) {
    assertArrayEquals(
        expected.toArray(new String[expected.size()]),
        theListOfStrings.toArray(new String[theListOfStrings.size()])
    );
  }

}
