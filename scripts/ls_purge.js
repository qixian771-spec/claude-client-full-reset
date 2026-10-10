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

const BROWSERS = [
  ['Chrome', 'Google/Chrome'], ['Chrome Beta', 'Google/Chrome Beta'],
  ['Chrome Canary', 'Google/Chrome Canary'], ['Edge', 'Microsoft Edge'],
  ['Brave', 'BraveSoftware/Brave-Browser'], ['Vivaldi', 'Vivaldi'],
  ['Chromium', 'Chromium'], ['Arc', 'Arc/User Data'],
];
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
function requireStopped(run = execFileSync) {
  // Share the same process rules with the Python entry points.
  run('python3', ['-c', 'import common; common.require_macos(); common.require_stopped()'],
    { cwd: __dirname, encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'pipe'] });
}
function requireCovered(backupDir, dir) {
  execFileSync('python3', [path.join(__dirname, 'backup.py'), '--check-path', dir, '--backup', backupDir],
    { encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'pipe'] });
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
    console.log('node scripts/ls_purge.js [--browser NAME] [--profile NAME] [--apply --backup /absolute/backup]');
    return;
  }
  if (process.platform !== 'darwin') throw new Error('Only macOS is supported');
  if (values.apply && !values.backup) throw new Error('--apply requires --backup');
  if (values.browser && !BROWSERS.some(([name]) => name === values.browser)) throw new Error('Unknown browser');
  requireStopped();
  let profiles = 0;
  const plan = [];
  for (const [name, relative] of BROWSERS) {
    if (values.browser && name !== values.browser) continue;
    for (const [profile, folder] of iterProfiles(path.join(os.homedir(), 'Library/Application Support', relative))) {
      if (values.profile && profile !== values.profile) continue;
      profiles++;
      const dir = path.join(folder, 'Local Storage/leveldb');
      if (!exists(dir)) continue;
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
module.exports = { purgeDir, operate, inventory, iterProfiles, requireStopped, main };
if (require.main === module) {
  main().catch(error => {
    // Do not print database keys, values or captured subprocess stdout/stderr.
    console.error('[ERROR] ' + (error.code ? error.code + ': ' : '') + error.message.split('\n')[0]);
    process.exitCode = 2;
  });
}
