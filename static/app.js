let STATE = null;
let refreshing = false;
let budgetInitialized = false;

let profitCursor = new Date();
let currentProfitMap = {};
let selectedProfitDate = null;


const won = (n) =>
  Number(n || 0).toLocaleString('ko-KR') + '원';


const pct = (n) =>
  (Number(n || 0) >= 0 ? '+' : '') +
  Number(n || 0).toFixed(2) +
  '%';


function toDateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');

  return `${y}-${m}-${d}`;
}


function todayKey() {
  return toDateKey(new Date());
}


function viRemain(x) {
  const price = Number(x.price || 0);
  const vi = Number(x.vi_pre || 0);

  if (price <= 0 || vi <= 0) {
    return '—';
  }

  const remain =
    ((vi / price) - 1) * 100;

  return pct(remain);
}


function normalizeTradeDate(raw) {
  if (!raw) {
    return todayKey();
  }

  const direct = new Date(raw);

  if (!Number.isNaN(direct.getTime())) {
    return toDateKey(direct);
  }

  const m = String(raw).match(
    /(\d{4})[./-](\d{1,2})[./-](\d{1,2})/
  );

  if (m) {
    const yy = m[1];
    const mm = String(m[2]).padStart(2, '0');
    const dd = String(m[3]).padStart(2, '0');

    return `${yy}-${mm}-${dd}`;
  }

  return todayKey();
}


async function saveBudget() {
  const input =
    document.getElementById('budget');

  const amount =
    parseInt(
      String(
        input?.value || ''
      ).
