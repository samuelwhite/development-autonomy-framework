import { stdin, stdout } from 'node:process';
import { createInterface } from 'node:readline/promises';
import { Writable } from 'node:stream';
import { AccountError, bootstrapAccounts, openAccounts } from './accounts.mjs';

async function ask(prompt, hidden = false) {
  const muted = new Writable({ write(_chunk, _encoding, done) { done(); } });
  const editor = createInterface({ input: stdin, output: hidden ? muted : stdout, terminal: true, historySize: 0 });
  const abort = new AbortController();
  editor.on('SIGINT', () => abort.abort());
  if (hidden) stdout.write(prompt);
  try {
    return await editor.question(hidden ? '' : prompt, { signal: abort.signal });
  } finally {
    editor.close();
    if (hidden) stdout.write('\n');
  }
}

try {
  if (!stdin.isTTY || !stdout.isTTY) throw new AccountError(400, 'Use a trusted interactive terminal.');
  const directory = process.env.DAF_AUTH_STATE_DIR;
  if (!directory) throw new AccountError(400, 'Configure a private account state directory first.');
  if (process.argv.length === 3 && process.argv[2] === '--revoke-sessions') {
    if (await ask('Type REVOKE to invalidate every session: ') !== 'REVOKE') throw Error();
    const accounts = openAccounts(directory);
    try { accounts.revokeAll(); } finally { accounts.close(); }
    console.log('Sessions revoked.');
  } else if (process.argv.length === 2) {
    const username = await ask('Administrator username: ');
    const password = await ask('Administrator password: ', true);
    if (password !== await ask('Repeat password: ', true)) {
      throw new AccountError(400, 'Passwords do not match.');
    }
    await bootstrapAccounts(directory, username, password);
    console.log('Administrator created.');
  } else {
    throw Error();
  }
} catch (error) {
  console.error(error instanceof AccountError ? error.message :
    'Account setup did not complete. Verify private state and whether an administrator already exists.');
  process.exitCode = 1;
}
