// Central place for all knobs. Everything is overridable from the CLI with
// `-e KEY=value` (read here from k6's __ENV), so you never edit code to change a run.

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

// Which scenario to run. One of: smoke | load | stress | spike.
export const SCENARIO = __ENV.SCENARIO || 'smoke';

// Starting balance (in paise) for each account created in setup().
export const START_BALANCE_PAISE = Number(__ENV.START_BALANCE_PAISE || 100000000);

// How many accounts setup() seeds. Traffic is spread randomly across all of them,
// so reads hit many different cache keys and — crucially — writes no longer all
// contend on ONE hot account row (see the write-contention discussion). Set to 1
// to reproduce the old single-account behaviour.
export const NUM_ACCOUNTS = Number(__ENV.NUM_ACCOUNTS || 100);

// Pass/fail gates applied to every run. Tune these as you learn your system's limits.
export const thresholds = {
  http_req_failed: ['rate<0.01'],       // <1% of requests may fail
  http_req_duration: ['p(95)<500'],     // 95% of requests under 500ms
};

// Scenario definitions. Only the one named by SCENARIO is activated (see main.js).
// All drive the same `exec: 'traffic'` function.
const allScenarios = {
  // Sanity check: a single user, everything should be green. Gate CI on this.
  smoke: {
    executor: 'constant-vus',
    vus: 1,
    duration: '1m',
    exec: 'traffic',
    tags: { scenario: 'smoke' },
  },

  // Expected steady-state traffic: ramp up, hold, ramp down.
  load: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '2m', target: 50 },
      { duration: '5m', target: 50 },
      { duration: '1m', target: 0 },
    ],
    exec: 'traffic',
    tags: { scenario: 'load' },
  },

  // Find the knee: keep climbing until latency/errors degrade.
  stress: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '1m', target: 50 },
      { duration: '2m', target: 100 },
      { duration: '2m', target: 200 },
      { duration: '2m', target: 400 },
      { duration: '2m', target: 0 },
    ],
    exec: 'traffic',
    tags: { scenario: 'stress' },
  },

  // Stepped ramps for capacity testing across user bands. Run each in turn
  // (-e SCENARIO=tier1|tier2|tier3) to see where latency/errors bend as you climb.
  tier1: {
    executor: 'ramping-vus',
    startVUs: 1,
    stages: [
      { duration: '1m', target: 100 },
      { duration: '2m', target: 100 },
      { duration: '30s', target: 0 },
    ],
    exec: 'traffic',
    tags: { scenario: 'tier1' },
  },
  tier2: {
    executor: 'ramping-vus',
    startVUs: 100,
    stages: [
      { duration: '1m', target: 500 },
      { duration: '2m', target: 500 },
      { duration: '30s', target: 0 },
    ],
    exec: 'traffic',
    tags: { scenario: 'tier2' },
  },
  tier3: {
    executor: 'ramping-vus',
    startVUs: 500,
    stages: [
      { duration: '1m', target: 1000 },
      { duration: '2m', target: 1000 },
      { duration: '30s', target: 0 },
    ],
    exec: 'traffic',
    tags: { scenario: 'tier3' },
  },

  // Sudden surge then drop: tests how fast the system recovers.
  spike: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '10s', target: 300 },
      { duration: '1m', target: 300 },
      { duration: '10s', target: 0 },
      { duration: '30s', target: 0 },
    ],
    exec: 'traffic',
    tags: { scenario: 'spike' },
  },
};

export function selectedScenario() {
  const s = allScenarios[SCENARIO];
  if (!s) {
    throw new Error(
      `Unknown SCENARIO="${SCENARIO}". Use one of: ${Object.keys(allScenarios).join(', ')}`,
    );
  }
  return { [SCENARIO]: s };
}
