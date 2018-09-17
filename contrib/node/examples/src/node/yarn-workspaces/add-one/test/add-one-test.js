const assert = require('assert');
const AddOne = require('../index.js');

describe('AddOne', function () {
  it('adds one correctly', function () {
    assert.equal(2, AddOne.addOne(1));
  });
});
