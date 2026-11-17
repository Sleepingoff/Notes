const test = require('node:test');
const assert = require('node:assert/strict');
const {backendCommand, isAppUrl} = require('../desktop/backend.cjs');
test('frozen backend dispatch does not depend on a user Python installation', () => {
  const command = backendCommand({packaged: true, resourcesPath: '/app/resources', platform: 'win32'});
  assert.ok(command[0].endsWith('notes-backend.exe'));
  assert.deepEqual(command.slice(1), ['server', '--port', '0']);
});
test('external URLs cannot be mistaken for the app server', () => {
  const origin = 'http://127.0.0.1:12345';
  assert.equal(isAppUrl(origin + '/api/subjects', origin), true);
  for (const url of ['https://example.com', 'file:///etc/passwd', 'http://127.0.0.1:12346', 'http://user@127.0.0.1:12345', 'bad']) assert.equal(isAppUrl(url, origin), false);
});
