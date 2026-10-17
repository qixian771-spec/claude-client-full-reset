#!/usr/bin/env node
'use strict';
// Default preview opens a disposable copy. Apply requires a verified backup.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { parseArgs } = require('node:util');
function loadDatabase() {
  try { return require('classic-level').ClassicLevel; }
  catch (error) { throw new Error('无法加载 classic-level (' + error.code + ')；请在 skill 目录执行 npm ci'); }
}

const DOMAIN = /(?:^|[^a-z0-9.-])\.?(?:[a-z0-9-]+\.)*(?:claude\.ai|anthropic\.com)(?=[:/?#\x00]|$)/i;

function exists(file) {
  try { fs.lstatSync(file); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}
function fileHash(file) {
  const digest = crypto.createHash('sha256');
  const fd = fs.openSync(file, 'r');
  try {
    const buffer = Buffer.alloc(1024 * 1024);
    let count;
    while ((count = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) digest.update(buffer.subarray(0, count));
    return digest.digest('hex');
  } finally { fs.closeSync(fd); }
}
function inventory(root, prefix = '') {
  const info = fs.lstatSync(root);
  if (info.isSymbolicLink()) throw new Error('Refusing symlink: ' + root);
  if (info.isFile()) return [[prefix, fileHash(root)]];
  if (!info.isDirectory()) throw new Error('Unsupported file type: ' + root);
  const items = [[prefix, '<directory>']];
  for (const name of fs.readdirSync(root).sort()) {
    items.push(...inventory(path.join(root, name), prefix + '/' + name));
  }
  return items;
}
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
// Platform rules (processes, browser roots, backups) live only in the Python
// scripts. The interpreter is explicit: CLAUDE_RESET_PYTHON when set, else
// the documented launcher for this OS. A missing interpreter is an error.
function pythonCommand(env = process.env, platform = process.platform) {
  if (env.CLAUDE_RESET_PYTHON) return [env.CLAUDE_RESET_PYTHON, []];
  return platform === 'win32' ? ['py', ['-3']] : ['python3', []];
}
function python(args, run = execFileSync) {
  const [command, prefix] = pythonCommand();
  return run(command, [...prefix, ...args],
    { cwd: __dirname, encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'pipe'] });
}
function requireStopped(run = execFileSync) {
  python(['-c', 'import common; common.require_supported(); common.require_stopped()'], run);
}
function requireCovered(backupDir, dir) {
  python([path.join(__dirname, 'backup.py'), '--check-path', dir, '--backup', backupDir]);
}
function browserRoots(run = execFileSync) {
  const roots = JSON.parse(python([path.join(__dirname, 'platforms.py'), '--browser-roots'], run));
  if (!Array.isArray(roots) || !roots.every(item => Array.isArray(item) && item.length === 2 &&
      item.every(part => typeof part === 'string'))) {
    throw new Error('Invalid browser root list from platforms.py');
  }
  return roots;
}
function iterProfiles(root) {
  if (!exists(root)) return [];
  const info = fs.lstatSync(root);
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error('Invalid browser root: ' + root);
  return fs.readdirSync(root).sort().flatMap(name => {
    const folder = path.join(root, name);
    const info = fs.lstatSync(folder);
    if (info.isSymbolicLink()) throw new Error('Refusing symlink: ' + folder);
    if (!info.isDirectory()) return [];
    return name === 'Default' || name.startsWith('Profile ') ||
      ['Preferences', 'Cookies', 'History', 'Network'].some(n => exists(path.join(folder, n)))
      ? [[name, folder]] : [];
  });
}
// LevelDB data: numbered tables/logs, manifests and temporary manifest files.
const DATA_FILE = /^(?:\d+\.(?:ldb|log|sst|dbtmp)|MANIFEST-\d+)$/;
// A browser may create the directory before writing any data. Only a
// directory with neither CURRENT nor any data file counts as empty; data
// without CURRENT may be damaged and stops the run.
function levelState(dir) {
  const names = fs.readdirSync(dir).sort();
  if (names.includes('CURRENT')) return 'database';
  const data = names.filter(name => DATA_FILE.test(name));
  if (data.length) {
    throw new Error('LevelDB has data files but no CURRENT; possibly damaged: ' + dir +
      ' (files: ' + names.join(', ') + ')');
  }
  return 'empty';
}
async function operate(dir, apply, Database = loadDatabase()) {
  const db = new Database(dir, { createIfMissing: false, keyEncoding: 'buffer', valueEncoding: 'buffer' });
  try {
    await db.open();
    const keys = [];
    for await (const [key] of db.iterator()) {
      if (DOMAIN.test(key.toString('latin1'))) keys.push(key);
    }
    if (apply && keys.length) {
      await db.batch(keys.map(key => ({ type: 'del', key })), { sync: true });
      for (const key of keys) {
        const value = await db.get(key);
        if (value !== undefined) throw new Error('Key still exists after deletion');
      }
    }
    return keys.length;
  } finally { await db.close(); }
}
async function purgeDir(dir, apply = false, Database = loadDatabase()) {
  const before = inventory(dir);
  if (apply) return operate(dir, true, Database);
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-level-preview-'));
  try {
    const copy = path.join(temp, 'db');
    fs.cpSync(dir, copy, { recursive: true, errorOnExist: true, force: false });
    if (!same(before, inventory(copy)) || !same(before, inventory(dir))) {
      throw new Error('LevelDB changed during snapshot');
    }
    const count = await operate(copy, false, Database);
    if (!same(before, inventory(dir))) throw new Error('LevelDB changed during preview');
    return count;
  } finally {
    // Only remove the scratch directory created above, never user data.
    fs.rmSync(temp, { recursive: true });
  }
}
async function main() {
  const { values } = parseArgs({ options: {
    apply: { type: 'boolean', default: false }, backup: { type: 'string' },
    browser: { type: 'string' }, profile: { type: 'string' }, help: { type: 'boolean' },
  } });
  if (values.help) {
    console.log('node scripts/ls_purge.js [--browser NAME] [--profile NAME] [--apply --backup ABSOLUTE_BACKUP_DIR]');
    console.log('Python: CLAUDE_RESET_PYTHON if set, otherwise python3 (macOS) or py -3 (Windows).');
    return;
  }
  if (values.apply && !values.backup) throw new Error('--apply requires --backup');
  requireStopped();
  const roots = browserRoots();
  if (values.browser && !roots.some(([name]) => name === values.browser)) throw new Error('Unknown browser');
  let profiles = 0;
  const plan = [];
  for (const [name, root] of roots) {
    if (values.browser && name !== values.browser) continue;
    for (const [profile, folder] of iterProfiles(root)) {
      if (values.profile && profile !== values.profile) continue;
      profiles++;
      const dir = path.join(folder, 'Local Storage/leveldb');
      if (!exists(dir)) continue;
      if (levelState(dir) === 'empty') {
        console.log(`[EMPTY] ${name}/${profile}: Local Storage LevelDB not initialised (no CURRENT, no data files); counted as 0, not opened`);
        continue;
      }
      const count = await purgeDir(dir);
      if (count) {
        if (values.apply) requireCovered(values.backup, dir);
        plan.push({ name, profile, dir, count });
      }
    }
  }
  if ((values.browser || values.profile) && !profiles) throw new Error('Selected browser/profile does not exist');
  for (const item of plan) {
    if (values.apply) {
      requireStopped();
      requireCovered(values.backup, item.dir);
      item.count = await purgeDir(item.dir, true);
    }
    console.log(`[${values.apply ? 'APPLY' : 'DRY'}] ${item.name}/${item.profile}: keys=${item.count}`);
  }
  console.log(`matched_directories=${plan.length}; logical key deletion only, no forensic-erasure claim`);
}
// Do not print database keys, values or captured subprocess stdout/stderr:
// first lines only. LevelDB causes carry a status and file path, which
// explain why a database could not be opened.
function formatError(error) {
  const line = item => (item.code ? item.code + ': ' : '') + String(item.message).split('\n')[0];
  return '[ERROR] ' + line(error) + (error.cause instanceof Error ? ' (cause: ' + line(error.cause) + ')' : '');
}
module.exports = { purgeDir, operate, inventory, iterProfiles, requireStopped, browserRoots, pythonCommand, formatError, levelState, main };
if (require.main === module) {
  main().catch(error => {
    console.error(formatError(error));
    process.exitCode = 2;
  });
}
