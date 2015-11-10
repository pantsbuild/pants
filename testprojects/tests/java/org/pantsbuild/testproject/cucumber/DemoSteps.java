// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cucumber;

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
public class DemoSteps {

  private List<String> fruits;
  private List<String> veggies;
  private List<String> cart;

  @Before public void before() {
    fruits = new LinkedList<String>();
    veggies = new LinkedList<String>();
    cart = new LinkedList<String>();
  }

  @After public void after() {
    fruits = null;
    veggies = null;
    cart = null;
  }

  @Given("^nothing in particular$")
  public void nothingInParticular() {
  }

  @Given("^some fruit: (.*)$")
  public void addFruitToList(List<String> fruits) {
    this.fruits.addAll(fruits);
  }

  @Given("^some veggies: (.*)$")
  public void addVeggiesToList(List<String> veggies) {
    this.veggies.addAll(veggies);
  }

  @When("^we go grocery shopping$")
  public void gatherFood() {
    cart.addAll(fruits);
    cart.addAll(veggies);
  }

  @Then("^expect the cart to contain: (.*)$")
  public void checkCart(List<String> foods) {
    assertArrayEquals(
      foods.toArray(new String[cart.size()]),
      cart.toArray(new String[cart.size()])
    );
  }

}
