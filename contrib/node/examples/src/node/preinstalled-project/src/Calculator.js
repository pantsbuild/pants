"use strict";

class Calculator {

  constructor(initialNumber) {
    this.number = initialNumber || 0;
  }

  add(number) {
    this.number += number;
  }

  subtract(number) {
    this.number -= number;
  }

  multiply(number) {
    this.number *= number;
  }

  divide(number) {
    this.number /= number;
  }

}

module.exports = Calculator;
