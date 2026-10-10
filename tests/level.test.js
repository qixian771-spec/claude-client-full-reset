const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ClassicLevel } = require('classic-level');
const { purgeDir, operate, inventory, requireStopped, iterProfiles } = require('../scripts/ls_purge');

async function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'reset-level-test-'));
  t.after(() => fs.rmSync(root, { recursive: true }));
  const dir = path.join(root, 'db');
  const db = new ClassicLevel(dir, { keyEncoding: 'buffer', valueEncoding: 'buffer' });
  await db.open();
  const target = Buffer.concat([Buffer.from('_https://claude.ai\0\x01'), Buffer.from([0xff, 0xfe])]);
  const unrelated = Buffer.from('_https://example.com\0\x01claude');
  await db.put(target, Buffer.from('secret-token'));
  await db.put(unrelated, Buffer.from('retain'));
  await db.close();
  return { root, dir, target, unrelated };
}

test('preview leaves original bytes and all binary keys unchanged', async t => {
  const { dir } = await fixture(t);
  const before = inventory(dir);
  assert.equal(await purgeDir(dir), 1);
  assert.deepEqual(inventory(dir), before);
});
test('apply deletes exact binary key and preserves unrelated data', async t => {
  const { dir, target, unrelated } = await fixture(t);
  assert.equal(await purgeDir(dir, true), 1);
  const db = new ClassicLevel(dir, { keyEncoding: 'buffer', valueEncoding: 'buffer' });
  await db.open();
  try {
    assert.equal(await db.get(target), undefined);
    assert.equal((await db.get(unrelated)).toString(), 'retain');
  } finally { await db.close(); }
});
test('failed process query propagates', () => {
  assert.throws(() => requireStopped(() => { throw new Error('ps failed'); }), /ps failed/);
});
test('missing DB errors rather than creates database', async t => {
  const { root } = await fixture(t);
  const dir = path.join(root, 'missing');
  await assert.rejects(purgeDir(dir));
  assert.equal(fs.existsSync(dir), false);
});
test('symlink refusal', async t => {
  const { root, dir } = await fixture(t);
  const link = path.join(root, 'link');
  fs.symlinkSync(dir, link);
  await assert.rejects(purgeDir(link), /symlink/);
});
test('iteration failure propagates and closes resource', async () => {
  let closed = false;
  class Broken {
    async open() {}
    async *iterator() { throw new Error('read denied'); }
    async close() { closed = true; }
  }
  await assert.rejects(operate('fixture', false, Broken), /read denied/);
  assert.equal(closed, true);
});
test('batch failure propagates and closes resource', async () => {
  let closed = false;
  class Broken {
    async open() {}
    async *iterator() { yield [Buffer.from('_https://claude.ai\0key'), Buffer.from('value')]; }
    async batch() { throw new Error('write failed'); }
    async close() { closed = true; }
  }
  await assert.rejects(operate('fixture', true, Broken), /write failed/);
  assert.equal(closed, true);
});
test('discovers Network-only profiles and Canary-style paths', async t => {
  const { root } = await fixture(t);
  fs.mkdirSync(path.join(root, 'Custom/Network'), { recursive: true });
  assert.equal(iterProfiles(root).some(([name]) => name === 'Custom'), true);
});
test('open failure closes handle and returns error', async () => {
  let closed = false;
  class Broken {
    async open() { throw new Error('locked'); }
    async close() { closed = true; }
  }
  await assert.rejects(operate('fixture', false, Broken), /locked/);
  assert.equal(closed, true);
});
test('damaged DB cannot be interpreted as an empty DB', async t => {
  const { dir } = await fixture(t);
  fs.writeFileSync(path.join(dir, 'CURRENT'), 'invalid manifest');
  await assert.rejects(purgeDir(dir));
});
