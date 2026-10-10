#!/usr/bin/env node
/* =============================================================================
 * claude-client-full-reset :: Local Storage · LevelDB 按 key 精删
 * -----------------------------------------------------------------------------
 * 契约：
 *   - 默认 dry-run，只列出待删 key；加 --apply 才真删。
 *   - 浏览器在运行 → 直接拒绝（LevelDB 需独占锁，且改动会被回写覆盖）。
 *   - ⚠️ 必须理解边界：del() 是【逻辑删除】——tombstone 写下去后 key 不可见，
 *        但旧 .ldb 文件里的【物理字节仍在】，字节扫描依旧命中。
 *        判据是「功能上不存在」→ 精删足够。
 *        判据是「磁盘上无痕迹」→ 必须整目录删 Local Storage（用 trash_paths.sh）。
 *
 * 依赖：classic-level（预编译绑定，避开 plyvel 在 macOS 上的 C++ ABI 符号缺失）
 *   npm i classic-level
 *   NODE_PATH=/path/to/node_modules node scripts/ls_purge.js --apply
 *
 * 用法：
 *   node scripts/ls_purge.js                  # dry-run 全部 profile
 *   node scripts/ls_purge.js --apply
 *   node scripts/ls_purge.js --apply --profile "Profile 7"
 * ========================================================================== */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

let ClassicLevel;
try {
  ({ ClassicLevel } = require('classic-level'));
} catch (e) {
  console.error('✗ 缺少依赖 classic-level。');
  console.error('  npm i classic-level');
  console.error('  NODE_PATH=<node_modules路径> node scripts/ls_purge.js --apply');
  console.error('  （为什么不用 plyvel：macOS 上常报 symbol not found: __ZTIN7leveldb10ComparatorE）');
  process.exit(2);
}

const APPLY = process.argv.includes('--apply');
const ONLY = (() => {
  const i = process.argv.indexOf('--profile');
  return i >= 0 ? process.argv[i + 1] : null;
})();

const HOME = os.homedir();
const APPSUP = path.join(HOME, 'Library', 'Application Support');
const BROWSERS = [
  ['Chrome', path.join(APPSUP, 'Google', 'Chrome')],
  ['Chrome Beta', path.join(APPSUP, 'Google', 'Chrome Beta')],
  ['Edge', path.join(APPSUP, 'Microsoft Edge')],
  ['Brave', path.join(APPSUP, 'BraveSoftware', 'Brave-Browser')],
  ['Vivaldi', path.join(APPSUP, 'Vivaldi')],
  ['Chromium', path.join(APPSUP, 'Chromium')],
  ['Arc', path.join(APPSUP, 'Arc', 'User Data')],
];
const RE = /claude|anthropic/i;
const SKIP_SHUTDOWN = ['Google Chrome', 'Google Chrome Beta', 'Microsoft Edge',
  'Brave Browser', 'Vivaldi', 'Chromium', 'Arc'];

function browsersRunning() {
  try {
    const out = execSync('ps -eo comm=', { encoding: 'utf8' });
    const set = new Set(out.split('\n').map(s => s.trim()));
    return SKIP_SHUTDOWN.filter(n => set.has(n));
  } catch (e) { return []; }
}

function iterProfiles(root) {
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root)
    .filter(n => {
      const d = path.join(root, n);
      return fs.statSync(d).isDirectory() &&
        (fs.existsSync(path.join(d, 'Preferences')) ||
         fs.existsSync(path.join(d, 'Cookies')));
    })
    .map(n => [n, path.join(root, n)]);
}

async function purgeDir(dir) {
  const db = new ClassicLevel(dir, { createIfMissing: false });
  await db.open();
  const toDel = [];
  for await (const [k] of db.iterator()) {
    if (RE.test(k.toString('latin1'))) toDel.push(k);
  }
  if (APPLY) {
    for (const k of toDel) await db.del(k);
  }
  await db.close();
  return toDel.map(k => k.toString('utf8').slice(0, 90));
}

(async () => {
  console.log('═══ Local Storage · LevelDB 按 key 精删 ' +
    (APPLY ? '[APPLY]' : '[DRY-RUN]') + ' ═══');

  const alive = browsersRunning();
  if (alive.length) {
    console.log('  ⛔ 拒绝执行：正在运行 → ' + alive.join(', '));
    console.log('     先退出浏览器（osascript -e \'tell application "Google Chrome" to quit\'）');
    process.exit(2);
  }

  let nDir = 0, nKey = 0;
  for (const [bname, root] of BROWSERS) {
    for (const [prof, bdir] of iterProfiles(root)) {
      if (ONLY && prof !== ONLY) continue;
      const ls = path.join(bdir, 'Local Storage', 'leveldb');
      if (!fs.existsSync(ls)) continue;
      let keys = [];
      try {
        keys = await purgeDir(ls);
      } catch (e) {
        console.log('  [FAIL] ' + bname + '/' + prof + '  <' + e.message + '>');
        continue;
      }
      if (!keys.length) continue;
      nDir++; nKey += keys.length;
      console.log('  [' + (APPLY ? 'APPLY' : 'DRY ') + '] ' + bname + '/' + prof +
        '  ' + keys.length + ' 个 key');
      keys.slice(0, 8).forEach(k => console.log('          · ' + k));
      if (keys.length > 8) console.log('          · …另有 ' + (keys.length - 8) + ' 个');
    }
  }

  console.log('─'.repeat(60));
  console.log('  涉及目录: ' + nDir + '    ' + (APPLY ? '已删' : '待删') + ' key: ' + nKey);

  if (!APPLY && nKey) {
    console.log('  加 --apply 执行。');
  } else if (APPLY) {
    console.log('  ⚠️  这是逻辑删除 —— 旧 .ldb 里物理字节仍在。');
    console.log('      若验收判据是「磁盘上无痕迹」，请改用整目录删：');
    console.log('        bash scripts/trash_paths.sh "<profile>/Local Storage"');
  }
  console.log('═'.repeat(60));
})();
