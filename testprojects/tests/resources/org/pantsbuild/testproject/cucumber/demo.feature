Feature: Demonstrates the functionality of cucumber tests.
  Background:
    Given nothing in particular

  Scenario: Demonstrates running tests works.
    Given some fruit: peach, orange, apple
    Given some veggies: carrot, potato, leek
  When we go grocery shopping
  Then expect the cart to contain: peach, orange, apple, carrot, potato, leek

  Scenario: Demonstrates running more tests works.
    Given some fruit: plum, tangerine
    Given some veggies: onion, cabbage, lettuce
  When we go grocery shopping
  Then expect the cart to contain: plum, tangerine, onion, cabbage, lettuce
