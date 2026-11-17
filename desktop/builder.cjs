const release = process.env.NOTES_RELEASE_SIGNING === '1';
module.exports = {
  appId: 'io.github.sleepingoff.notes', productName: 'Notes',
  directories: {output: 'release', buildResources: 'packaging'},
  files: ['desktop/**', 'package.json', 'LICENSE', 'THIRD_PARTY_NOTICES.md'],
  extraResources: [{from: 'desktop-resources/backend', to: 'backend', filter: ['**/*']}],
  asar: true,
  electronFuses: {runAsNode: true, enableNodeOptionsEnvironmentVariable: false, enableNodeCliInspectArguments: false},
  artifactName: 'Notes-${version}-${os}-${arch}.${ext}',
  forceCodeSigning: release && process.platform === 'darwin',
  mac: {target: ['dmg', 'zip'], category: 'public.app-category.education',
    hardenedRuntime: release, identity: release ? undefined : '-',
    entitlements: 'packaging/entitlements.mac.plist', entitlementsInherit: 'packaging/entitlements.mac.plist',
    notarize: release,
    binaries: ['Contents/Resources/backend/notes-backend']},
  dmg: {sign: release},
  win: {target: ['nsis'], signAndEditExecutable: true},
  nsis: {oneClick: false, perMachine: false, allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true, deleteAppDataOnUninstall: false},
  publish: [{provider: 'github', owner: 'Sleepingoff', repo: 'Notes', releaseType: 'release'}]
};
