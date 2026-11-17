const test = require('node:test');
const assert = require('node:assert/strict');
const {backendCommand, isAppUrl} = require('../desktop/backend.cjs');
const {execFileSync} = require('node:child_process');
test('release without certificate secrets clears empty signing variables', () => {
  const result = JSON.parse(execFileSync(process.execPath, ['-e', `
    const config = require('./desktop/builder.cjs');
    console.log(JSON.stringify({link: process.env.CSC_LINK ?? null, winLink: process.env.WIN_CSC_LINK ?? null,
      identity: config.mac.identity, notarize: config.mac.notarize}));
  `], {cwd: require('node:path').resolve(__dirname, '..'), env: {...process.env,
    NOTES_RELEASE_SIGNING: '0', CSC_LINK: '', CSC_KEY_PASSWORD: '', WIN_CSC_LINK: '', WIN_CSC_KEY_PASSWORD: ''}, encoding: 'utf8'}));
  assert.deepEqual(result, {link: null, winLink: null, identity: '-', notarize: false});
});
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
