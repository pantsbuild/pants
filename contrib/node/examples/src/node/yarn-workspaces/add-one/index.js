'use strict';

const numeral = require('numeral');

const addOne = (number) => {
  const thisNumeral = numeral(number);
  return thisNumeral.value() + 1;
};
console.log('AddOne');

module.exports.addOne = addOne;
