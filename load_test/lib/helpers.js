// Small helpers for building request payloads and reusable checks.
import { check } from 'k6';

// Pick a random element from an array.
export function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// Build a randomized transaction body for POST /api/transaction/.
// Amounts are in paise (integer minor units).
export function randomTransaction(accountId) {
  const type = pick(['credit', 'debit']);
  return {
    account_id: accountId,
    type: type,
    amount: Math.floor(Math.random() * 10000) + 1, // 1..10000 paise
    description: `k6 ${type}`,
    occured_at: new Date().toISOString(),
  };
}

// Standard 2xx check. `name` labels the check in the k6 summary.
export function is2xx(res, name) {
  return check(res, {
    [`${name} status is 2xx`]: (r) => r.status >= 200 && r.status < 300,
  });
}
