var assert = require('assert'),
    Calculator = require('../src/Calculator.js');

describe('Calculator', function() {
  it('adds', function() {
    var calculator = new Calculator();
    calculator.add(2);
    assert.equal(2, calculator.number);
  });

  it('subtracts', function() {
    var calculator = new Calculator();
    calculator.subtract(2);
    assert.equal(-2, calculator.number);
  });

  it('multiplies', function() {
    var calculator = new Calculator(2);
    calculator.multiply(2);
    assert.equal(4, calculator.number);
  });

  it('divides', function() {
    var calculator = new Calculator(4);
    calculator.divide(2);
    assert.equal(2, calculator.number);
  });

  it('handles initial state', function() {
    var calculator = new Calculator();
    assert.equal(0, calculator.number);
    calculator = new Calculator(10);
    assert.equal(10, calculator.number);
  });
});
