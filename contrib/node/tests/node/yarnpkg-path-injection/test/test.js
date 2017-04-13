import 'babel-polyfill'
import assert from 'assert'
import process from 'process'
import child_process_promise from 'child-process-promise'

describe('Testing Yarnpkg Path Injection', () => {
  describe('Executable Path', () => {
    it('should contain "pants" when running test in pants', () => {
      assert.ok(process.execPath.includes('pants'))
    })
  })
  describe('Node Executable Path', () => {
    it('should contain "pants"', async () => {
      const NodeExecutablePathProcess=await child_process_promise.exec('which node',{encoding:'utf8'})
      assert.ok(NodeExecutablePathProcess.stdout.includes('pants'))
    })
  })
  describe('Npm Executable Path', () => {
    it('should contain "pants"', async () => {
      const NodeExecutablePathProcess=await child_process_promise.exec('which npm',{encoding:'utf8'})
      assert.ok(NodeExecutablePathProcess.stdout.includes('pants'))
    })
  })
  describe('Yarnpkg Executable Path', () => {
    it('should contain "pants"', async () => {
      const NodeExecutablePathProcess=await child_process_promise.exec('which yarnpkg',{encoding:'utf8'})
      assert.ok(NodeExecutablePathProcess.stdout.includes('pants'))
    })
  })
})
