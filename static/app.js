let STATE = null;
let refreshing = false;
let budgetInitialized = false;

const won = (n) =>
  Number(n || 0).toLocaleString('ko-KR') + '원';

const pct = (n) =>
  (Number(n || 0) >= 0 ? '+' : '') +
  Number(n || 0).toFixed(2) +
  '%';


function tab(id, button) {
  document.querySelectorAll('.tab').forEach((x) => {
    x.classList.remove('active');
  });

  document.querySelectorAll('nav button').forEach((x) => {
    x.classList.remove('active');
  });

  const target = document.getElementById(id);

  if (target) {
    target.classList.add('active');
  }

  if (button) {
    button.classList.add('active');
  }
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


function row(x, smart = false) {
  const payload = encodeURIComponent(JSON.stringify(x));

  return `
    <div class="row" data-detail="${payload}">
      <div>
        <div class="name">${x.name || x.code}</div>
        <div class="code">${x.code}</div>
        <span class="pill">
          ${(x.reasons || []).slice(0, 2).join(' · ') || '분석중'}
        </span>
      </div>

      <div>
        <div class="sub">현재가</div>
        <b>${won(x.price)}</b>
      </div>

      <div>
        <div class="sub">
          ${smart ? 'PER/PBR' : '점수'}
        </div>

        <b class="score">
          ${
            smart
              ? `${Number(x.per || 0).toFixed(1)} / ${Number(x.pbr || 0).toFixed(2)}`
              : x.score
          }
        </b>
      </div>

      <div class="hide-sm">
        <div class="sub">
          ${smart ? '외국인/기관' : 'VI 직전'}
        </div>

        <b>
          ${
            smart
              ? `${Math.round(x.foreign_net || 0)} / ${Math.round(x.institution_net || 0)}`
              : won(x.vi_pre)
          }
        </b>
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
    <h2>
      ${x.name}
      <small>${x.code}</small>
    </h2>

    <h1>${won(x.price)}</h1>

    <div class="chart">
      ${bars}
    </div>

    <p>
      <b>PER</b> ${Number(x.per || 0).toFixed(2)}
      <b>PBR</b> ${Number(x.pbr || 0).toFixed(2)}
    </p>

    <p>
      <b>상승 VI 직전 참고가</b>
      ${won(x.vi_pre)}
    </p>

    <p>
      <b>AI 점수</b>
      ${x.score}
    </p>

    <p>
      ${(x.reasons || []).join(' · ')}
    </p>
  `;

  document.getElementById('modal').classList.add('show');
}


function closeModal() {
  document.getElementById('modal').classList.remove('show');
}


function render(s) {
  STATE = s;
  const p = s.paper;

  document.getElementById('equity').textContent =
    won(p.equity);

  const budgetInput =
    document.getElementById('budget');

  if (!budgetInitialized) {
    budgetInput.value = p.budget;
    budgetInitialized = true;
  }

  document.getElementById('currentBudget').textContent =
    '현재 운용값: ' + won(p.budget);

  document.getElementById('heldCost').textContent =
    '보유원가 ' +
    won(p.held_cost) +
    ' / 한도 ' +
    won(p.budget);

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
            <strong>
              ${m.value == null ? '—' : m.value}
            </strong>
            <div class="pending">
              ${m.status || ''}
            </div>
          </div>
        `
      )
      .join('');

  document.getElementById('sectors').innerHTML =
    s.sectors.length
      ? s.sectors
          .map(
            (x, i) =>
              `<div class="sector">
                ${i + 1}. ${x.sector} ${pct(x.change_pct)}
              </div>`
          )
          .join('')
      : `<div class="empty">
          KRX 데이터가 쌓이면 주도섹터가 표시됩니다.
        </div>`;

  document.getElementById('positions').innerHTML =
    p.positions.length
      ? p.positions
          .map(
            (x) => `
              <div class="row">
                <div>
                  <div class="name">● ${x.name}</div>
                  <div class="code">${x.code} · ${x.qty}주</div>
                </div>

                <div>
                  <div class="sub">평단</div>
                  <b>${won(x.avg_price)}</b>
                </div>

                <div>
                  <div class="sub">현재가</div>
                  <b>${won(x.current_price)}</b>
                </div>

                <div>
                  <div class="sub">손익</div>
                  <b class="${x.pnl >= 0 ? 'pos' : 'neg'}">
                    ${pct(x.pnl_pct)}<br>
                    ${won(x.pnl)}
                  </b>
                </div>
              </div>
            `
          )
          .join('')
      : `<div class="empty">
          AI PAPER 보유종목이 없습니다.
        </div>`;

  document.getElementById('scalpList').innerHTML =
    s.scalp.length
      ? s.scalp.map((x) => row(x, false)).join('')
      : `<div class="empty">
          실시간 후보를 수집 중입니다.
        </div>`;

  document.getElementById('smartList').innerHTML =
    s.smart.length
      ? s.smart.map((x) => row(x, true)).join('')
      : `<div class="empty">
          스마트머니 후보를 수집 중입니다.
        </div>`;

  document.getElementById('tradeList').innerHTML =
    p.trades.length
      ? p.trades
          .map(
            (t) => `
              <div class="row">
                <div>
                  <div class="name">
                    ${t.side === 'BUY' ? '매수' : '매도'} · ${t.name}
                  </div>
                  <div class="code">
                    ${t.time} · ${t.qty}주
                  </div>
                </div>

                <div>
                  <div class="sub">체결가</div>
                  <b>${won(t.price)}</b>
                </div>

                <div>
                  <div class="sub">실현손익</div>
                  <b class="${t.pnl >= 0 ? 'pos' : 'neg'}">
                    ${won(t.pnl)}
                  </b>
                </div>

                <div class="hide-sm">
                  <div class="sub">수익률</div>
                  <b>${pct(t.pnl_pct)}</b>
                </div>
              </div>
            `
          )
          .join('')
      : `<div class="empty">
          오늘 PAPER 거래가 없습니다.
        </div>`;
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
    .querySelectorAll('nav button[data-tab]')
    .forEach((button) => {
      button.addEventListener('click', () => {
        tab(button.dataset.tab, button);
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
    const el = event.target.closest('[data-detail]');

    if (!el) {
      return;
    }

    try {
      detail(
        JSON.parse(
          decodeURIComponent(el.dataset.detail)
        )
      );
    } catch (e) {
      console.error(e);
    }
  });
}


document.addEventListener('DOMContentLoaded', () => {
  bindUi();
  refresh();

  setInterval(
    refresh,
    5000
  );
});
