const test = require('node:test');
const assert = require('node:assert/strict');
const {
  normalizeCodex,
  normalizeCodexCredits,
  normalizeCodexNewApi,
  normalizeCodexUsage,
  normalizeMiniMax,
  normalizeKimi,
  normalizeLongCat,
  normalizeQianwen,
  normalizeVolcengine,
  normalizeZhipu
} = require('../parser.js');

test('normalizes Codex reset credit count', () => {
  const result = normalizeCodexCredits({
    available_count: 4,
    credits: [
      { status: 'available', expires_at: '2026-07-31T20:32:32.581848Z' },
      { status: 'available', expires_at: '2026-07-27T00:09:42.875222Z' },
      { status: 'redeemed', expires_at: '2026-07-20T00:00:00Z' }
    ]
  });
  assert.equal(result.availableCount, 4);
  assert.equal(result.credits.length, 3);
  assert.equal(result.nextExpiresAt, '2026-07-27T00:09:42.875222Z');
});

test('normalizes Codex usage windows and seconds timestamps', () => {
  const result = normalizeCodexUsage({
    rate_limit: {
      primary_window: {
        used_percent: 55,
        limit_window_seconds: 604800,
        reset_after_seconds: 472615,
        reset_at: 1784498403
      },
      secondary_window: null
    },
    rate_limit_reset_credits: { available_count: 4 }
  });
  assert.equal(result.windows[0].name, 'weekly');
  assert.equal(result.windows[0].usedPercent, 55);
  assert.equal(result.windows[0].resetAt, 1784498403000);
  assert.equal(result.windows[1].available, false);
  assert.equal(result.resetCards, 4);
});

test('normalizes NewAPI Codex usage and reset cards together', () => {
  const result = normalizeCodexNewApi({
    rate_limit: {
      primary_window: { used_percent: 12, limit_window_seconds: 604800, reset_at: 1784498403 }
    },
    rate_limit_reset_credits: { available_count: 2 },
    credits: [{ status: 'available', expires_at: '2026-07-20T00:00:00Z' }]
  });
  assert.equal(result.usage.windows[0].usedPercent, 12);
  assert.equal(result.usage.resetCards, 2);
  assert.equal(result.credits.nextExpiresAt, '2026-07-20T00:00:00Z');
});

test('normalizes Codex reset credits and reset time', () => {
  assert.deepEqual(normalizeCodex({ remaining: 3, reset_at: '2026-07-15T00:00:00Z' }), {
    remaining: 3,
    resetAt: '2026-07-15T00:00:00Z',
    windows: []
  });
});

test('normalizes Codex five-hour and weekly quota windows', () => {
  const result = normalizeCodex({ model_remains: [{
    model_name: 'codex',
    start_time: 1784012400000,
    end_time: 1784030400000,
    current_interval_used_percent: '44%',
    current_interval_total_percent: '100%',
    weekly_start_time: 1783872000000,
    weekly_end_time: 1784476800000,
    current_weekly_used_percent: '12%',
    current_weekly_total_percent: '100%'
  }] });
  assert.equal(result.windows[0].interval.usedPercent, 44);
  assert.equal(result.windows[0].weekly.usedPercent, 12);
  assert.equal(result.windows[0].weekly.resetAt, 1784476800000);
});

test('normalizes MiniMax remaining percentage', () => {
  assert.deepEqual(normalizeMiniMax({ data: { remains_percent: 72 } }), {
    limit: 100,
    used: 28,
    remaining: 72,
    unit: '%',
    windows: []
  });
});

test('normalizes MiniMax interval and weekly quota windows', () => {
  const result = normalizeMiniMax({ model_remains: [{
    model_name: 'MiniMax-M2',
    current_interval_used_percent: '44%',
    current_interval_total_percent: '100%',
    end_time: 1784030400000,
    weekly_start_time: 1783872000000,
    weekly_end_time: 1784476800000,
    current_weekly_used_percent: '0%',
    current_weekly_total_percent: '100%'
  }] });
  assert.equal(result.windows[0].interval.usedPercent, 44);
  assert.equal(result.windows[0].interval.remainingPercent, 56);
  assert.equal(result.windows[0].weekly.resetAt, 1784476800000);
});

test('uses MiniMax five-hour window for the headline usage when available', () => {
  const result = normalizeMiniMax({
    remains_percent: 0,
    model_remains: [{
      model_name: 'MiniMax-M2',
      current_interval_used_percent: '0%',
      current_interval_total_percent: '100%',
      end_time: 1784030400000
    }]
  });
  assert.equal(result.used, 0);
  assert.equal(result.remaining, 100);
});

test('normalizes Volcengine plan usage from used and total fields', () => {
  assert.deepEqual(normalizeVolcengine({ data: { total: 1000, used: 245 } }), {
    limit: 1000,
    used: 245,
    remaining: 755,
    unit: '次',
    periods: [],
    details: []
  });
});

test('normalizes Volcengine session weekly and monthly quota usage', () => {
  const result = normalizeVolcengine({ Result: { QuotaUsage: [
    { Level: 'session', Percent: 0, ResetTimestamp: -1 },
    { Level: 'weekly', Percent: 21.055637, ResetTimestamp: 1784476800 },
    { Level: 'monthly', Percent: 92.895395, ResetTimestamp: 1784217599 }
  ] } });
  assert.deepEqual(result.periods.map(period => period.name), ['session', 'weekly', 'monthly']);
  assert.equal(result.periods[1].usedPercent, 21.055637);
  assert.equal(result.periods[2].resetAt, 1784217599000);
});

test('normalizes Volcengine AgentPlan AFP quota usage', () => {
  const result = normalizeVolcengine({ Result: {
    AFPFiveHour: { Quota: 2000, Used: 561.7224, ResetTime: 1784038641000 },
    AFPWeekly: { Quota: 7000, Used: 1674.8421, ResetTime: 1784476800000 },
    AFPMonthly: { Quota: 20000, Used: 11620.4873, ResetTime: 1784217599000 }
  } });
  assert.deepEqual(result.periods.map(period => period.name), ['5h', 'weekly', 'monthly']);
  assert.ok(Math.abs(result.periods[0].usedPercent - 28.08612) < 0.000001);
  assert.ok(Math.abs(result.periods[1].usedPercent - 23.926315714285714) < 0.000001);
  assert.ok(Math.abs(result.periods[2].usedPercent - 58.1024365) < 0.000001);
  assert.equal(result.periods[2].quota, 20000);
  assert.equal(result.periods[2].used, 11620.4873);
  assert.equal(result.periods[1].resetAt, 1784476800000);
});

test('normalizes Kimi Code subscription usage periods', () => {
  const result = normalizeKimi({
    ratelimitCode5h: { ratio: 0.0002, enabled: true, resetTime: '2026-07-17T09:44:50.542928506Z' },
    ratelimitCode7d: { ratio: 0.0001, enabled: true, resetTime: '2026-07-24T04:44:49.542928506Z' },
    subscriptionBalance: { amountUsedRatio: 0.0933, kimiCodeUsedRatio: 0.0795, expireTime: '2026-08-17T04:44:51Z' }
  });
  assert.deepEqual(result.periods.map(period => period.name), ['5h', '7d', '订阅']);
  assert.ok(Math.abs(result.periods[0].usedPercent - 0.02) < 0.000001);
  assert.equal(result.periods[0].resetAt, '2026-07-17T09:44:50.542928506Z');
  assert.ok(Math.abs(result.periods[1].usedPercent - 0.01) < 0.000001);
  assert.ok(Math.abs(result.periods[2].usedPercent - 9.33) < 0.000001);
  assert.equal(result.periods[2].resetAt, '2026-08-17T04:44:51Z');
});

test('normalizes LongCat token pack usage periods', () => {
  const result = normalizeLongCat({
    code: 0,
    msg: 'success',
    data: {
      currentLot: {
        source: 'FREE_PACK',
        remainingToken: 3585186,
        consumedToken: 6414814,
        totalToken: 10000000,
        consumedRatio: 0.6414814,
        remainSeconds: 1620531,
        expireTime: '2026-08-05 07:54:57',
        status: 'ACTIVE'
      },
      otherLots: [
        {
          source: 'PACK_99',
          remainingToken: 50000000,
          consumedToken: 0,
          totalToken: 50000000,
          consumedRatio: 0.0,
          remainSeconds: 1620555,
          expireTime: '2026-08-05 07:55:21',
          status: 'ACTIVE'
        }
      ]
    }
  });
  assert.deepEqual(result.periods.map(period => period.name), ['免费额度', '付费额度']);
  assert.ok(Math.abs(result.periods[0].usedPercent - 64.14814) < 0.000001);
  assert.equal(result.periods[0].remainingPercent, 35.85186);
  assert.equal(result.periods[0].expireTime, '2026-08-05 07:54:57');
  assert.equal(result.periods[1].usedPercent, 0);
  assert.equal(result.periods[1].expireTime, '2026-08-05 07:55:21');
  assert.equal(result.used, 64.14814);
  assert.equal(result.limit, 100);
  assert.equal(result.unit, '%');
});

test('normalizes Qianwen AI TokenPlan usage periods', () => {
  const result = normalizeQianwen({
    code: '200',
    data: {
      DataV2: {
        ret: ['SUCCESS::接口调用成功'],
        data: {
          msg: 'Success.',
          code: 'SUCCESS',
          data: {
            per5HourPercentage: 0.000046514285714285715,
            per1WeekResetTime: 1785069600000,
            per5HourResetTime: 1784482800000,
            per1WeekPercentage: 0.000013024
          },
          requestId: '9a173805',
          success: true
        }
      },
      success: true,
      httpStatus: 200
    },
    httpStatusCode: '200',
    successResponse: true
  });
  assert.deepEqual(result.periods.map(period => period.name), ['5h', '1w']);
  assert.ok(Math.abs(result.periods[0].usedPercent - 0.0046514285714285715) < 0.000001);
  assert.equal(result.periods[0].resetAt, 1784482800000);
  assert.ok(Math.abs(result.periods[1].usedPercent - 0.0013024) < 0.000001);
  assert.equal(result.periods[1].resetAt, 1785069600000);
  assert.equal(result.used, 0.0046514285714285715);
  assert.equal(result.limit, 100);
  assert.equal(result.unit, '%');
});

test('normalizes Zhipu CodingPlan token and time limits', () => {
  const result = normalizeZhipu({
    data: {
      limits: [
        { type: 'TIME_LIMIT', percentage: '8.2%' },
        { type: 'TOKENS_LIMIT', unit: 6, number: 1, percentage: 45, nextResetTime: 1787607163997 },
        { type: 'TOKENS_LIMIT', unit: 3, number: 5, percentage: 12.5, nextResetTime: 1787176502893 },
        { type: 'UNKNOWN_LIMIT', percentage: 99 }
      ]
    }
  });
  assert.deepEqual(result.periods.map(period => period.name), ['5h', 'weekly', 'time']);
  assert.equal(result.periods[0].usedPercent, 12.5);
  assert.equal(result.periods[0].remainingPercent, 87.5);
  assert.equal(result.periods[0].resetAt, 1787176502893);
  assert.equal(result.periods[1].usedPercent, 45);
  assert.equal(result.periods[1].resetAt, 1787607163997);
  assert.equal(result.periods[2].usedPercent, 8.2);
  assert.equal(result.used, 45);
  assert.equal(result.remaining, 55);
  assert.equal(result.limit, 100);
  assert.equal(result.unit, '%');
});

test('orders Zhipu token windows by reset time when window metadata is absent', () => {
  const result = normalizeZhipu({
    data: {
      limits: [
        { type: 'TOKENS_LIMIT', percentage: 41, nextResetTime: 1787607163997 },
        { type: 'TOKENS_LIMIT', percentage: 9, nextResetTime: 1787176502893 }
      ]
    }
  });
  assert.deepEqual(result.periods.map(period => period.name), ['5h', 'weekly']);
  assert.equal(result.periods[0].usedPercent, 9);
  assert.equal(result.periods[1].usedPercent, 41);
});

test('normalizes an empty Zhipu CodingPlan response', () => {
  const result = normalizeZhipu({ data: { limits: [] } });
  assert.deepEqual(result.periods, []);
  assert.equal(result.used, 0);
  assert.equal(result.remaining, 100);
});

test('normalizes Google AI Gemini Models five-hour and weekly quota usage', () => {
  const { normalizeGoogleAi } = require('../parser.js');
  const result = normalizeGoogleAi({
    groups: [{
      displayName: 'Gemini Models',
      buckets: [
        { bucketId: 'gemini-weekly', window: 'weekly', remainingFraction: 0.99498266 },
        { bucketId: 'gemini-5h', window: '5h', remainingFraction: 1 }
      ]
    }]
  });
  assert.equal(result.periods.length, 2);
  assert.deepEqual(result.periods.map(period => period.name), ['5h', 'weekly']);
  assert.equal(result.periods[0].usedPercent, 0);
  assert.ok(Math.abs(result.periods[1].usedPercent - 0.501734) < 0.000001);
  assert.ok(Math.abs(result.used - 0.501734) < 0.000001);
  assert.equal(result.limit, 100);
  assert.equal(result.unit, '%');
});

test('normalizes Google AI without Gemini Models group as empty periods', () => {
  const { normalizeGoogleAi } = require('../parser.js');
  const result = normalizeGoogleAi({ groups: [{ displayName: 'Claude and GPT models', buckets: [] }] });
  assert.equal(result.periods.length, 0);
  assert.equal(result.used, 0);
});
