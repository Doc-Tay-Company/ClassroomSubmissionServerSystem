const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(path.join(__dirname, '../static/js/admin.js'), 'utf8');
const start = source.indexOf('  $("import-form")?.addEventListener("submit", async (event) => {');
const end = source.indexOf('  $("notification-form")?.addEventListener("submit", async (event) => {', start);
assert(start >= 0 && end > start, 'account import handler boundaries exist');
const handlerSource = source.slice(start, end);

async function runCase({ response, requestError, refreshError } = {}) {
  const form = { resetCount: 0, reset() { this.resetCount += 1; } };
  const result = { textContent: '', errors: [], classList: { remove() {} }, style: {} };
  const requests = [];
  const toastErrors = [];
  let accountRefreshes = 0;
  let monitorRefreshes = 0;
  let event;
  const context = {
    $: (id) => ({ 'import-form': { addEventListener(type, callback) { this.handler = callback; runCase.handler = callback; } }, 'import-result': result }[id]),
    document: {},
    window: {
      cssRequest: async (url, options) => {
        requests.push({ url, options });
        await Promise.resolve();
        event.currentTarget = null;
        if (requestError) throw requestError;
        return response;
      },
    },
    FormData: class { constructor(sourceForm) { this.form = sourceForm; } },
    loadAccounts: async () => { accountRefreshes += 1; if (refreshError) throw refreshError; },
    loadMonitor: async () => { monitorRefreshes += 1; },
    show: (id, message, isError) => { result.textContent = message; if (isError) result.errors.push(message); },
    toastError: (error) => toastErrors.push(error.message),
  };
  vm.createContext(context);
  vm.runInContext(handlerSource, context);
  event = { currentTarget: form, preventDefault() {} };
  await runCase.handler(event);
  return { form, result, requests, toastErrors, accountRefreshes, monitorRefreshes };
}

async function main() {
  const success = await runCase({ response: { created_count: 1, created: ['S123'], duplicates: [], errors: [] } });
  assert.strictEqual(success.form.resetCount, 1, 'successful create resets the captured form reference');
  assert(success.result.textContent.includes('S123') || success.result.textContent.includes('1'), 'success feedback reports the created account count');
  assert.strictEqual(success.accountRefreshes, 1, 'success refreshes the account list');
  assert.strictEqual(success.monitorRefreshes, 1, 'success refreshes related monitoring data');
  assert.strictEqual(success.requests.length, 1, 'success sends one create request and never retries');

  const duplicate = await runCase({ response: { created_count: 0, created: [], duplicates: ['S123'], errors: [] } });
  assert(duplicate.result.textContent.includes('1') && duplicate.result.textContent.includes('MSSV'), 'existing Student ID is reported as skipped');
  assert.strictEqual(duplicate.form.resetCount, 1, 'duplicate-only successful response clears the submitted form');
  assert.strictEqual(duplicate.requests.length, 1, 'duplicate handling does not retry creation');

  const failure = await runCase({ requestError: new Error('Student ID already exists') });
  assert(failure.result.errors.some((message) => message.includes('Student ID already exists')), 'API failure displays the actual error');
  assert.strictEqual(failure.form.resetCount, 0, 'failed create retains form content');
  assert.strictEqual(failure.accountRefreshes, 0, 'failed create does not refresh as if it succeeded');
  assert.strictEqual(failure.requests.length, 1, 'failed create is not automatically retried');

  const staleList = await runCase({ response: { created_count: 1, created: ['S123'], duplicates: [], errors: [] }, refreshError: new Error('refresh unavailable') });
  assert(staleList.result.textContent.includes('đã tạo 1 tài khoản') && staleList.result.textContent.includes('không thể làm mới'),
    'refresh failure does not falsely claim account creation failed');
  assert.strictEqual(staleList.requests.length, 1, 'refresh failure does not repeat the create request');
  console.log('PASS account import success, duplicate, API failure, and refresh failure');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
