// k6 load test for the FastAPI banking lab.
//
// Run one scenario at a time with -e SCENARIO=smoke|load|stress|spike.
// Example (streaming metrics into Grafana via Prometheus remote-write):
//
//   K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write \
//   K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),min,max" \
//   k6 run -o experimental-prometheus-rw -e SCENARIO=load load_test/main.js
//
// Plain run (terminal summary only):
//   k6 run -e SCENARIO=smoke load_test/main.js

import http from 'k6/http';
import { sleep } from 'k6';
import {
  BASE_URL,
  START_BALANCE_PAISE,
  thresholds,
  selectedScenario,
} from './lib/config.js';
import { randomTransaction, is2xx } from './lib/helpers.js';

const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };

export const options = {
  scenarios: selectedScenario(),
  thresholds: thresholds,
};

// setup() runs once before the test. It creates the account every VU will hit,
// so the load test is fully self-contained (no manual DB seeding needed).
// The returned value is passed to every iteration of traffic().
export function setup() {
  const res = http.post(
    `${BASE_URL}/api/account`,
    JSON.stringify({ balance_paise: START_BALANCE_PAISE }),
    JSON_HEADERS,
  );
  if (res.status !== 201 && res.status !== 200) {
    throw new Error(`setup failed to create account: ${res.status} ${res.body}`);
  }
  const accountId = res.json('id');
  console.log(`setup: created account id=${accountId}`);
  return { accountId };
}

// The workload each virtual user runs, on repeat. Read-heavy mix (~80/20):
// 40% GET account, 40% GET transactions, 20% POST transaction.
export function traffic(data) {
  const id = data.accountId;
  const roll = Math.random();

  if (roll < 0.4) {
    const res = http.get(`${BASE_URL}/api/account?account_id=${id}`, {
      tags: { name: 'GET /account' },
    });
    is2xx(res, 'GET /account');
  } else if (roll < 0.8) {
    const res = http.get(`${BASE_URL}/api/transaction/?account_id=${id}`, {
      tags: { name: 'GET /transaction' },
    });
    is2xx(res, 'GET /transaction');
  } else {
    const res = http.post(
      `${BASE_URL}/api/transaction/`,
      JSON.stringify(randomTransaction(id)),
      { ...JSON_HEADERS, tags: { name: 'POST /transaction' } },
    );
    is2xx(res, 'POST /transaction');
  }

  sleep(0.5); // brief think-time between requests
}
