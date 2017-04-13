/* eslint-env mocha */
import 'babel-polyfill'
import assert from 'assert'
import process from 'process'
import ChildProcessPromise from 'child-process-promise'

describe('Testing Npm Path Injection', () => {
  describe('Executable Path', () => {
    it('should contain "pants" when running test in pants', () => {
      assert.ok(process.execPath.includes('pants'))
    })
  })
  describe('Node Executable Path', () => {
    it('should contain "pants"', async () => {
      const NodeExecutablePathProcess = await ChildProcessPromise.exec('which node', {encoding: 'utf8'})
      assert.ok(NodeExecutablePathProcess.stdout.includes('pants'))
    })
  })
  describe('Npm Executable Path', () => {
    it('should contain "pants"', async () => {
      const NodeExecutablePathProcess = await ChildProcessPromise.exec('which npm', {encoding: 'utf8'})
      assert.ok(NodeExecutablePathProcess.stdout.includes('pants'))
    })
  })
})
