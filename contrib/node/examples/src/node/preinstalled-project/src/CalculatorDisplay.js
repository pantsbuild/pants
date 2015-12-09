"use strict";

var React = require('react');

var CalculatorDisplay = React.createClass({
  displayName: "CalculatorDisplay",

  render: function() {
    return React.createElement(
      "div",
      null,
      "Current value: " + this.props.calculator.number
    );
  }
});

module.exports = CalculatorDisplay;
