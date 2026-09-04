let STATE = null;
let refreshing = false;

let budgetInitializedFor =
  null;

let profitCursor =
  new Date();

let currentProfitMap = {};

let selectedProfitDate =
  null;


const MODE_KEY =
  'gy_market_mode';


let MARKET_MODE =
  readMarketMode();


const $ = (id) =>
  document.getElementById(
    id
  );


function readMarketMode() {
  try {
    return (
      localStorage.getItem(
        MODE_KEY
      ) === 'US'
        ? 'US'
        : 'KR'
    );

  } catch (_) {
    return 'KR';
  }
}


function saveMarketMode(
  mode
) {
  try {
    localStorage.setItem(
      MODE_KEY,
      mode
    );

  } catch (_) {
  }
}


const won = (n) =>
  Number(
    n || 0
  ).toLocaleString(
    'ko-KR'
  ) + '원';


const usd = (n) =>
  '$' +
  Number(
    n || 0
  ).toLocaleString(
    'en-US',
    {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4
    }
  );


const pct = (n) =>
  (
    Number(
      n || 0
    ) >= 0
      ? '+'
      : ''
  )
  +
  Number(
    n || 0
  ).toFixed(
    2
  )
  +
  '%';


const plain = (n) =>
  Number(
    n || 0
  ).toLocaleString(
    'en-US',
    {
      maximumFractionDigits: 4
    }
  );


function priceText(
  value,
  market = MARKET_MODE
) {
  return (
    market === 'US'
      ? usd(
          value
        )
      : won(
          value
        )
  );
}


function setText(
  id,
  text
) {
  const el = $(
    id
  );

  if (el) {
    el.textContent =
      text;
  }
}


function setHtml(
  id,
  html
) {
  const el = $(
    id
  );

  if (el) {
    el.innerHTML =
      html;
  }
}


function toDateKey(
  date
) {
  const y =
    date.getFullYear();

  const m =
    String(
      date.getMonth()
      + 1
    ).padStart(
      2,
      '0'
    );

  const d =
    String(
      date.getDate()
    ).padStart(
      2,
      '0'
    );

  return (
    `${y}-${m}-${d}`
  );
}


function todayKey() {
  return toDateKey(
    new Date()
  );
}


function normalizeTradeDate(
  raw
) {
  if (!raw) {
    return todayKey();
  }

  const text =
    String(
      raw
    );

  const match =
    text.match(
      /(\d{4})[./-](\d{1,2})[./-](\d{1,2})/
    );

  if (match) {
    return (
      `${match[1]}-`
      +
      `${String(
        match[2]
      ).padStart(
        2,
        '0'
      )}-`
      +
      `${String(
        match[3]
      ).padStart(
        2,
        '0'
      )}`
    );
  }

  const parsed =
    new Date(
      text
    );

  if (
    Number.isNaN(
      parsed.getTime()
    )
  ) {
    return todayKey();
  }

  return toDateKey(
    parsed
  );
}


function viRemain(
  x
) {
  const price =
    Number(
      x?.price || 0
    );

  const vi =
    Number(
      x?.vi_pre || 0
    );

  if (
    MARKET_MODE !== 'KR'
    ||
    price <= 0
    ||
    vi <= 0
  ) {
    return '—';
  }

  return pct(
    (
      (
        vi / price
      )
      - 1
    )
    * 100
  );
}


function updateModeUi() {
  document.body.dataset.market =
    MARKET_MODE;

  const isUS =
    MARKET_MODE === 'US';

  $('marketModeBtn')
    ?.classList
    .toggle(
      'us',
      isUS
    );

  $('marketModeBtn')
    ?.setAttribute(
      'aria-pressed',
      isUS
        ? 'true'
        : 'false'
    );

  $('krModeLabel')
    ?.classList
    .toggle(
      'active',
      !isUS
    );

  $('usModeLabel')
    ?.classList
    .toggle(
      'active',
      isUS
    );

  setText(
    'marketModeCaption',
    isUS
      ? '미장 주요 지수'
      : '국장 주요 지수'
  );

  setText(
    'sectorCaption',
    isUS
      ? '미국 종목 업종 강도'
      : '국내 주도 섹터'
  );

  setText(
    'flowTitle',
    isUS
      ? '미국 종목 분석 후보'
      : '국내 수급 포착 후보'
  );

  setText(
    'flowCaption',
    isUS
      ? 'NHPLUG 미국주식 전용'
      : 'KRX / NXT 공식 시세'
  );

  setText(
    'smartTitle',
    isUS
      ? '미국 스마트 분석'
      : '스마트머니 + 저평가'
  );

  setText(
    'smartCaption',
    isUS
      ? 'PER · PBR · 기술 점수'
      : 'PER · PBR · 외국인 · 기관'
  );

  setText(
    'holdingCaption',
    isUS
      ? '미장 PAPER 별도'
      : '국장 PAPER'
  );

  setText(
    'heroMarketText',
    isUS
      ? 'NHPLUG US · PAPER ANALYSIS'
      : 'KRX / NXT · PAPER · AUTO SIGNAL'
  );

  setText(
    'subtitleText',
    isUS
      ? 'NHPLUG 미국주식 기반 AI 분석 대시보드'
      : 'NHPLUG/KRX 기반 AI 모의투자 대시보드'
  );
}


async function setMarketMode(
  mode
) {
  const next =
    mode === 'US'
      ? 'US'
      : 'KR';

  if (
    next === MARKET_MODE
  ) {
    return;
  }

  MARKET_MODE =
    next;

  saveMarketMode(
    MARKET_MODE
  );

  budgetInitializedFor =
    null;

  selectedProfitDate =
    null;

  currentProfitMap = {};

  updateModeUi();

  await refresh(
    true
  );
}


async function toggleMarketMode() {
  await setMarketMode(
    MARKET_MODE === 'KR'
      ? 'US'
      : 'KR'
  );
}


async function saveBudget() {
  const input =
    $('budget');

  const amount =
    parseInt(
      String(
        input?.value || ''
      ).replace(
        /\D/g,
        ''
      ),
      10
    ) || 0;

  if (
    amount <= 0
  ) {
    alert(
      '운용금액을 입력해주세요.'
    );

    return;
  }

  const maxCash =
    Number(
      STATE?.paper
        ?.initial_cash
      || 1000000
    );

  if (
    amount > maxCash
  ) {
    alert(
      '운용금액은 가상 총자금 '
      +
      won(
        maxCash
      )
      +
      '을 초과할 수 없습니다.'
    );

    return;
  }

  const btn =
    $('saveBudgetBtn');

  if (btn) {
    btn.disabled =
      true;

    btn.textContent =
      '저장 중';
  }

  try {
    const response =
      await fetch(
        '/api/budget',
        {
          method:
            'POST',

          headers: {
            'Content-Type':
              'application/json'
          },

          body:
            JSON.stringify(
              {
                amount,
                market:
                  MARKET_MODE
              }
            )
        }
      );

    if (
      !response.ok
    ) {
      throw new Error(
        `budget HTTP ${response.status}`
      );
    }

    const data =
      await response.json();

    if (
      STATE?.paper
    ) {
      STATE.paper.budget =
        data.budget;
    }

    setText(
      'currentBudget',
      '현재 운용값: '
      +
      won(
        data.budget
      )
    );

    setText(
      'heldCost',
      '보유원가 '
      +
      won(
        STATE?.paper
          ?.held_cost || 0
      )
      +
      ' / 한도 '
      +
      won(
        data.budget
      )
    );

    alert(
      '오늘 운용금액이 '
      +
      won(
        data.budget
      )
      +
      '으로 설정되었습니다.'
    );

  } catch (error) {
    console.error(
      error
    );

    alert(
      '운용금액 저장에 실패했습니다.'
    );

  } finally {
    if (btn) {
      btn.disabled =
        false;

      btn.textContent =
        '저장';
    }
  }
}


function scrollToSection(
  id
) {
  const target =
    $(id);

  if (!target) {
    return;
  }

  target.scrollIntoView(
    {
      behavior:
        'smooth',

      block:
        'start'
    }
  );
}


function candidateRow(
  x,
  smart = false,
  rank = 0
) {
  const payload =
    encodeURIComponent(
      JSON.stringify(
        x
      )
    );

  const isUS =
    MARKET_MODE === 'US';

  let metric3Title;
  let metric3Value;
  let metric4Title;
  let metric4Value;

  if (smart) {
    if (isUS) {
      metric3Title =
        'AI 점수';

      metric3Value =
        Number(
          x.score || 0
        ).toFixed(
          1
        );

      metric4Title =
        '체결강도';

      metric4Value =
        Math.round(
          x.execution_strength
          || 0
        );

    } else {
      metric3Title =
        '외국인 / 기관';

      metric3Value =
        `${Math.round(
          x.foreign_net || 0
        )} / ${Math.round(
          x.institution_net || 0
        )}`;

      metric4Title =
        '체결강도';

      metric4Value =
        Math.round(
          x.execution_strength
          || 0
        );
    }

  } else {
    metric3Title =
      isUS
        ? 'VI'
        : '목표가(VI)';

    metric3Value =
      isUS
        ? 'KR 전용'
        : priceText(
            x.vi_pre,
            'KR'
          );

    metric4Title =
      isUS
        ? 'PER / PBR'
        : 'VI까지';

    metric4Value =
      isUS
        ? `${Number(
            x.per || 0
          ).toFixed(
            1
          )} / ${Number(
            x.pbr || 0
          ).toFixed(
            2
          )}`
        : viRemain(
            x
          );
  }

  return `
    <div
      class="row"
      data-detail="${payload}"
    >

      <div class="stock-top">

        <div class="stock-left">

          <div class="name">
            ${x.name || x.code || '-'}
          </div>

          <div class="code">
            ${x.code || ''}
            ${
              x.sector
                ? ` · ${x.sector}`
                : ''
            }
          </div>

          <span class="pill">
            ${
              (
                x.reasons || []
              )
              .slice(
                0,
                2
              )
              .join(
                ' · '
              )
              ||
              '분석중'
            }
          </span>

        </div>

        <div class="stock-rank">
          ${
            rank > 0
              ? `${rank}위`
              : ''
          }
        </div>

      </div>


      <div class="metric-grid">

        <div class="metric">

          <span class="metric-title">
            현재가
          </span>

          <span class="metric-value">
            ${
              priceText(
                x.price,
                x.market
                || MARKET_MODE
              )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            ${
              smart
                ? 'PER / PBR'
                : 'AI 점수'
            }
          </span>

          <span
            class="
              metric-value
              ${
                smart
                  ? ''
                  : 'score'
              }
            "
          >
            ${
              smart
                ? `${Number(
                    x.per || 0
                  ).toFixed(
                    1
                  )} / ${Number(
                    x.pbr || 0
                  ).toFixed(
                    2
                  )}`
                : Number(
                    x.score || 0
                  ).toFixed(
                    1
                  )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            ${metric3Title}
          </span>

          <span class="metric-value">
            ${metric3Value}
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            ${metric4Title}
          </span>

          <span class="metric-value">
            ${metric4Value}
          </span>

        </div>

      </div>

    </div>
  `;
}


function positionRow(
  x
) {
  return `
    <div class="row">

      <div class="stock-top">

        <div class="stock-left">

          <div class="name">
            ● ${x.name || x.code}
          </div>

          <div class="code">
            ${x.code} · ${x.qty}주
          </div>

        </div>

      </div>


      <div class="metric-grid">

        <div class="metric">

          <span class="metric-title">
            평단
          </span>

          <span class="metric-value">
            ${won(x.avg_price)}
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            현재가
          </span>

          <span class="metric-value">
            ${won(x.current_price)}
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            손익률
          </span>

          <span
            class="
              metric-value
              ${
                Number(
                  x.pnl || 0
                ) >= 0
                  ? 'pos'
                  : 'neg'
              }
            "
          >
            ${pct(x.pnl_pct)}
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            손익금액
          </span>

          <span
            class="
              metric-value
              ${
                Number(
                  x.pnl || 0
                ) >= 0
                  ? 'pos'
                  : 'neg'
              }
            "
          >
            ${won(x.pnl)}
          </span>

        </div>

      </div>

    </div>
  `;
}


function tradeRow(
  t
) {
  return `
    <div class="row">

      <div class="stock-top">

        <div class="stock-left">

          <div class="name">
            ${
              t.side === 'BUY'
                ? '매수'
                : '매도'
            }
            ·
            ${t.name || t.code}
          </div>

          <div class="code">
            ${t.date || ''}
            ${t.time || ''}
            ·
            ${t.qty || 0}주
            ·
            ${t.code || ''}
          </div>

        </div>

      </div>


      <div class="metric-grid">

        <div class="metric">
          <span class="metric-title">
            체결가
          </span>

          <span class="metric-value">
            ${won(t.price)}
          </span>
        </div>


        <div class="metric">
          <span class="metric-title">
            실현손익
          </span>

          <span
            class="
              metric-value
              ${
                Number(
                  t.pnl || 0
                ) >= 0
                  ? 'pos'
                  : 'neg'
              }
            "
          >
            ${won(t.pnl)}
          </span>
        </div>


        <div class="metric">
          <span class="metric-title">
            수익률
          </span>

          <span
            class="
              metric-value
              ${
                Number(
                  t.pnl || 0
                ) >= 0
                  ? 'pos'
                  : 'neg'
              }
            "
          >
            ${pct(t.pnl_pct)}
          </span>
        </div>


        <div class="metric">
          <span class="metric-title">
            구분
          </span>

          <span class="metric-value">
            ${t.side || ''}
          </span>
        </div>

      </div>

    </div>
  `;
}


function miniChart(
  series
) {
  const values =
    Array.isArray(
      series
    )
      ? series
          .map(
            Number
          )
          .filter(
            Number.isFinite
          )
      : [];

  if (
    values.length < 2
  ) {
    return '';
  }

  const min =
    Math.min(
      ...values
    );

  const max =
    Math.max(
      ...values
    );

  return `
    <div
      style="
        display:flex;
        align-items:end;
        gap:2px;
        height:30px;
        margin-top:8px
      "
    >

      ${
        values
          .slice(
            -12
          )
          .map(
            (v) => {
              const h =
                Math.max(
                  4,
                  (
                    (
                      v - min
                    )
                    /
                    (
                      max - min
                      || 1
                    )
                  )
                  * 26
                  + 4
                );

              return `
                <i
                  style="
                    display:block;
                    flex:1;
                    height:${h}px;
                    border-radius:3px 3px 0 0;
                    background:rgba(126,231,255,.65)
                  "
                ></i>
              `;
            }
          )
          .join('')
      }

    </div>
  `;
}


function renderMarkets(
  markets
) {
  setHtml(
    'markets',

    markets.length

      ? markets
          .map(
            (m) => {
              const change =
                m.change == null
                  ? null
                  : Number(
                      m.change
                    );

              const rate =
                m.change_pct == null
                  ? null
                  : Number(
                      m.change_pct
                    );

              const cls =
                rate == null
                  ? ''
                  : rate >= 0
                    ? 'pos'
                    : 'neg';

              return `
                <div class="market">

                  <b>
                    ${m.label || '-'}
                  </b>

                  <strong>
                    ${
                      m.value == null
                        ? '—'
                        : plain(
                            m.value
                          )
                    }
                  </strong>

                  <div
                    class="
                      delta
                      ${cls}
                    "
                  >
                    ${
                      change == null
                        ? ''
                        : `${
                            change >= 0
                              ? '+'
                              : ''
                          }${plain(
                            change
                          )} · ${pct(
                            rate
                          )}`
                    }
                  </div>

                  ${
                    miniChart(
                      m.series
                    )
                  }

                  <div class="pending">
                    ${
                      m.source
                        ? `${m.source} · `
                        : ''
                    }
                    ${m.status || ''}
                  </div>

                </div>
              `;
            }
          )
          .join('')

      : `
          <div class="empty">
            시장 지수 데이터를
            불러오는 중입니다.
          </div>
        `
  );
}


function renderSession(
  session
) {
  const panel =
    $('sessionPanel');

  if (!panel) {
    return;
  }

  if (
    MARKET_MODE !== 'KR'
    ||
    !session
  ) {
    panel.style.display =
      'none';

    panel.innerHTML =
      '';

    return;
  }

  panel.style.display =
    '';

  panel.innerHTML = `
    <div
      class="sub-title-row"
      style="margin-bottom:0"
    >

      <div>

        <b>
          NXT 거래세션
        </b>

        <div
          class="pending"
          style="margin-top:6px"
        >
          프리 08:00~08:50
          · 메인 09:00:30~15:20
          · 애프터 15:40~20:00
        </div>

      </div>

      <span
        class="${
          session.open
            ? 'pos'
            : ''
        }"
      >
        ${
          session.label
          || session.session
        }
        ·
        ${
          session.status
          || ''
        }
      </span>

    </div>
  `;
}


function detail(
  x
) {
  const series =
    Array.isArray(
      x?.series
    )
      ? x.series
          .map(
            Number
          )
          .filter(
            Number.isFinite
          )
      : [];

  const min =
    series.length
      ? Math.min(
          ...series
        )
      : 0;

  const max =
    series.length
      ? Math.max(
          ...series
        )
      : 1;

  const bars =
    series
      .map(
        (v) => `
          <div
            class="bar"
            style="
              height:${
                Math.max(
                  2,
                  (
                    (
                      v - min
                    )
                    /
                    (
                      max - min
                      || 1
                    )
                  )
                  * 100
                )
              }%
            "
          ></div>
        `
      )
      .join('');

  const isUS =
    (
      x?.market
      || MARKET_MODE
    ) === 'US';

  setHtml(
    'detail',
    `
      <h2>
        ${x?.name || x?.code || '-'}

        <small>
          ${x?.code || ''}
        </small>
      </h2>


      <h1>
        ${
          priceText(
            x?.price,
            x?.market
            || MARKET_MODE
          )
        }
      </h1>


      <div class="chart">
        ${bars}
      </div>


      <p>
        <b>
          PER
        </b>

        ${
          Number(
            x?.per || 0
          ).toFixed(
            2
          )
        }

        &nbsp;

        <b>
          PBR
        </b>

        ${
          Number(
            x?.pbr || 0
          ).toFixed(
            2
          )
        }
      </p>


      ${
        isUS
          ? ''
          : `
              <p>
                <b>
                  목표가(VI)
                </b>

                ${
                  priceText(
                    x?.vi_pre,
                    'KR'
                  )
                }
              </p>

              <p>
                <b>
                  VI까지
                </b>

                ${
                  viRemain(
                    x
                  )
                }
              </p>
            `
      }


      <p>
        <b>
          AI 점수
        </b>

        ${
          Number(
            x?.score || 0
          ).toFixed(
            1
          )
        }
      </p>


      ${
        !isUS
          ? `
              <p>
                <b>
                  외국인 / 기관
                </b>

                ${
                  Math.round(
                    x?.foreign_net
                    || 0
                  )
                }
                /
                ${
                  Math.round(
                    x?.institution_net
                    || 0
                  )
                }
              </p>
            `
          : ''
      }


      <p>
        ${
          (
            x?.reasons
            || []
          ).join(
            ' · '
          )
          ||
          '분석 데이터 축적 중'
        }
      </p>
    `
  );

  $('modal')
    ?.classList
    .add(
      'show'
    );
}


function closeModal() {
  $('modal')
    ?.classList
    .remove(
      'show'
    );
}


function buildProfitMap(
  trades
) {
  const map = {};

  (
    trades || []
  ).forEach(
    (t) => {
      const realized =
        Number(
          t.pnl || 0
        );

      if (
        realized === 0
        &&
        t.side !== 'SELL'
      ) {
        return;
      }

      const key =
        normalizeTradeDate(
          t.date
          || t.time
        );

      if (!map[key]) {
        map[key] = {
          total: 0,
          items: []
        };
      }

      map[key].total +=
        realized;

      map[key].items.push(
        {
          name:
            t.name
            || t.code
            || '-',

          code:
            t.code
            || '',

          pnl:
            realized,

          pnl_pct:
            Number(
              t.pnl_pct || 0
            ),

          time:
            t.time
            || '',

          side:
            t.side
            || ''
        }
      );
    }
  );

  return map;
}


function renderProfitDetail(
  dateKey
) {
  selectedProfitDate =
    dateKey;

  const box =
    currentProfitMap[
      dateKey
    ];

  if (!box) {
    setHtml(
      'profitSummary',
      `${dateKey} 실현손익: 0원`
    );

    setHtml(
      'profitDetailList',
      `
        <div class="empty">
          선택한 날짜의
          수익 내역이 없습니다.
        </div>
      `
    );

    drawProfitCalendar();

    return;
  }

  setHtml(
    'profitSummary',
    `
      ${dateKey} 실현손익:

      <b
        class="${
          box.total >= 0
            ? 'pos'
            : 'neg'
        }"
      >
        ${won(box.total)}
      </b>
    `
  );

  setHtml(
    'profitDetailList',

    box.items
      .map(
        (item) => `
          <div class="profit-row">

            <div class="profit-left">

              <b>
                ${item.name}
              </b>

              <span>
                ${item.code}
                ·
                ${item.time}
                ·
                ${item.side}
              </span>

            </div>


            <div class="profit-right">

              <b
                class="${
                  item.pnl >= 0
                    ? 'pos'
                    : 'neg'
                }"
              >
                ${won(item.pnl)}
              </b>

              <span>
                ${pct(item.pnl_pct)}
              </span>

            </div>

          </div>
        `
      )
      .join('')
      ||
      `
        <div class="empty">
          상세 수익 내역이 없습니다.
        </div>
      `
  );

  drawProfitCalendar();
}


function drawProfitCalendar() {
  const cal =
    $('profitCalendar');

  const title =
    $('profitMonthTitle');

  if (
    !cal
    ||
    !title
  ) {
    return;
  }

  const year =
    profitCursor
      .getFullYear();

  const month =
    profitCursor
      .getMonth();

  title.textContent =
    `${year}년 ${month + 1}월`;

  const first =
    new Date(
      year,
      month,
      1
    );

  const last =
    new Date(
      year,
      month + 1,
      0
    );

  const startWeekday =
    first.getDay();

  const daysInMonth =
    last.getDate();

  const prevLast =
    new Date(
      year,
      month,
      0
    ).getDate();

  const cells = [];


  for (
    let i =
      startWeekday - 1;

    i >= 0;

    i -= 1
  ) {
    const dayNum =
      prevLast - i;

    const d =
      new Date(
        year,
        month - 1,
        dayNum
      );

    cells.push(
      {
        key:
          toDateKey(
            d
          ),

        day:
          dayNum,

        other:
          true
      }
    );
  }


  for (
    let day = 1;

    day <= daysInMonth;

    day += 1
  ) {
    const d =
      new Date(
        year,
        month,
        day
      );

    cells.push(
      {
        key:
          toDateKey(
            d
          ),

        day,

        other:
          false
      }
    );
  }


  while (
    cells.length % 7
    !== 0
  ) {
    const dayNum =
      cells.length
      -
      (
        startWeekday
        +
        daysInMonth
      )
      +
      1;

    const d =
      new Date(
        year,
        month + 1,
        dayNum
      );

    cells.push(
      {
        key:
          toDateKey(
            d
          ),

        day:
          dayNum,

        other:
          true
      }
    );
  }


  cal.innerHTML =
    cells
      .map(
        (cell) => {
          const data =
            currentProfitMap[
              cell.key
            ];

          const total =
            Number(
              data?.total || 0
            );

          return `
            <button
              class="
                day-cell
                ${
                  cell.other
                    ? 'is-other'
                    : ''
                }
                ${
                  selectedProfitDate
                  === cell.key
                    ? 'is-active'
                    : ''
                }
              "
              type="button"
              data-date="${cell.key}"
            >

              <div class="day-head">
                ${cell.day}
              </div>

              <div
                class="
                  day-profit
                  ${
                    total >= 0
                      ? 'pos'
                      : 'neg'
                  }
                "
              >
                ${
                  data
                    ? won(
                        total
                      )
                    : ''
                }
              </div>

            </button>
          `;
        }
      )
      .join('');
}


function render(
  s
) {
  if (
    !s
    ||
    !s.paper
    ||
    s.market_mode
    !== MARKET_MODE
  ) {
    throw new Error(
      'invalid or stale state payload'
    );
  }

  STATE = s;

  const p =
    s.paper;


  setText(
    'equity',
    won(
      p.equity
    )
  );


  setText(
    'cash',
    '가상현금 '
    +
    won(
      p.cash
    )
  );


  const budgetInput =
    $('budget');

  if (
    budgetInput
    &&
    budgetInitializedFor
    !== MARKET_MODE
  ) {
    budgetInput.value =
      p.budget;

    budgetInitializedFor =
      MARKET_MODE;
  }


  setText(
    'currentBudget',
    '현재 운용값: '
    +
    won(
      p.budget
    )
  );


  setText(
    'heldCost',
    '보유원가 '
    +
    won(
      p.held_cost
    )
    +
    ' / 한도 '
    +
    won(
      p.budget
    )
  );


  const h =
    s.health
    || {};


  const marketConnected =
    Boolean(
      h.realtime?.[
        MARKET_MODE
      ]
    )
    ||
    Number(
      h.priced?.[
        MARKET_MODE
      ]
      || 0
    ) > 0;


  setText(
    'health',

    marketConnected

      ? (
          '● NH '
          +
          (
            MARKET_MODE
            === 'KR'
              ? '국내'
              : '미국'
          )
          +
          ' 시세 수신'
        )

      : (
          '○ '
          +
          (
            h.nh_configured
              ? 'NH 시세 수신 대기'
              : 'NH API 키 미설정'
          )
        )
  );


  renderMarkets(
    Array.isArray(
      s.market
    )
      ? s.market
          .filter(
            Boolean
          )
      : []
  );


  renderSession(
    s.session
  );


  const sectors =
    Array.isArray(
      s.sectors
    )
      ? s.sectors
      : [];


  setHtml(
    'sectors',

    sectors.length

      ? sectors
          .map(
            (x, i) => `
              <div class="sector">
                ${i + 1}위
                ·
                ${x.sector || '기타'}
                ${pct(x.change_pct)}
                ${
                  x.leader
                    ? ` · ${x.leader}`
                    : ''
                }
              </div>
            `
          )
          .join('')

      : `
          <div class="empty">
            ${
              MARKET_MODE === 'KR'
                ? '국내'
                : '미국'
            }
            시세가 쌓이면
            섹터 강도가 표시됩니다.
          </div>
        `
  );


  const positions =
    Array.isArray(
      p.positions
    )
      ? p.positions
      : [];


  setHtml(
    'positions',

    positions.length

      ? positions
          .map(
            positionRow
          )
          .join('')

      : `
          <div class="empty">
            현재 보유종목이 없습니다.
          </div>
        `
  );


  const scalp =
    Array.isArray(
      s.scalp
    )
      ? s.scalp
      : [];


  setHtml(
    'scalpList',

    scalp.length

      ? scalp
          .map(
            (x, i) =>
              candidateRow(
                x,
                false,
                i + 1
              )
          )
          .join('')

      : `
          <div class="empty">
            ${
              MARKET_MODE === 'KR'
                ? '국내'
                : '미국'
            }
            후보를 수집 중입니다.
          </div>
        `
  );


  const smart =
    Array.isArray(
      s.smart
    )
      ? s.smart
      : [];


  setHtml(
    'smartList',

    smart.length

      ? smart
          .map(
            (x, i) =>
              candidateRow(
                x,
                true,
                i + 1
              )
          )
          .join('')

      : `
          <div class="empty">
            스마트 분석 후보를
            수집 중입니다.
          </div>
        `
  );


  const trades =
    Array.isArray(
      p.trades
    )
      ? p.trades
      : [];


  setHtml(
    'tradeList',

    trades.length

      ? trades
          .map(
            tradeRow
          )
          .join('')

      : `
          <div class="empty">
            오늘 PAPER 거래가 없습니다.
          </div>
        `
  );


  currentProfitMap =
    buildProfitMap(
      trades
    );


  drawProfitCalendar();


  if (
    selectedProfitDate
  ) {
    renderProfitDetail(
      selectedProfitDate
    );

  } else {
    const keys =
      Object.keys(
        currentProfitMap
      )
      .sort()
      .reverse();

    if (
      keys.length
    ) {
      renderProfitDetail(
        keys[0]
      );

    } else {
      setHtml(
        'profitSummary',
        '날짜를 누르면 그날의 수익 내역이 표시됩니다.'
      );

      setHtml(
        'profitDetailList',
        `
          <div class="empty">
            아직 실현손익 데이터가 없습니다.
          </div>
        `
      );
    }
  }
}


async function refresh(
  force = false
) {
  if (
    refreshing
    &&
    !force
  ) {
    return;
  }

  refreshing =
    true;

  const requestedMode =
    MARKET_MODE;

  try {
    const response =
      await fetch(
        `/api/state?market=${encodeURIComponent(
          requestedMode
        )}`,
        {
          cache:
            'no-store'
        }
      );

    if (
      !response.ok
    ) {
      throw new Error(
        `state HTTP ${response.status}`
      );
    }

    const data =
      await response.json();

    if (
      requestedMode
      !== MARKET_MODE
    ) {
      return;
    }

    render(
      data
    );

  } catch (error) {
    setText(
      'health',
      '○ 서버/화면 데이터 연결 오류'
    );

    console.error(
      error
    );

  } finally {
    refreshing =
      false;
  }
}


function bindUi() {
  $('marketModeBtn')
    ?.addEventListener(
      'click',
      toggleMarketMode
    );


  $('saveBudgetBtn')
    ?.addEventListener(
      'click',
      saveBudget
    );


  document
    .querySelectorAll(
      '[data-scroll]'
    )
    .forEach(
      (button) => {
        button.addEventListener(
          'click',
          () => {
            scrollToSection(
              button.dataset.scroll
            );
          }
        );
      }
    );


  $('modal')
    ?.addEventListener(
      'click',
      (event) => {
        if (
          event.target
          === event.currentTarget
        ) {
          closeModal();
        }
      }
    );


  $('closeModalBtn')
    ?.addEventListener(
      'click',
      closeModal
    );


  document
    .addEventListener(
      'click',
      (event) => {
        const detailEl =
          event.target
            .closest?.(
              '[data-detail]'
            );

        if (detailEl) {
          try {
            detail(
              JSON.parse(
                decodeURIComponent(
                  detailEl
                    .dataset
                    .detail
                )
              )
            );

          } catch (error) {
            console.error(
              error
            );
          }

          return;
        }


        const dayEl =
          event.target
            .closest?.(
              '[data-date]'
            );

        if (dayEl) {
          renderProfitDetail(
            dayEl.dataset.date
          );
        }
      }
    );


  $('prevMonthBtn')
    ?.addEventListener(
      'click',
      () => {
        profitCursor =
          new Date(
            profitCursor
              .getFullYear(),

            profitCursor
              .getMonth()
              - 1,

            1
          );

        drawProfitCalendar();
      }
    );


  $('nextMonthBtn')
    ?.addEventListener(
      'click',
      () => {
        profitCursor =
          new Date(
            profitCursor
              .getFullYear(),

            profitCursor
              .getMonth()
              + 1,

            1
          );

        drawProfitCalendar();
      }
    );
}


document.addEventListener(
  'DOMContentLoaded',
  () => {
    updateModeUi();

    bindUi();

    refresh();

    setInterval(
      refresh,
      5000
    );
  }
);
