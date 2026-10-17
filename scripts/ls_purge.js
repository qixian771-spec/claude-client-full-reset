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
// Run through common.cli so failures print the sanitised [ERROR] and
// [下一步] lines that formatError relays, never a traceback.
const STOPPED_CHECK = [
  'import sys, common',
  'def check():',
  '    common.require_supported()',
  '    common.require_stopped()',
  '    return 0',
  'sys.exit(common.cli(check))',
].join('\n');
function requireStopped(run = execFileSync) {
  python(['-c', STOPPED_CHECK], run);
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
// Only numbered tables (.ldb/.sst) and write-ahead logs (.log) hold records.
const RECORD_FILE = /^\d+\.(?:ldb|sst|log)$/;
// LevelDB writes MANIFEST-000001 before CURRENT when it creates a database,
// and treats a directory without CURRENT as "does not exist". A browser can
// leave the directory unused or stop mid-creation (seen with Edge on
// Windows). Without CURRENT and without any record file there are no keys:
// report it as empty. Record files without CURRENT may be damage and stop.
function levelState(dir) {
  const names = fs.readdirSync(dir).sort();
  if (names.includes('CURRENT')) return { state: 'database', names };
  if (names.some(name => RECORD_FILE.test(name))) {
    throw new Error('LevelDB has record files but no CURRENT; possibly damaged: ' + dir +
      ' (files: ' + names.join(', ') + ')');
  }
  return { state: 'empty', names };
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
  if (values.browser && !roots.some(([name]) => name === values.browser)) {
    throw new Error('Unknown browser; valid names: ' + roots.map(([name]) => name).join(', '));
  }
  let profiles = 0;
  const plan = [];
  for (const [name, root] of roots) {
    if (values.browser && name !== values.browser) continue;
    for (const [profile, folder] of iterProfiles(root)) {
      if (values.profile && profile !== values.profile) continue;
      profiles++;
      const dir = path.join(folder, 'Local Storage/leveldb');
      if (!exists(dir)) continue;
      const level = levelState(dir);
      if (level.state === 'empty') {
        console.log(`[EMPTY] ${name}/${profile}: Local Storage LevelDB never completed creation ` +
          `(no CURRENT, no record files; files: ${level.names.join(', ') || 'none'}); counted as 0, not opened`);
        continue;
      }
      const count = await purgeDir(dir);
      if (count) {
        if (values.apply) requireCovered(values.backup, dir);
        plan.push({ name, profile, dir, count });
      }
    }
  }
  if ((values.browser || values.profile) && !profiles) {
    throw new Error('Selected browser/profile does not exist; run python scripts/browser_scan.py to see the real ' +
      'browser names and profile folder names (e.g. Default, Profile 1)');
  }
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
// Do not print database keys, values or arbitrary subprocess output: first
// lines only. LevelDB causes carry a status and file path, which explain why
// a database could not be opened. From our own Python entry points only the
// already-sanitised [ERROR] / [下一步] lines are relayed.
const RELAYED = /^\[(?:ERROR|下一步)\] /;
function formatError(error) {
  if (typeof error.stderr === 'string') {
    const relayed = error.stderr.split(/\r?\n/).filter(text => RELAYED.test(text));
    if (relayed.length) return relayed.join('\n');
  }
  const line = item => (item.code ? item.code + ': ' : '') + String(item.message).split('\n')[0];
  let text = '[ERROR] ' + line(error) + (error.cause instanceof Error ? ' (cause: ' + line(error.cause) + ')' : '');
  if (error.code === 'ENOENT' && String(error.syscall || '').startsWith('spawn')) {
    text += '\n[下一步] 找不到 Python：安装 Python 3.10+（Windows 需带 py 启动器），' +
      '或把环境变量 CLAUDE_RESET_PYTHON 设为 python 可执行文件的完整路径后重试';
  }
  return text;
}
module.exports = { purgeDir, operate, inventory, iterProfiles, requireStopped, browserRoots, pythonCommand, formatError, levelState, main };
if (require.main === module) {
  main().catch(error => {
    console.error(formatError(error));
    process.exitCode = 2;
  });
}
