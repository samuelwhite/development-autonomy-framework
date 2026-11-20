import { createHash, randomBytes, scrypt as derive, timingSafeEqual } from 'node:crypto';
import { accessSync, closeSync, constants, lstatSync, openSync, readFileSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { promisify } from 'node:util';

const scrypt = promisify(derive);
const parameters = { N: 32768, r: 8, p: 3, maxmem: 40 * 1024 * 1024 };
const word = /^[a-z0-9][a-z0-9_.-]{2,31}$/;
const hex = /^[a-f0-9]{64}$/;
const roles = new Set(['administrator', 'viewer']);
const sessionLifetime = 24 * 60 * 60;
const digest = (text) => createHash('sha256').update(text).digest('hex');
const dummySalt = randomBytes(16).toString('hex');
const dummyHash = randomBytes(32).toString('hex');
let hashing = 0;
let blocklist;

export class AccountError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function username(value) {
  const name = typeof value === 'string' ? value.toLowerCase() : '';
  return word.test(name) ? name : null;
}

function inputPassword(value) {
  return typeof value === 'string' && Buffer.byteLength(value) <= 1024 ? value.normalize('NFC') : null;
}

function enforcePassword(value, name) {
  const password = inputPassword(value);
  if (!password || [...password].length < 10 || [...password].length > 256) {
    throw new AccountError(400, 'Use 10 to 256 characters. A long, unique passphrase works well.');
  }
  if (!blocklist) {
    const entries = readFileSync(new URL('./password-blocklist.sha256', import.meta.url), 'utf8').trim().split(/\r?\n/);
    if (entries.length < 100 || !entries.every((entry) => hex.test(entry))) throw Error('Invalid password blocklist');
    blocklist = new Set(entries);
  }
  const folded = password.normalize('NFKC').trim().toLowerCase();
  const compact = folded.replace(/[\s._-]+/g, '');
  const account = name.replace(/[._-]+/g, '');
  if (!folded || blocklist.has(digest(folded)) || /^(.)\1+$/u.test(compact) ||
      /^(?:1234567890?|0123456789|qwertyuiop|asdfghjkl|letmein|password|passphrase|welcome|admin|daf|missioncontrol|correcthorsebatterystaple)[\d!@#$]*$/.test(compact) ||
      (compact.startsWith(account) && /^[\d!@#$]*$/.test(compact.slice(account.length)))) {
    throw new AccountError(400, 'Choose a unique password that is harder to guess.');
  }
  return password;
}

async function hash(password, salt) {
  if (hashing >= 2) throw new AccountError(429, 'Too many requests. Try again shortly.');
  hashing++;
  try {
    return await scrypt(password, Buffer.from(salt, 'hex'), 32, parameters);
  } finally {
    hashing--;
  }
}

async function passwordRecord(password, name) {
  const salt = randomBytes(16).toString('hex');
  return { salt, hash: (await hash(enforcePassword(password, name), salt)).toString('hex') };
}

async function matches(password, record) {
  const candidate = inputPassword(password);
  if (candidate === null) return false;
  const value = await hash(candidate, record?.salt ?? dummySalt);
  return timingSafeEqual(value, Buffer.from(record?.hash ?? dummyHash, 'hex'));
}

function open(directory, initializing = false) {
  if (!directory) throw Error('Account state directory is required');
  const path = join(directory, 'accounts.sqlite');
  const folder = lstatSync(directory);
  if (!folder.isDirectory() || (process.platform !== 'win32' && (folder.mode & 0o077))) {
    throw Error('Account directory must be private');
  }
  accessSync(directory, constants.W_OK);
  if (initializing) closeSync(openSync(path, 'wx', 0o600));
  try {
    const file = lstatSync(path);
    if (!file.isFile() || file.nlink !== 1 || (process.platform !== 'win32' && (file.mode & 0o077))) {
      throw Error('Account database must be a private regular file');
    }
    const db = new DatabaseSync(path, { enableForeignKeyConstraints: true });
    try {
      db.exec('PRAGMA busy_timeout = 2000');
      return db;
    } catch (error) {
      db.close();
      throw error;
    }
  } catch (error) {
    if (initializing) unlinkSync(path);
    throw error;
  }
}

function transaction(db, operation) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const result = operation();
    db.exec('COMMIT');
    return result;
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

export async function bootstrapAccounts(directory, rawName, password) {
  const name = username(rawName);
  if (!name) throw new AccountError(400, 'Use 3 to 32 letters, digits, dots, hyphens or underscores.');
  const record = await passwordRecord(password, name);
  const db = open(directory, true);
  try {
    transaction(db, () => {
      db.exec(`
        CREATE TABLE users (
          name TEXT PRIMARY KEY,
          role TEXT NOT NULL CHECK (role IN ('administrator', 'viewer')),
          enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
          salt TEXT NOT NULL CHECK (length(salt) = 32),
          hash TEXT NOT NULL CHECK (length(hash) = 64)
        ) STRICT;
        CREATE TABLE sessions (
          id TEXT PRIMARY KEY CHECK (length(id) = 64),
          name TEXT NOT NULL REFERENCES users(name),
          expires INTEGER NOT NULL
        ) STRICT;
        CREATE INDEX sessions_by_user ON sessions(name);
        PRAGMA user_version = 1;
      `);
      db.prepare("INSERT INTO users VALUES (?, 'administrator', 1, ?, ?)").run(name, record.salt, record.hash);
    });
  } finally {
    db.close();
  }
}

export function openAccounts(directory, now = Date.now) {
  const db = open(directory);
  try {
    if (db.prepare('PRAGMA user_version').get().user_version !== 1 ||
        db.prepare('PRAGMA quick_check').get().quick_check !== 'ok' ||
        db.prepare('PRAGMA foreign_key_check').get()) throw Error('Unsupported or corrupt account store');
    const users = db.prepare('SELECT * FROM users').all();
    if (!users.every((user) => user.name === username(user.name) && roles.has(user.role) &&
        /^[a-f0-9]{32}$/.test(user.salt) && hex.test(user.hash)) ||
        !users.some((user) => user.enabled && user.role === 'administrator')) {
      throw Error('Invalid or uninitialised account store');
    }
    transaction(db, () => {});
  } catch (error) {
    db.close();
    throw error;
  }
  const time = () => Math.floor(now() / 1000);
  const find = db.prepare('SELECT * FROM users WHERE name = ?');
  const session = db.prepare(`
    SELECT users.name, users.role FROM sessions JOIN users USING (name)
    WHERE sessions.id = ? AND sessions.expires > ? AND users.enabled = 1
  `);
  const identity = (id) => hex.test(id || '') ? session.get(digest(id), time()) : undefined;
  const loginError = () => new AccountError(401, 'Sign-in failed. Check your credentials and try again.');
  const needUser = (id, admin = false) => {
    const user = identity(id);
    if (!user) throw loginError();
    if (admin && user.role !== 'administrator') throw new AccountError(403, 'Administrator access is required.');
    return user;
  };
  const clearSessions = db.prepare('DELETE FROM sessions WHERE name = ?');
  const replacePassword = db.prepare('UPDATE users SET salt = ?, hash = ? WHERE name = ?');
  const target = (value) => {
    const user = find.get(username(value));
    if (!user) throw new AccountError(404, 'User not found.');
    return user;
  };
  let closed = false;

  return {
    identity,
    close() {
      if (!closed) {
        closed = true;
        db.close();
      }
    },
    async login(rawName, password, priorId) {
      const name = username(rawName);
      const record = name ? find.get(name) : null;
      if (!await matches(password, record?.enabled ? record : null) || !record?.enabled) throw loginError();
      return transaction(db, () => {
        const current = find.get(name);
        if (!current?.enabled || current.hash !== record.hash || current.salt !== record.salt) throw loginError();
        const id = randomBytes(32).toString('hex');
        if (hex.test(priorId || '')) db.prepare('DELETE FROM sessions WHERE id = ?').run(digest(priorId));
        db.prepare('DELETE FROM sessions WHERE expires <= ?').run(time());
        db.prepare(`
          DELETE FROM sessions WHERE id IN (
            SELECT id FROM sessions WHERE name = ? ORDER BY expires DESC, rowid DESC LIMIT -1 OFFSET 7
          )
        `).run(name);
        db.prepare('INSERT INTO sessions VALUES (?, ?, ?)').run(digest(id), name, time() + sessionLifetime);
        return { id, maxAge: sessionLifetime };
      });
    },
    logout(id) {
      if (hex.test(id || '')) db.prepare('DELETE FROM sessions WHERE id = ?').run(digest(id));
    },
    list(id) {
      needUser(id, true);
      return db.prepare('SELECT name AS username, role, enabled FROM users ORDER BY name').all()
        .map((user) => ({ ...user, enabled: Boolean(user.enabled) }));
    },
    async add(id, rawName, role, password) {
      needUser(id, true);
      const name = username(rawName);
      if (!name || !roles.has(role)) throw new AccountError(400, 'Enter a valid username and role.');
      const record = await passwordRecord(password, name);
      transaction(db, () => {
        needUser(id, true);
        if (find.get(name)) throw new AccountError(409, 'That username already exists.');
        if (db.prepare('SELECT count(*) AS total FROM users').get().total >= 100) {
          throw new AccountError(409, 'This installation has reached its user limit.');
        }
        db.prepare('INSERT INTO users VALUES (?, ?, 1, ?, ?)').run(name, role, record.salt, record.hash);
      });
    },
    async reset(id, rawName, password) {
      needUser(id, true);
      const { name } = target(rawName);
      const record = await passwordRecord(password, name);
      transaction(db, () => {
        needUser(id, true);
        replacePassword.run(record.salt, record.hash, name);
        clearSessions.run(name);
      });
    },
    status(id, rawName, enabled) {
      if (typeof enabled !== 'boolean') throw new AccountError(400, 'Choose enabled or disabled.');
      transaction(db, () => {
        needUser(id, true);
        const user = target(rawName);
        if (!enabled && user.enabled && user.role === 'administrator' &&
            db.prepare("SELECT count(*) AS total FROM users WHERE role = 'administrator' AND enabled = 1").get().total === 1) {
          throw new AccountError(409, 'Keep at least one administrator enabled.');
        }
        db.prepare('UPDATE users SET enabled = ? WHERE name = ?').run(Number(enabled), user.name);
        if (!enabled) clearSessions.run(user.name);
      });
    },
    async change(id, current, password) {
      const { name } = needUser(id);
      const previous = find.get(name);
      if (!await matches(current, previous)) throw new AccountError(400, 'The current password is incorrect.');
      const record = await passwordRecord(password, name);
      transaction(db, () => {
        needUser(id);
        if (find.get(name).hash !== previous.hash) throw loginError();
        replacePassword.run(record.salt, record.hash, name);
        clearSessions.run(name);
      });
    },
    revokeAll() {
      db.exec('DELETE FROM sessions');
    },
  };
}
