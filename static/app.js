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

  const remain = ((vi / price) - 1) * 100;
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

  const m = String(raw).match(/(\d{4})[./-](\d{1,2})[./-](\d{1,2})/);
  if (m) {
    const yy = m[1];
    const mm = String(m[2]).padStart(2, '0');
    const dd = String(m[3]).padStart(2, '0');
    return `${yy}-${mm}-${dd}`;
  }

  return todayKey();
}

async function saveBudget() {
  const input = document.getElementById('budget');

  const amount =
    parseInt(
      String(input?.value || '').replace(/\D/g, ''),
      10
    ) || 0;

  if (amount <= 0) {
    alert('운용금액을 입력해주세요.');
    return;
  }

  const maxCash =
    Number(STATE?.paper?.initial_cash || 1000000);

  if (amount > maxCash) {
    alert(
      '운용금액은 가상 총자금 ' +
      won(maxCash) +
      '을 초과할 수 없습니다.'
    );
    return;
  }

  const btn = document.getElementById('saveBudgetBtn');

  if (btn) {
    btn.disabled = true;
    btn.textContent = '저장 중';
  }

  try {
    const r = await fetch('/api/budget', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ amount })
    });

    if (!r.ok) {
      throw new Error(`budget HTTP ${r.status}`);
    }

    const data = await r.json();

    document.getElementById('currentBudget').textContent =
      '현재 운용값: ' + won(data.budget);

    if (STATE?.paper) {
      STATE.paper.budget = data.budget;
    }

    document.getElementById('heldCost').textContent =
      '보유원가 ' +
      won(STATE?.paper?.held_cost || 0) +
      ' / 한도 ' +
      won(data.budget);

    alert(
      '오늘 운용금액이 ' +
      won(data.budget) +
      '으로 설정되었습니다.'
    );

  } catch (e) {
    console.error(e);
    alert('운용금액 저장에 실패했습니다.');

  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '저장';
    }
  }
}

function scrollToSection(id) {
  const target = document.getElementById(id);
  if (!target) return;

  target.scrollIntoView({
    behavior: 'smooth',
    block: 'start'
  });
}

function candidateRow(x, smart = false, rank = 0) {
  const payload = encodeURIComponent(JSON.stringify(x));

  return `
    <div class="row" data-detail="${payload}">
      <div class="stock-top">
        <div class="stock-left">
          <div class="name">${x.name || x.code}</div>
          <div class="code">${x.code}</div>
          <span class="pill">
            ${(x.reasons || []).slice(0, 2).join(' · ') || '분석중'}
          </span>
        </div>

        <div class="stock-rank">
          ${rank > 0 ? `${rank}위` : ''}
        </div>
      </div>

      <div class="metric-grid">
        <div class="metric">
          <span class="metric-title">현재가</span>
          <span class="metric-value">${won(x.price)}</span>
        </div>

        <div class="metric">
          <span class="metric-title">
            ${smart ? 'PER / PBR' : 'AI 점수'}
          </span>
          <span class="metric-value ${smart ? '' : 'score'}">
            ${
              smart
                ? `${Number(x.per || 0).toFixed(1)} / ${Number(x.pbr || 0).toFixed(2)}`
                : x.score
            }
          </span>
        </div>

        <div class="metric">
          <span class="metric-title">
            ${smart ? '외국인 / 기관' : '목표가(VI)'}
          </span>
          <span class="metric-value">
            ${
              smart
                ? `${Math.round(x.foreign_net || 0)} / ${Math.round(x.institution_net || 0)}`
                : won(x.vi_pre)
            }
          </span>
        </div>

        <div class="metric">
          <span class="metric-title">
            ${smart ? '체결강도' : 'VI까지'}
          </span>
          <span class="metric-value">
            ${smart ? Math.round(x.execution_strength || 0) : viRemain(x)}
          </span>
          ${
            smart
              ? ''
              : `<div class="mini-note">현재가 옆 목표가 표시</div>`
          }
        </div>
      </div>
    </div>
  `;
}

function positionRow(x) {
  return `
    <div class="row">
      <div class="stock-top">
        <div class="stock-left">
          <div class="name">● ${x.name}</div>
          <div class="code">${x.code} · ${x.qty}주</div>
        </div>
      </div>

      <div class="metric-grid">
        <div class="metric">
          <span class="metric-title">평단</span>
          <span class="metric-value">${won(x.avg_price)}</span>
        </div>

        <div class="metric">
          <span class="metric-title">현재가</span>
          <span class="metric-value">${won(x.current_price)}</span>
        </div>

        <div class="metric">
          <span class="metric-title">손익률</span>
          <span class="metric-value ${x.pnl >= 0 ? 'pos' : 'neg'}">
            ${pct(x.pnl_pct)}
          </span>
        </div>

        <div class="metric">
          <span class="metric-title">손익금액</span>
          <span class="metric-value ${x.pnl >= 0 ? 'pos' : 'neg'}">
            ${won(x.pnl)}
          </span>
        </div>
      </div>
    </div>
  `;
}

function tradeRow(t) {
  return `
    <div class="row">
      <div class="stock-top">
        <div class="stock-left">
          <div class="name">
            ${t.side === 'BUY' ? '매수' : '매도'} · ${t.name}
          </div>
          <div class="code">
            ${t.time} · ${t.qty}주 · ${t.code || ''}
          </div>
        </div>
      </div>

      <div class="metric-grid">
        <div class="metric">
          <span class="metric-title">체결가</span>
          <span class="metric-value">${won(t.price)}</span>
        </div>

        <div class="metric">
          <span class="metric-title">실현손익</span>
          <span class="metric-value ${Number(t.pnl || 0) >= 0 ? 'pos' : 'neg'}">
            ${won(t.pnl)}
          </span>
        </div>

        <div class="metric">
          <span class="metric-title">수익률</span>
          <span class="metric-value ${Number(t.pnl || 0) >= 0 ? 'pos' : 'neg'}">
            ${pct(t.pnl_pct)}
          </span>
        </div>

        <div class="metric">
          <span class="metric-title">구분</span>
          <span class="metric-value">${t.side}</span>
        </div>
      </div>
    </div>
  `;
}

function detail(x) {
  const s = x.series || [];
  const min = Math.min(...s, 0);
  const max = Math.max(...s, 1);

  const bars = s
    .map(
      (v) =>
        `<div class="bar" style="height:${Math.max(
          2,
          ((v - min) / (max - min || 1)) * 100
        )}%"></div>`
    )
    .join('');

  document.getElementById('detail').innerHTML = `
    <h2>${x.name} <small>${x.code}</small></h2>
    <h1>${won(x.price)}</h1>

    <div class="chart">${bars}</div>

    <p><b>PER</b> ${Number(x.per || 0).toFixed(2)} &nbsp; <b>PBR</b> ${Number(x.pbr || 0).toFixed(2)}</p>
    <p><b>목표가(VI)</b> ${won(x.vi_pre)}</p>
    <p><b>VI까지</b> ${viRemain(x)}</p>
    <p><b>AI 점수</b> ${x.score}</p>
    <p>${(x.reasons || []).join(' · ')}</p>
  `;

  document.getElementById('modal').classList.add('show');
}

function closeModal() {
  document.getElementById('modal').classList.remove('show');
}

function buildProfitMap(trades) {
  const map = {};

  (trades || []).forEach((t) => {
    const realized = Number(t.pnl || 0);

    if (realized === 0 && t.side !== 'SELL') {
      return;
    }

    const key = normalizeTradeDate(t.date || t.time);

    if (!map[key]) {
      map[key] = {
        total: 0,
        items: []
      };
    }

    map[key].total += realized;
    map[key].items.push({
      name: t.name,
      code: t.code || '',
      pnl: realized,
      pnl_pct: Number(t.pnl_pct || 0),
      time: t.time || '',
      side: t.side || ''
    });
  });

  return map;
}

function renderProfitDetail(dateKey) {
  selectedProfitDate = dateKey;

  const box = currentProfitMap[dateKey];

  if (!box) {
    document.getElementById('profitSummary').innerHTML =
      `${dateKey} 실현손익: 0원`;

    document.getElementById('profitDetailList').innerHTML =
      `<div class="empty">선택한 날짜의 수익 내역이 없습니다.</div>`;

    drawProfitCalendar();
    return;
  }

  document.getElementById('profitSummary').innerHTML =
    `${dateKey} 실현손익: <b class="${box.total >= 0 ? 'pos' : 'neg'}">${won(box.total)}</b>`;

  document.getElementById('profitDetailList').innerHTML =
    box.items.length
      ? box.items
          .map(
            (item) => `
              <div class="profit-row">
                <div class="profit-left">
                  <b>${item.name}</b>
                  <span>${item.code} · ${item.time} · ${item.side}</span>
                </div>

                <div class="profit-right">
                  <b class="${item.pnl >= 0 ? 'pos' : 'neg'}">${won(item.pnl)}</b>
                  <span>${pct(item.pnl_pct)}</span>
                </div>
              </div>
            `
          )
          .join('')
      : `<div class="empty">상세 수익 내역이 없습니다.</div>`;

  drawProfitCalendar();
}

function drawProfitCalendar() {
  const year = profitCursor.getFullYear();
  const month = profitCursor.getMonth();

  document.getElementById('profitMonthTitle').textContent =
    `${year}년 ${month + 1}월`;

  const first = new Date(year, month, 1);
  const last = new Date(year, month + 1, 0);

  const startWeekday = first.getDay();
  const daysInMonth = last.getDate();

  const prevLast = new Date(year, month, 0).getDate();

  const cells = [];

  for (let i = startWeekday - 1; i >= 0; i -= 1) {
    const dayNum = prevLast - i;
    const d = new Date(year, month - 1, dayNum);
    cells.push({
      key: toDateKey(d),
      day: dayNum,
      other: true
    });
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const d = new Date(year, month, day);
    cells.push({
      key: toDateKey(d),
      day,
      other: false
    });
  }

  while (cells.length % 7 !== 0) {
    const dayNum = cells.length - (startWeekday + daysInMonth) + 1;
    const d = new Date(year, month + 1, dayNum);
    cells.push({
      key: toDateKey(d),
      day: dayNum,
      other: true
    });
  }

  document.getElementById('profitCalendar').innerHTML =
    cells
      .map((cell) => {
        const data = currentProfitMap[cell.key];
        const total = Number(data?.total || 0);

        return `
          <button
            class="day-cell ${cell.other ? 'is-other' : ''} ${selectedProfitDate === cell.key ? 'is-active' : ''}"
            type="button"
            data-date="${cell.key}"
          >
            <div class="day-head">${cell.day}</div>
            <div class="day-profit ${total >= 0 ? 'pos' : 'neg'}">
              ${data ? won(total) : ''}
            </div>
          </button>
        `;
      })
      .join('');
}

function render(s) {
  STATE = s;
  const p = s.paper;

  document.getElementById('equity').textContent = won(p.equity);

  const budgetInput = document.getElementById('budget');

  if (!budgetInitialized) {
    budgetInput.value = p.budget;
    budgetInitialized = true;
  }

  document.getElementById('currentBudget').textContent =
    '현재 운용값: ' + won(p.budget);

  document.getElementById('heldCost').textContent =
    '보유원가 ' + won(p.held_cost) + ' / 한도 ' + won(p.budget);

  document.getElementById('cash').textContent =
    '가상현금 ' + won(p.cash);

  const h = s.health;

  document.getElementById('health').textContent =
    h.nh_realtime
      ? '● NH KRX 실시간 연결'
      : '○ 연결대기 · ' +
        (
          h.nh_configured
            ? '시세 수신 대기'
            : 'NH API 키 미설정'
        );

  document.getElementById('markets').innerHTML =
    s.market
      .map(
        (m) => `
          <div class="market">
            <b>${m.label}</b>
            <strong>${m.value == null ? '—' : m.value}</strong>
            <div class="delta">${m.change || ''}</div>
            <div class="pending">${m.status || ''}</div>
          </div>
        `
      )
      .join('');

  document.getElementById('sectors').innerHTML =
    s.sectors.length
      ? s.sectors
          .map(
            (x, i) =>
              `<div class="sector">${i + 1}위 · ${x.sector} ${pct(x.change_pct)}</div>`
          )
          .join('')
      : `<div class="empty">KRX 데이터가 쌓이면 주도 섹터가 표시됩니다.</div>`;

  document.getElementById('positions').innerHTML =
    p.positions.length
      ? p.positions.map(positionRow).join('')
      : `<div class="empty">AI PAPER 보유종목이 없습니다.</div>`;

  document.getElementById('scalpList').innerHTML =
    s.scalp.length
      ? s.scalp.map((x, i) => candidateRow(x, false, i + 1)).join('')
      : `<div class="empty">실시간 후보를 수집 중입니다.</div>`;

  document.getElementById('smartList').innerHTML =
    s.smart.length
      ? s.smart.map((x, i) => candidateRow(x, true, i + 1)).join('')
      : `<div class="empty">스마트머니 후보를 수집 중입니다.</div>`;

  document.getElementById('tradeList').innerHTML =
    p.trades.length
      ? p.trades.map(tradeRow).join('')
      : `<div class="empty">오늘 PAPER 거래가 없습니다.</div>`;

  currentProfitMap = buildProfitMap(p.trades || []);
  drawProfitCalendar();

  if (selectedProfitDate) {
    renderProfitDetail(selectedProfitDate);
  } else {
    const keys = Object.keys(currentProfitMap).sort().reverse();
    if (keys.length) {
      renderProfitDetail(keys[0]);
    } else {
      document.getElementById('profitSummary').innerHTML =
        '날짜를 누르면 그날의 수익 내역이 표시됩니다.';
      document.getElementById('profitDetailList').innerHTML =
        `<div class="empty">아직 실현손익 데이터가 없습니다.</div>`;
    }
  }
}

async function refresh() {
  if (refreshing) {
    return;
  }

  refreshing = true;

  try {
    const r = await fetch('/api/state', {
      cache: 'no-store'
    });

    if (!r.ok) {
      throw new Error(`state HTTP ${r.status}`);
    }

    const data = await r.json();
    render(data);

  } catch (e) {
    const health = document.getElementById('health');

    if (health) {
      health.textContent = '○ 서버 연결 끊김';
    }

    console.error(e);

  } finally {
    refreshing = false;
  }
}

function bindUi() {
  document
    .getElementById('saveBudgetBtn')
    ?.addEventListener('click', saveBudget);

  document
    .querySelectorAll('[data-scroll]')
    .forEach((button) => {
      button.addEventListener('click', () => {
        scrollToSection(button.dataset.scroll);
      });
    });

  document
    .getElementById('modal')
    ?.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) {
        closeModal();
      }
    });

  document
    .getElementById('closeModalBtn')
    ?.addEventListener('click', closeModal);

  document.addEventListener('click', (event) => {
    const detailEl = event.target.closest('[data-detail]');
    if (detailEl) {
      try {
        detail(
          JSON.parse(
            decodeURIComponent(detailEl.dataset.detail)
          )
        );
      } catch (e) {
        console.error(e);
      }
      return;
    }

    const dayEl = event.target.closest('[data-date]');
    if (dayEl) {
      renderProfitDetail(dayEl.dataset.date);
    }
  });

  document
    .getElementById('prevMonthBtn')
    ?.addEventListener('click', () => {
      profitCursor = new Date(
        profitCursor.getFullYear(),
        profitCursor.getMonth() - 1,
        1
      );
      drawProfitCalendar();
    });

  document
    .getElementById('nextMonthBtn')
    ?.addEventListener('click', () => {
      profitCursor = new Date(
        profitCursor.getFullYear(),
        profitCursor.getMonth() + 1,
        1
      );
      drawProfitCalendar();
    });
}

document.addEventListener('DOMContentLoaded', () => {
  bindUi();
  refresh();
  setInterval(refresh, 5000);
});
