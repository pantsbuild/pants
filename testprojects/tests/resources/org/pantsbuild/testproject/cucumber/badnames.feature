Feature: Demonstrates sanitization of names returned by Cucumber.
  Background:
    Given nothing in particular

  Scenario: Demonstrates that %SPECIAL/symbols ! ~ * are sanitized.
    Given these strings: hello, goodbye
  When these string are added to a %%@@%! list
  Then these strings should be in the list: hello, goodbye
