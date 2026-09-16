function firstNumber(value, keys) {
  for (const key of keys) {
    const candidate = value?.[key];
    if (typeof candidate === 'number' && Number.isFinite(candidate)) return candidate;
    if (typeof candidate === 'string' && candidate.trim() !== '' && Number.isFinite(Number(candidate))) {
      return Number(candidate);
    }
  }
  return null;
}

function firstValue(value, keys) {
  for (const key of keys) {
    if (value && value[key] !== undefined && value[key] !== null) return value[key];
  }
  return null;
}

function percent(value) {
  if (typeof value === 'string') value = value.replace('%', '');
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function normalizeWindows(value) {
  return Array.isArray(value.model_remains) ? value.model_remains.map(item => ({
    modelName: item.model_name || 'Plan',
    interval: {
      usedPercent: percent(item.current_interval_used_percent),
      totalPercent: percent(item.current_interval_total_percent) || 100,
      remainingPercent: Math.max(0, 100 - percent(item.current_interval_used_percent)),
      startAt: item.start_time || null,
      resetAt: item.end_time || null
    },
    weekly: {
      usedPercent: percent(item.current_weekly_used_percent),
      totalPercent: percent(item.current_weekly_total_percent) || 100,
      remainingPercent: Math.max(0, 100 - percent(item.current_weekly_used_percent)),
      startAt: item.weekly_start_time || null,
      resetAt: item.weekly_end_time || null
    }
  })) : [];
}

function unwrap(value) {
  if (!value || typeof value !== 'object') return {};
  return value.data && typeof value.data === 'object' ? value.data : value;
}

function normalizeCodex(payload) {
  const value = unwrap(payload);
  return {
    remaining: firstNumber(value, ['remaining', 'remaining_credits', 'reset_credits', 'credits_remaining']) ?? 0,
    resetAt: firstValue(value, ['reset_at', 'resetAt', 'reset_time', 'resetTime']),
    windows: normalizeWindows(value)
  };
}

function normalizeCodexCredits(payload) {
  const value = unwrap(payload);
  const credits = Array.isArray(value.credits) ? value.credits : [];
  const availableCount = firstNumber(value, ['available_count', 'availableCount']) ?? credits.filter(item => item?.status === 'available').length;
  const availableExpirations = credits
    .filter(item => item?.status === 'available' && item.expires_at)
    .map(item => item.expires_at)
    .sort((left, right) => Date.parse(left) - Date.parse(right));
  return { availableCount, credits, nextExpiresAt: availableExpirations[0] || null, updatedAt: Date.now() };
}

function normalizeCodexUsage(payload) {
  const unwrapped = unwrap(payload);
  const value = unwrapped.usage && typeof unwrapped.usage === 'object' ? { ...unwrapped, ...unwrapped.usage } : unwrapped;
  const rateLimit = value.rate_limit && typeof value.rate_limit === 'object' ? value.rate_limit : {};
  const toWindow = (window, fallbackName) => {
    if (!window || typeof window !== 'object') return { name: fallbackName, available: false, usedPercent: 0, remainingPercent: 100, resetAt: null, resetAfterSeconds: null };
    const seconds = firstNumber(window, ['limit_window_seconds']) ?? 0;
    const name = seconds === 18000 ? '5h' : seconds >= 604800 ? 'weekly' : fallbackName;
    const usedPercent = Math.max(0, Math.min(100, percent(window.used_percent)));
    const resetAt = firstNumber(window, ['reset_at']);
    return { name, available: true, usedPercent, remainingPercent: Math.max(0, 100 - usedPercent), resetAt: resetAt ? resetAt * 1000 : null, resetAfterSeconds: firstNumber(window, ['reset_after_seconds']) };
  };
  const resetCards = firstNumber(value.rate_limit_reset_credits, ['available_count']) ?? null;
  return {
    windows: [toWindow(rateLimit.primary_window, 'weekly'), toWindow(rateLimit.secondary_window, '5h')],
    resetCards,
    planType: value.plan_type || null,
    updatedAt: Date.now()
  };
}

function normalizeCodexNewApi(payload) {
  const value = unwrap(payload);
  const usage = normalizeCodexUsage(value.usage && typeof value.usage === 'object' ? value.usage : value);
  const result = { usage, updatedAt: Date.now() };
  if (Array.isArray(value.credits) && value.credits.length) {
    result.credits = normalizeCodexCredits(value);
  }
  return result;
}

function normalizeMiniMax(payload) {
  const value = unwrap(payload);
  const remaining = firstNumber(value, ['remains_percent', 'remaining_percent', 'remain_percent', 'remainingPercent']);
  const windows = normalizeWindows(value);
  const windowRemaining = windows[0]?.interval?.remainingPercent;
  const normalizedRemaining = windowRemaining === undefined
    ? (remaining === null ? 0 : Math.max(0, Math.min(100, remaining)))
    : windowRemaining;
  return { limit: 100, used: 100 - normalizedRemaining, remaining: normalizedRemaining, unit: '%', windows };
}

function normalizeKimi(payload) {
  const value = unwrap(payload);
  const ratioToPercent = ratio => Number.isFinite(Number(ratio)) ? Math.max(0, Math.min(100, Number(ratio) * 100)) : 0;
  const periods = [];
  if (value.ratelimitCode5h && typeof value.ratelimitCode5h === 'object') {
    periods.push({ name: '5h', usedPercent: ratioToPercent(value.ratelimitCode5h.ratio), remainingPercent: Math.max(0, 100 - ratioToPercent(value.ratelimitCode5h.ratio)), resetAt: value.ratelimitCode5h.resetTime || null });
  }
  if (value.ratelimitCode7d && typeof value.ratelimitCode7d === 'object') {
    periods.push({ name: '7d', usedPercent: ratioToPercent(value.ratelimitCode7d.ratio), remainingPercent: Math.max(0, 100 - ratioToPercent(value.ratelimitCode7d.ratio)), resetAt: value.ratelimitCode7d.resetTime || null });
  }
  if (value.subscriptionBalance && typeof value.subscriptionBalance === 'object') {
    const used = ratioToPercent(value.subscriptionBalance.amountUsedRatio ?? value.subscriptionBalance.kimiCodeUsedRatio);
    periods.push({ name: '订阅', usedPercent: used, remainingPercent: Math.max(0, 100 - used), resetAt: value.subscriptionBalance.expireTime || null });
  }
  const used = periods.length ? Math.max(...periods.map(period => period.usedPercent)) : 0;
  return { limit: 100, used, remaining: Math.max(0, 100 - used), unit: '%', periods, updatedAt: Date.now() };
}

function normalizeQianwen(payload) {
  const ratioToPercent = ratio => Number.isFinite(Number(ratio)) ? Math.max(0, Math.min(100, Number(ratio) * 100)) : 0;
  const root = unwrap(payload);
  let value = root;
  for (const key of ['DataV2', 'data', 'data', 'data']) {
    if (value && typeof value[key] === 'object') value = value[key];
  }
  const periods = [];
  if (value.per5HourPercentage !== undefined) {
    periods.push({ name: '5h', usedPercent: ratioToPercent(value.per5HourPercentage), remainingPercent: Math.max(0, 100 - ratioToPercent(value.per5HourPercentage)), resetAt: firstNumber(value, ['per5HourResetTime']) });
  }
  if (value.per1WeekPercentage !== undefined) {
    periods.push({ name: '1w', usedPercent: ratioToPercent(value.per1WeekPercentage), remainingPercent: Math.max(0, 100 - ratioToPercent(value.per1WeekPercentage)), resetAt: firstNumber(value, ['per1WeekResetTime']) });
  }
  const used = periods.length ? Math.max(...periods.map(period => period.usedPercent)) : 0;
  return { limit: 100, used, remaining: Math.max(0, 100 - used), unit: '%', periods, updatedAt: Date.now() };
}

function normalizeZhipu(payload) {
  const value = unwrap(payload);
  const limits = Array.isArray(value.limits) ? value.limits : [];
  const parsePercentage = item => {
      const rawPercentage = typeof item.percentage === 'string' ? item.percentage.replace('%', '') : item.percentage;
      const percentage = Number(rawPercentage);
      return Number.isFinite(percentage) ? Math.max(0, Math.min(100, percentage)) : null;
  };
  const resetAt = item => firstValue(item, ['nextResetTime', 'next_reset_time', 'resetTime', 'reset_time']);
  const tokenLimits = limits
    .map((item, index) => item && typeof item === 'object' && ['TOKENS_LIMIT', 'CREDIT_LIMIT'].includes(item.type)
      ? { item, index, usedPercent: parsePercentage(item), resetAt: resetAt(item) }
      : null)
    .filter(entry => entry && entry.usedPercent !== null)
    .sort((left, right) => {
      const windowRank = item => {
        const unit = Number(item.item.unit);
        const number = Number(item.item.number);
        if (unit === 3 && number === 5) return 0;
        if (unit === 6 && (number === 1 || number === 7)) return 1;
        return 2;
      };
      const rankDifference = windowRank(left) - windowRank(right);
      if (rankDifference) return rankDifference;
      const leftReset = Number(left.resetAt);
      const rightReset = Number(right.resetAt);
      if (Number.isFinite(leftReset) && Number.isFinite(rightReset) && leftReset !== rightReset) return leftReset - rightReset;
      return left.index - right.index;
    });
  const periods = tokenLimits.map((entry, index) => {
    const unit = Number(entry.item.unit);
    const number = Number(entry.item.number);
    const name = unit === 3 && number === 5 ? '5h' : unit === 6 && (number === 1 || number === 7) ? 'weekly' : index === 0 ? '5h' : 'weekly';
    return { name, usedPercent: entry.usedPercent, remainingPercent: Math.max(0, 100 - entry.usedPercent), resetAt: entry.resetAt ?? null };
  });
  const timeLimit = limits.find(item => item && typeof item === 'object' && item.type === 'TIME_LIMIT');
  const timeUsedPercent = timeLimit ? parsePercentage(timeLimit) : null;
  if (timeUsedPercent !== null) {
    periods.push({ name: 'time', usedPercent: timeUsedPercent, remainingPercent: Math.max(0, 100 - timeUsedPercent), resetAt: resetAt(timeLimit) ?? null });
  }
  const order = { '5h': 0, weekly: 1, time: 2 };
  periods.sort((left, right) => order[left.name] - order[right.name]);
  const used = periods.length ? Math.max(...periods.map(period => period.usedPercent)) : 0;
  return { limit: 100, used, remaining: Math.max(0, 100 - used), unit: '%', periods, updatedAt: Date.now() };
}

function normalizeLongCat(payload) {
  const value = unwrap(payload);
  const periods = [];
  const addLot = (lot, fallbackName) => {
    if (!lot || typeof lot !== 'object') return;
    const ratio = firstNumber(lot, ['consumedRatio']) ?? 0;
    const usedPercent = Math.max(0, Math.min(100, ratio * 100));
    let name = fallbackName;
    if (lot.source === 'FREE_PACK') name = '免费额度';
    else if (typeof lot.source === 'string' && lot.source.startsWith('PACK_')) name = '付费额度';
    periods.push({
      name,
      usedPercent,
      remainingPercent: Math.max(0, 100 - usedPercent),
      expireTime: lot.expireTime || null
    });
  };
  addLot(value.currentLot, '当前额度');
  if (Array.isArray(value.otherLots)) value.otherLots.forEach(lot => addLot(lot, '其他额度'));
  const used = periods.length ? Math.max(...periods.map(period => period.usedPercent)) : 0;
  return { limit: 100, used, remaining: Math.max(0, 100 - used), unit: '%', periods, updatedAt: Date.now() };
}

function normalizeVolcengine(payload) {
  const value = payload?.Result && typeof payload.Result === 'object' ? payload.Result : unwrap(payload);
  const afpPeriods = [
    ['5h', value.AFPFiveHour],
    ['weekly', value.AFPWeekly],
    ['monthly', value.AFPMonthly]
  ].filter(([, item]) => item && typeof item === 'object').map(([name, item]) => {
    const quota = firstNumber(item, ['Quota']) ?? 0;
    const used = firstNumber(item, ['Used']) ?? 0;
    const usedPercent = quota ? used / quota * 100 : 0;
    const resetTime = firstNumber(item, ['ResetTime']);
    return { name, quota, used, usedPercent, remainingPercent: quota ? Math.max(0, 100 - usedPercent) : 100, resetAt: resetTime && resetTime > 0 ? resetTime : null };
  });
  const periods = afpPeriods.length ? afpPeriods : Array.isArray(value.QuotaUsage) ? value.QuotaUsage.map(item => ({
    name: String(item.Level || '').toLowerCase(),
    usedPercent: percent(item.Percent),
    remainingPercent: Math.max(0, 100 - percent(item.Percent)),
    resetAt: firstNumber(item, ['ResetTimestamp']) > 0 ? firstNumber(item, ['ResetTimestamp']) * 1000 : null
  })) : [];
  const details = Array.isArray(value.Details) ? value.Details.map(item => ({
    time: item.Time || null,
    objectName: item.ObjectName || '',
    usage: firstNumber(item, ['Usage']) ?? 0,
    unit: item.Unit || '',
    billingType: item.BillingType || ''
  })) : [];
  if (periods.length) {
    const usedPercent = Math.max(...periods.map(period => period.usedPercent));
    return { limit: 100, used: usedPercent, remaining: Math.max(0, 100 - usedPercent), unit: '%', periods, details };
  }
  const limit = firstNumber(value, ['total', 'total_count', 'quota', 'limit', 'plan_quota', 'totalQuota']);
  const used = firstNumber(value, ['used', 'used_count', 'usage', 'consumed', 'usedQuota']);
  const remaining = firstNumber(value, ['remaining', 'remain', 'remaining_count', 'left', 'leftQuota']);
  const resolvedLimit = limit ?? ((used ?? 0) + (remaining ?? 0));
  const resolvedUsed = used ?? Math.max(0, resolvedLimit - (remaining ?? 0));
  return {
    limit: resolvedLimit,
    used: resolvedUsed,
    remaining: Math.max(0, resolvedLimit - resolvedUsed),
    unit: '次',
    periods,
    details
  };
}

function normalizeGoogleAi(payload) {
  const value = unwrap(payload);
  const groups = Array.isArray(value.groups) ? value.groups : [];
  const group = groups.find(item => String(item?.displayName || '').toLowerCase() === 'gemini models')
    || groups.find(item => String(item?.displayName || '').toLowerCase().includes('gemini'));
  if (!group || !Array.isArray(group.buckets)) return { limit: 100, used: 0, remaining: 100, unit: '%', periods: [], updatedAt: Date.now() };
  const labels = { '5h': '5h', weekly: 'weekly' };
  const periods = group.buckets
    .filter(bucket => bucket && labels[bucket.window] && Number.isFinite(Number(bucket.remainingFraction)))
    .map(bucket => {
      const remaining = Math.max(0, Math.min(1, Number(bucket.remainingFraction)));
      const usedPercent = Math.max(0, Math.min(100, (1 - remaining) * 100));
      return { name: labels[bucket.window], usedPercent, remainingPercent: Math.max(0, 100 - usedPercent), resetAt: bucket.resetTime || bucket.reset_at || null };
    })
    .sort((left, right) => ({ '5h': 0, weekly: 1 }[left.name] ?? 9) - ({ '5h': 0, weekly: 1 }[right.name] ?? 9));
  const used = periods.length ? Math.max(...periods.map(period => period.usedPercent)) : 0;
  return { limit: 100, used, remaining: Math.max(0, 100 - used), unit: '%', periods, updatedAt: Date.now() };
}

module.exports = { normalizeCodex, normalizeCodexCredits, normalizeCodexNewApi, normalizeCodexUsage, normalizeMiniMax, normalizeKimi, normalizeQianwen, normalizeZhipu, normalizeLongCat, normalizeVolcengine, normalizeGoogleAi };
