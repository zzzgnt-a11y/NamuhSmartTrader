let STATE = null;

let refreshing = false;

let MODE = 'KR';

let budgetInitialized = false;

let profitCursor =
  new Date();

let currentProfitMap = {};

let selectedProfitDate =
  null;


const $ = (id) =>
  document.getElementById(
    id
  );


const setText = (
  id,
  text
) => {
  const el = $(
    id
  );

  if (el) {
    el.textContent =
      text;
  }
};


const setHtml = (
  id,
  html
) => {
  const el = $(
    id
  );

  if (el) {
    el.innerHTML =
      html;
  }
};


const won = (n) =>
  Number(
    n || 0
  )
  .toLocaleString(
    'ko-KR'
  )
  +
  '원';


const usd = (n) =>
  '$'
  +
  Number(
    n || 0
  )
  .toLocaleString(
    'en-US',
    {
      minimumFractionDigits:
        2,

      maximumFractionDigits:
        4
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


const priceText = (
  value,
  market = MODE
) =>
  market === 'US'
    ? usd(
        value
      )
    : won(
        value
      );


function kstHour() {

  const parts =
    new Intl
      .DateTimeFormat(
        'en-US',
        {
          timeZone:
            'Asia/Seoul',

          hour:
            '2-digit',

          minute:
            '2-digit',

          hour12:
            false
        }
      )
      .formatToParts(
        new Date()
      );

  const hour =
    Number(
      parts.find(
        x =>
          x.type
          === 'hour'
      )?.value
      || 0
    );

  const minute =
    Number(
      parts.find(
        x =>
          x.type
          === 'minute'
      )?.value
      || 0
    );

  return (
    hour
    + minute
    / 60
  );
}


function autoViewMarket() {

  const h =
    kstHour();

  return (
    h >= 20
    || h < 6
  )
    ? 'US'
    : 'KR';
}


function applyModeUi() {

  const isUS =
    MODE === 'US';

  document.body.dataset.market =
    MODE;


  $('marketModeBtn')
    ?.classList
    .toggle(
      'us',
      isUS
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
    'subtitle',

    isUS
      ? 'NHPLUG 공식 데이터 기반 미장 모의투자'
      : 'NHPLUG 공식 데이터 기반 국장 모의투자'
  );


  setText(
    'heroText',

    isUS
      ? '미국 종목만 표시하며 원화 예산을 당일 환율로 환산해 PAPER 매매합니다.'
      : '국내 종목만 표시하며 KRX/NXT 시간대에 맞춰 PAPER 매매합니다.'
  );


  setText(
    'engineLabel',

    isUS
      ? 'US · PAPER · FX'
      : 'KR · PAPER · NHPLUG'
  );


  setText(
    'marketModeCaption',

    isUS
      ? '미장 주요 지수 · 그래프 포함'
      : '국장 주요 지수 · 그래프 포함'
  );


  setText(
    'sectorCaption',

    isUS
      ? '미국 업종 강도'
      : '국내 주도섹터'
  );


  setText(
    'scalpTitle',

    isUS
      ? '미국 분석 후보'
      : '국내 수급 후보'
  );


  setText(
    'scalpCaption',

    isUS
      ? 'AI 점수 · USD 현재가'
      : 'AI 점수 · 목표가(VI)'
  );


  setText(
    'smartTitle',

    isUS
      ? '미국 스마트 분석'
      : '국내 스마트머니 + 저평가'
  );


  setText(
    'smartCaption',

    isUS
      ? 'PER · PBR · 기술점수'
      : 'PER · PBR · 외국인 · 기관'
  );
}


async function setMode(
  mode
) {

  MODE =
    mode === 'US'
      ? 'US'
      : 'KR';

  budgetInitialized =
    false;

  applyModeUi();

  await refresh(
    true
  );
}


async function saveBudget() {

  const raw =
    String(
      $('budget')?.value
      || ''
    )
    .replace(
      /,/g,
      ''
    )
    .trim();


  const amount =
    raw === ''
      ? null
      : Number(
          raw.replace(
            /\D/g,
            ''
          )
        );


  if (
    amount !== null
    &&
    (
      !Number.isFinite(
        amount
      )
      ||
      amount < 0
      ||
      amount > 1000000
    )
  ) {

    alert(
      '0~1,000,000원 범위로 입력하거나 비워주세요.'
    );

    return;
  }


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
              amount:

                amount,

              auto_max_if_unset:
                Boolean(
                  $(
                    'autoMaxIfUnset'
                  )?.checked
                )
            }
          )
      }
    );


  if (
    !response.ok
  ) {

    alert(
      '운용금액 저장 실패'
    );

    return;
  }


  const data =
    await response.json();


  setText(
    'currentBudget',

    data.explicit_budget
    == null

      ? (
          '현재 운용값: 자동 최대 '
          +
          won(
            data.effective_budget
          )
        )

      : (
          '현재 운용값: '
          +
          won(
            data.effective_budget
          )
        )
  );


  await refresh(
    true
  );
}


function sparkline(
  series
) {

  const values =
    (
      Array.isArray(
        series
      )
        ? series
        : []
    )
    .map(
      Number
    )
    .filter(
      Number.isFinite
    );


  if (
    values.length < 2
  ) {

    return (
      '<div class="pending">'
      +
      '그래프 데이터 축적 중'
      +
      '</div>'
    );
  }


  const width =
    240;

  const height =
    48;


  const min =
    Math.min(
      ...values
    );


  const max =
    Math.max(
      ...values
    );


  const span =
    max - min
    || 1;


  const points =
    values.map(
      (
        value,
        index
      ) => {

        const x =
          (
            index
            /
            (
              values.length
              - 1
            )
          )
          * width;


        const y =
          height
          - 4
          -
          (
            (
              value
              - min
            )
            /
            span
          )
          *
          (
            height
            - 8
          );


        return (
          `${x},${y}`
        );
      }
    )
    .join(
      ' '
    );


  return `
    <svg
      class="index-spark"
      viewBox="0 0 ${width} ${height}"
      preserveAspectRatio="none"
      aria-label="지수 추이 그래프"
    >

      <line
        class="index-base"
        x1="0"
        y1="${height - 4}"
        x2="${width}"
        y2="${height - 4}"
      ></line>

      <polyline
        points="${points}"
      ></polyline>

    </svg>
  `;
}


function marketCards(
  markets
) {

  return markets
    .map(
      (market) => {

        const change =
          market.change
          == null
            ? null
            : Number(
                market.change
              );


        const rate =
          market.change_pct
          == null
            ? null
            : Number(
                market.change_pct
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
              ${market.label}
            </b>

            <strong>
              ${
                market.value
                == null
                  ? '—'
                  : Number(
                      market.value
                    )
                    .toLocaleString(
                      undefined,
                      {
                        maximumFractionDigits:
                          4
                      }
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
                  : (
                      `${
                        change >= 0
                          ? '+'
                          : ''
                      }`
                      +
                      change
                        .toLocaleString(
                          undefined,
                          {
                            maximumFractionDigits:
                              2
                          }
                        )
                      +
                      ' · '
                      +
                      pct(
                        rate
                      )
                    )
              }
            </div>

            ${
              sparkline(
                market.series
              )
            }

            <div class="pending">
              ${
                market.source
                  ? market.source
                    + ' · '
                  : ''
              }

              ${
                market.status
                || ''
              }
            </div>

          </div>
        `;
      }
    )
    .join(
      ''
    );
}


function candidateRow(
  item,
  smart = false,
  rank = 0
) {

  const payload =
    encodeURIComponent(
      JSON.stringify(
        item
      )
    );


  const isUS =
    (
      item.market
      || MODE
    )
    === 'US';


  return `
    <div
      class="row"
      data-detail="${payload}"
    >

      <div class="stock-top">

        <div class="stock-left">

          <div class="name">
            ${
              item.name
              || item.code
            }
          </div>

          <div class="code">
            ${
              item.code
            }

            ${
              item.sector
                ? ' · '
                  + item.sector
                : ''
            }
          </div>

          <span class="pill">
            ${
              (
                item.reasons
                || []
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
          ${rank}위
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
                item.price,
                item.market
                || MODE
              )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            AI 점수
          </span>

          <span
            class="
              metric-value
              score
            "
          >
            ${
              Number(
                item.score
                || 0
              ).toFixed(
                1
              )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            ${
              isUS
                ? 'PER / PBR'
                : '목표가(VI)'
            }
          </span>

          <span class="metric-value">

            ${
              isUS
                ? (
                    Number(
                      item.per
                      || 0
                    ).toFixed(
                      1
                    )
                    +
                    ' / '
                    +
                    Number(
                      item.pbr
                      || 0
                    ).toFixed(
                      2
                    )
                  )

                : priceText(
                    item.vi_pre,
                    'KR'
                  )
            }

          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            ${
              isUS
                ? '통화'
                : '외국인 / 기관'
            }
          </span>

          <span class="metric-value">

            ${
              isUS
                ? 'USD'

                : (
                    Math.round(
                      item.foreign_net
                      || 0
                    )
                    +
                    ' / '
                    +
                    Math.round(
                      item.institution_net
                      || 0
                    )
                  )
            }

          </span>

        </div>


      </div>

    </div>
  `;
}


function positionRow(
  position
) {

  const isUS =
    position.market
    === 'US';


  return `
    <div class="row">

      <div class="stock-top">

        <div class="stock-left">

          <div class="name">
            ● ${
              position.name
              || position.code
            }
          </div>

          <div class="code">
            ${
              position.code
            }
            ·
            ${
              position.qty
            }주

            ${
              isUS
              &&
              position.fx_buy
                ? (
                    ' · 매수환율 '
                    +
                    Number(
                      position.fx_buy
                    )
                    .toLocaleString()
                    +
                    '원'
                  )
                : ''
            }

          </div>

        </div>

      </div>


      <div class="metric-grid">


        <div class="metric">

          <span class="metric-title">
            평단
          </span>

          <span class="metric-value">
            ${
              priceText(
                position.avg_price,
                position.market
              )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            현재가
          </span>

          <span class="metric-value">
            ${
              priceText(
                position.current_price,
                position.market
              )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            원화 손익률
          </span>

          <span
            class="
              metric-value
              ${
                position.pnl >= 0
                  ? 'pos'
                  : 'neg'
              }
            "
          >
            ${
              pct(
                position.pnl_pct
              )
            }
          </span>

        </div>


        <div class="metric">

          <span class="metric-title">
            원화 손익
          </span>

          <span
            class="
              metric-value
              ${
                position.pnl >= 0
                  ? 'pos'
                  : 'neg'
              }
            "
          >
            ${
              won(
                position.pnl
              )
            }
          </span>

        </div>


      </div>

    </div>
  `;
}


function detail(
  item
) {

  setHtml(
    'detail',
    `
      <h2>
        ${
          item.name
          || item.code
        }

        <small>
          ${item.code}
        </small>
      </h2>

      <h1>
        ${
          priceText(
            item.price,
            item.market
            || MODE
          )
        }
      </h1>

      ${
        sparkline(
          item.series
        )
      }

      <p>
        <b>
          AI 점수
        </b>

        ${
          Number(
            item.score
            || 0
          ).toFixed(
            1
          )
        }
      </p>

      <p>
        <b>
          PER / PBR
        </b>

        ${
          Number(
            item.per
            || 0
          ).toFixed(
            2
          )
        }
        /
        ${
          Number(
            item.pbr
            || 0
          ).toFixed(
            2
          )
        }
      </p>

      <p>
        ${
          (
            item.reasons
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


function dateKey(
  date
) {

  return (
    `${date.getFullYear()}-`
    +
    `${String(
      date.getMonth()
      + 1
    ).padStart(
      2,
      '0'
    )}-`
    +
    `${String(
      date.getDate()
    ).padStart(
      2,
      '0'
    )}`
  );
}


function buildProfitMap(
  trades
) {

  const map = {};


  for (
    const trade
    of trades
    || []
  ) {

    if (
      trade.side
      !== 'SELL'
    ) {
      continue;
    }


    const key =
      trade.date
      ||
      dateKey(
        new Date()
      );


    if (!map[key]) {

      map[key] = {
        total:
          0,

        items:
          []
      };

    }


    map[
      key
    ].total +=
      Number(
        trade.pnl
        || 0
      );


    map[
      key
    ].items.push(
      trade
    );

  }


  return map;
}


function drawProfitCalendar() {

  const year =
    profitCursor
      .getFullYear();


  const month =
    profitCursor
      .getMonth();


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


  setText(
    'profitMonthTitle',
    `${year}년 ${month + 1}월`
  );


  const cells = [];


  for (
    let i = 0;

    i < first.getDay();

    i += 1
  ) {

    cells.push(
      null
    );

  }


  for (
    let day = 1;

    day <= last.getDate();

    day += 1
  ) {

    cells.push(
      new Date(
        year,
        month,
        day
      )
    );

  }


  setHtml(
    'profitCalendar',

    cells
      .map(
        (date) => {

          if (!date) {

            return (
              '<div class="day-cell is-other"></div>'
            );

          }


          const key =
            dateKey(
              date
            );


          const value =
            currentProfitMap[
              key
            ]?.total;


          return `
            <button
              class="
                day-cell
                ${
                  selectedProfitDate
                  === key
                    ? 'is-active'
                    : ''
                }
              "
              data-date="${key}"
            >

              <div class="day-head">
                ${
                  date.getDate()
                }
              </div>

              <div
                class="
                  day-profit
                  ${
                    Number(
                      value
                      || 0
                    ) >= 0
                      ? 'pos'
                      : 'neg'
                  }
                "
              >
                ${
                  value == null
                    ? ''
                    : won(
                        value
                      )
                }
              </div>

            </button>
          `;
        }
      )
      .join(
        ''
      )
  );
}


function renderProfitDetail(
  key
) {

  selectedProfitDate =
    key;


  const data =
    currentProfitMap[
      key
    ];


  setHtml(
    'profitSummary',
    `
      ${key} 실현손익:

      <b
        class="${
          Number(
            data?.total
            || 0
          ) >= 0
            ? 'pos'
            : 'neg'
        }"
      >
        ${
          won(
            data?.total
            || 0
          )
        }
      </b>
    `
  );


  setHtml(
    'profitDetailList',

    data
      ? data.items
          .map(
            trade => `
              <div class="profit-row">

                <div class="profit-left">

                  <b>
                    ${
                      trade.name
                      || trade.code
                    }
                  </b>

                  <span>
                    ${trade.code}
                    ·
                    ${trade.time}
                  </span>

                </div>

                <div class="profit-right">

                  <b
                    class="${
                      trade.pnl >= 0
                        ? 'pos'
                        : 'neg'
                    }"
                  >
                    ${
                      won(
                        trade.pnl
                      )
                    }
                  </b>

                  <span>
                    ${
                      pct(
                        trade.pnl_pct
                      )
                    }
                  </span>

                </div>

              </div>
            `
          )
          .join(
            ''
          )

      : (
          '<div class="empty">'
          +
          '선택한 날짜의 매매내역이 없습니다.'
          +
          '</div>'
        )
  );


  drawProfitCalendar();
}


function render(
  state
) {

  if (
    !state
    ||
    state.mode
    !== MODE
  ) {

    throw new Error(
      'market state mismatch'
    );

  }


  STATE =
    state;


  const paper =
    state.paper
    || {};


  const schedule =
    state.schedule
    || {};


  setText(
    'equity',
    won(
      paper.equity
    )
  );


  setText(
    'heldCost',
    (
      '보유원가 '
      +
      won(
        paper.held_cost
      )
      +
      ' / 한도 '
      +
      won(
        paper.effective_budget
      )
    )
  );


  if (
    !budgetInitialized
  ) {

    $('budget').value =
      paper.explicit_budget
      == null
        ? ''
        : paper.explicit_budget;


    $('autoMaxIfUnset').checked =
      Boolean(
        paper.auto_max_if_unset
      );


    budgetInitialized =
      true;

  }


  setText(
    'currentBudget',

    paper.explicit_budget
    == null

      ? (
          '현재 운용값: '
          +
          (
            paper.auto_max_if_unset

              ? (
                  '자동 최대 '
                  +
                  won(
                    paper.effective_budget
                  )
                )

              : '미설정(매수 중지)'
          )
        )

      : (
          '현재 운용값: '
          +
          won(
            paper.effective_budget
          )
        )
  );


  setText(
    'scheduleCard',

    (
      '자동매매 · 국장 '
      +
      (
        schedule.kr_hours
        || '08:00~20:00 KST'
      )
      +
      ' / 미장 '
      +
      (
        schedule.us_hours
        || '20:00~06:00 KST'
      )
      +
      ' · 현재 '
      +
      (
        schedule.label
        || '-'
      )
    )
  );


  setText(
    'fxNote',

    paper.usdkrw > 0

      ? (
          'USD/KRW '
          +
          Number(
            paper.usdkrw
          )
          .toLocaleString(
            undefined,
            {
              maximumFractionDigits:
                2
            }
          )
          +
          '원 · '
          +
          (
            paper.usdkrw_asof
            || '최근 공식값'
          )
        )

      : (
          'USD/KRW 공식 환율 수신 대기'
          +
          ' · 수신 전 미장 신규매수 차단'
        )
  );


  const health =
    state.health
    || {};


  setText(
    'health',

    health.nh_configured

      ? (
          '● NH 연결 · KR '
          +
          (
            health.kr_priced
            || 0
          )
          +
          '/'
          +
          (
            health.kr_tracked
            || 0
          )
          +
          ' · US '
          +
          (
            health.us_priced
            || 0
          )
          +
          '/'
          +
          (
            health.us_tracked
            || 0
          )
        )

      : '○ NH API 키 미설정'
  );


  const session =
    state.session;


  if (
    MODE === 'KR'
    &&
    session
  ) {

    setText(
      'sessionStatus',
      (
        session.label
        +
        ' · '
        +
        session.status
      )
    );


    $('sessionStatus').hidden =
      false;

  }

  else {

    $('sessionStatus').hidden =
      true;

  }


  setHtml(
    'markets',

    marketCards(
      Array.isArray(
        state.market
      )
        ? state.market
        : []
    )
  );


  const sectors =
    Array.isArray(
      state.sectors
    )
      ? state.sectors
      : [];


  setHtml(
    'sectors',

    sectors.length

      ? sectors
          .map(
            (
              item,
              index
            ) => `
              <div class="sector">
                ${index + 1}위
                ·
                ${item.sector}
                ${pct(item.change_pct)}
                ${
                  item.leader
                    ? ' · '
                      + item.leader
                    : ''
                }
              </div>
            `
          )
          .join(
            ''
          )

      : (
          '<div class="empty">'
          +
          '섹터 데이터 축적 중'
          +
          '</div>'
        )
  );


  const scalp =
    Array.isArray(
      state.scalp
    )
      ? state.scalp
      : [];


  const smart =
    Array.isArray(
      state.smart
    )
      ? state.smart
      : [];


  setHtml(
    'scalpList',

    scalp.length

      ? scalp
          .map(
            (
              item,
              index
            ) =>
              candidateRow(
                item,
                false,
                index + 1
              )
          )
          .join(
            ''
          )

      : (
          '<div class="empty">'
          +
          '후보 데이터 축적 중'
          +
          '</div>'
        )
  );


  setHtml(
    'smartList',

    smart.length

      ? smart
          .map(
            (
              item,
              index
            ) =>
              candidateRow(
                item,
                true,
                index + 1
              )
          )
          .join(
            ''
          )

      : (
          '<div class="empty">'
          +
          '스마트 후보 데이터 축적 중'
          +
          '</div>'
        )
  );


  const positions =
    Array.isArray(
      paper.positions
    )
      ? paper.positions
      : [];


  setHtml(
    'positions',

    positions.length

      ? positions
          .map(
            positionRow
          )
          .join(
            ''
          )

      : (
          '<div class="empty">'
          +
          '현재 보유종목이 없습니다.'
          +
          '</div>'
        )
  );


  currentProfitMap =
    buildProfitMap(
      paper.trades
      || []
    );


  drawProfitCalendar();


  if (
    selectedProfitDate
  ) {

    renderProfitDetail(
      selectedProfitDate
    );

  }

  else {

    setHtml(
      'profitSummary',
      '날짜를 누르면 그날의 수익 내역이 표시됩니다.'
    );


    setHtml(
      'profitDetailList',
      '<div class="empty">아직 실현손익 데이터가 없습니다.</div>'
    );

  }


  if (
    state.market_separation
    &&
    !state.market_separation.ok
  ) {

    throw new Error(
      'market separation violation'
    );

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


  try {

    const response =
      await fetch(
        `/api/state?market=${MODE}`,
        {
          cache:
            'no-store'
        }
      );


    if (
      !response.ok
    ) {

      throw new Error(
        `state ${response.status}`
      );

    }


    render(
      await response.json()
    );

  }

  catch (
    error
  ) {

    console.error(
      error
    );


    setText(
      'health',
      '○ 서버/데이터 연결 오류'
    );

  }

  finally {

    refreshing =
      false;

  }

}


function bind(
) {

  $('saveBudgetBtn')
    ?.addEventListener(
      'click',
      saveBudget
    );


  $('marketModeBtn')
    ?.addEventListener(
      'click',
      () =>
        setMode(
          MODE === 'KR'
            ? 'US'
            : 'KR'
        )
    );


  $('krModeLabel')
    ?.addEventListener(
      'click',
      () =>
        setMode(
          'KR'
        )
    );


  $('usModeLabel')
    ?.addEventListener(
      'click',
      () =>
        setMode(
          'US'
        )
    );


  document
    .querySelectorAll(
      '[data-scroll]'
    )
    .forEach(
      button =>

        button
          .addEventListener(
            'click',
            () =>
              $(
                button.dataset.scroll
              )
              ?.scrollIntoView(
                {
                  behavior:
                    'smooth',

                  block:
                    'start'
                }
              )
          )
    );


  document
    .addEventListener(
      'click',
      event => {

        const detailElement =
          event.target
            .closest?.(
              '[data-detail]'
            );


        if (
          detailElement
        ) {

          try {

            detail(
              JSON.parse(
                decodeURIComponent(
                  detailElement
                    .dataset
                    .detail
                )
              )
            );

          }

          catch (
            error
          ) {

            console.error(
              error
            );

          }

          return;

        }


        const day =
          event.target
            .closest?.(
              '[data-date]'
            );


        if (day) {

          renderProfitDetail(
            day.dataset.date
          );

        }

      }
    );


  $('closeModalBtn')
    ?.addEventListener(
      'click',
      () =>
        $('modal')
          ?.classList
          .remove(
            'show'
          )
    );


  $('modal')
    ?.addEventListener(
      'click',
      event => {

        if (
          event.target
          === event.currentTarget
        ) {

          event.currentTarget
            .classList
            .remove(
              'show'
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


document
  .addEventListener(
    'DOMContentLoaded',
    () => {

      MODE =
        autoViewMarket();


      applyModeUi();


      bind();


      refresh();


      setInterval(
        refresh,
        5000
      );

    }
  );
