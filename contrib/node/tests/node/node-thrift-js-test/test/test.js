/* eslint-env mocha */
import 'babel-polyfill'
import assert from 'assert'
import Name from 'employee-dep' //full path contrib.node..

describe('Testing Node Thrift JS generation', () => {
  describe('Employee Test', () => {
    it('setting name should reflect changes', () => {
      var test_name = Name;
      test_name.name = "Satwik";
      assert.ok(test_name.name === "Satwik");
    })
  })
})