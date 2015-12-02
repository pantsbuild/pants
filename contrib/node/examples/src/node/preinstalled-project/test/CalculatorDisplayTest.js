var assert = require('assert'),
    React = require('react'),
    Calculator = require('../src/Calculator.js'),
    CalculatorDisplay = require('../src/CalculatorDisplay.js');

describe('CalculatorDisplay', function() {
  it('renders correctly', function() {
    var calculator = new Calculator(2),
        calculatorDisplay = React.createElement(CalculatorDisplay, { calculator: calculator });
    assert.equal(
      '<div>Current value: 2</div>',
      React.renderToStaticMarkup(calculatorDisplay)
    );
  });
});
