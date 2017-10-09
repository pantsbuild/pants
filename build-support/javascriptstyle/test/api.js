const javascriptstyle = require('../');
const test = require('tape');

test('api: lintFiles', function (t) {
  t.plan(3);
  javascriptstyle.lintFiles([], { cwd: 'bin' }, function (err, result) {
    t.error(err, 'no error while linting');
    t.equal(typeof result, 'object', 'result is an object');
    t.equal(result.errorCount, 0);
  });
});

test('api: lintText', function (t) {
  t.plan(3);
  javascriptstyle.lintText('console.log("hi there");\n', function (err, result) {
    t.error(err, 'no error while linting');
    t.equal(typeof result, 'object', 'result is an object');
    t.equal(result.errorCount, 1, 'should have used single quotes');
  });
});
