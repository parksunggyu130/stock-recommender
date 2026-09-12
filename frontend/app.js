const top3El = document.getElementById("top3");
const top10El = document.getElementById("top10");
const metaInfoEl = document.getElementById("metaInfo");
const tradingDateEl = document.getElementById("tradingDate");
const refreshBtn = document.getElementById("refreshBtn");
const eodBtn = document.getElementById("eodBtn");
const notifyBtn = document.getElementById("notifyBtn");
const notifyStatus = document.getElementById("notifyStatus");
const performanceEl = document.getElementById("performance");
const limitUpTodayEl = document.getElementById("limitUpToday");
const precursorStatsEl = document.getElementById("precursorStats");
const precursorMetaEl = document.getElementById("precursorMeta");

function fmtPrice(n) {
  return Number(n).toLocaleString("ko-KR") + "원";
}

function render(data) {
  tradingDateEl.textContent = data.trading_date || "-";
  metaInfoEl.textContent = data.date
    ? `${data.date} 기준 · 시가총액 상위 종목 스크리닝 결과`
    : "";

  top3El.innerHTML = (data.top3 || [])
    .map(
      (s, i) => `
      <div class="stock-card">
        <span class="rank">TOP ${i + 1}</span>
        <p class="name">${s.name}</p>
        <p class="ticker">${s.ticker}</p>
        <p class="price">${fmtPrice(s.close)}</p>
        <div class="tags">${(s.reasons || []).map((r) => `<span class="tag">${r}</span>`).join("")}</div>
        ${(s.headlines || []).map((h) => `<p class="headline">📰 ${h}</p>`).join("")}
      </div>`
    )
    .join("") || `<p class="loading">오늘의 추천 데이터가 없습니다.</p>`;

  top10El.innerHTML = (data.top10 || [])
    .map(
      (s, i) => `
      <div class="top10-row">
        <div class="left">
          <span class="idx">${i + 1}</span>
          <span class="name">${s.name} (${s.ticker})</span>
        </div>
        <span class="score">${s.score}/5점</span>
      </div>`
    )
    .join("");
}

async function loadToday() {
  try {
    const res = await fetch("/api/recommendations/today");
    if (!res.ok) throw new Error(await res.text());
    render(await res.json());
  } catch (err) {
    top3El.innerHTML = `<p class="loading">추천 데이터를 불러오지 못했습니다: ${err.message}</p>`;
  }
}

async function refreshNow() {
  refreshBtn.disabled = true;
  refreshBtn.textContent = "⏳ 계산 중… (최대 1~2분)";
  try {
    const res = await fetch("/api/recommendations/refresh", { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    render(await res.json());
  } catch (err) {
    alert("추천 계산에 실패했습니다: " + err.message);
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.textContent = "🔄 지금 추천받기";
  }
}

refreshBtn.addEventListener("click", refreshNow);

// ---- 16시 마감 체크: 추천 성과 / 상한가 / 사전 징조 ----

function renderPerformance(perf) {
  if (!perf || !perf.available || !perf.results || perf.results.length === 0) {
    performanceEl.innerHTML = `<p class="loading">아직 마감 체크 전입니다. "지금 마감 체크"를 눌러보세요.</p>`;
    return;
  }
  const rows = perf.results
    .map((r) => {
      const cls = r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : "flat";
      const sign = r.change_pct > 0 ? "+" : "";
      return `
      <div class="perf-row">
        <span>${r.name} (${r.ticker})</span>
        <span>${fmtPrice(r.rec_price)} → ${fmtPrice(r.current_price)}</span>
        <span class="change ${cls}">${sign}${r.change_pct.toFixed(2)}%</span>
      </div>`;
    })
    .join("");

  const sim = perf.simulation;
  const simHtml = sim
    ? (() => {
        const cls = sim.profit > 0 ? "up" : sim.profit < 0 ? "down" : "flat";
        const sign = sim.profit >= 0 ? "+" : "";
        return `
        <div class="sim-box">
          <div class="sim-title">💰 1,000만원 가상 투자 시뮬레이션 <span class="sim-note">(수수료·세금 미반영)</span></div>
          <div class="sim-summary">
            <span>${fmtPrice(sim.seed)} → ${fmtPrice(sim.final_value)}</span>
            <span class="change ${cls}">${sign}${sim.profit.toLocaleString("ko-KR")}원 (${sign}${sim.profit_pct}%)</span>
          </div>
        </div>`;
      })()
    : "";

  performanceEl.innerHTML = rows + simHtml;
}

function renderLimitUpToday(events) {
  if (!events || events.length === 0) {
    limitUpTodayEl.innerHTML = `<p class="loading">오늘은 상한가(+30%) 종목이 없습니다.</p>`;
    return;
  }
  limitUpTodayEl.innerHTML = events
    .map(
      (e) => `
      <div class="limitup-card">
        <div class="title"><span>${e.name} (${e.ticker})</span><span class="change">+${e.change_pct.toFixed(2)}%</span></div>
        ${e.keywords && e.keywords.length ? `<div class="tags">${e.keywords.map((k) => `<span class="tag">${k}</span>`).join("")}</div>` : ""}
        ${
          e.headlines && e.headlines.length
            ? e.headlines.map((h) => `<p class="headline">📰 ${h}</p>`).join("")
            : `<p class="empty-reason">관련 뉴스를 찾지 못했습니다 (네이버 뉴스 API 키 미설정 시에도 비어있습니다).</p>`
        }
      </div>`
    )
    .join("");
}

function renderPrecursorStats(stats) {
  const total = stats.total_events || 0;
  precursorMetaEl.textContent =
    `누적 상한가 이벤트 ${total}건 기준` +
    (total < 10 ? " — 데이터가 아직 적어 참고용입니다. 앱을 오래 돌릴수록 통계가 정교해집니다." : "");

  const offsets = Object.keys(stats.by_offset || {})
    .map(Number)
    .sort((a, b) => a - b);

  if (offsets.length === 0) {
    precursorStatsEl.innerHTML = `<p class="loading">아직 누적된 상한가 이벤트가 없습니다. 매일 마감 체크가 쌓이면 이곳에 사전 징조 통계가 표시됩니다.</p>`;
    return;
  }

  const offsetLabel = (o) => (o === 0 ? "상한가 당일" : `${Math.abs(o)}거래일 전`);
  const conditionLabels = [];
  offsets.forEach((o) => {
    Object.keys(stats.by_offset[String(o)].condition_rates || {}).forEach((label) => {
      if (!conditionLabels.includes(label)) conditionLabels.push(label);
    });
  });

  let html = "<table><thead><tr><th>구분</th>";
  offsets.forEach((o) => (html += `<th>${offsetLabel(o)}</th>`));
  html += "</tr></thead><tbody>";

  html += `<tr><td class="cond-label">표본 수</td>${offsets
    .map((o) => `<td>${stats.by_offset[String(o)].sample_count}건</td>`)
    .join("")}</tr>`;
  html += `<tr><td class="cond-label">평균 점수</td>${offsets
    .map((o) => `<td>${stats.by_offset[String(o)].avg_score}/5</td>`)
    .join("")}</tr>`;

  conditionLabels.forEach((label) => {
    html += `<tr><td class="cond-label">${label}</td>`;
    offsets.forEach((o) => {
      const rate = stats.by_offset[String(o)].condition_rates[label] ?? 0;
      html += `<td>${rate}%</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table>";
  precursorStatsEl.innerHTML = html;
}

async function loadPerformance() {
  try {
    const res = await fetch("/api/performance/today");
    renderPerformance(await res.json());
  } catch (err) {
    // 조용히 무시 (기본 안내 문구 유지)
  }
}

async function loadLimitUpToday() {
  try {
    const res = await fetch("/api/limit-up/today");
    const data = await res.json();
    renderLimitUpToday(data.events);
  } catch (err) {
    limitUpTodayEl.innerHTML = `<p class="loading">불러오지 못했습니다: ${err.message}</p>`;
  }
}

async function loadPrecursorStats() {
  try {
    const res = await fetch("/api/limit-up/precursor-stats");
    renderPrecursorStats(await res.json());
  } catch (err) {
    precursorStatsEl.innerHTML = `<p class="loading">불러오지 못했습니다: ${err.message}</p>`;
  }
}

async function runEodCheck() {
  eodBtn.disabled = true;
  eodBtn.textContent = "⏳ 마감 체크 중… (최대 1분)";
  try {
    const res = await fetch("/api/eod/refresh", { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    await Promise.all([loadPerformance(), loadLimitUpToday(), loadPrecursorStats()]);
  } catch (err) {
    alert("마감 체크에 실패했습니다: " + err.message);
  } finally {
    eodBtn.disabled = false;
    eodBtn.textContent = "📊 지금 마감 체크";
  }
}

eodBtn.addEventListener("click", runEodCheck);

// ---- 서비스워커 & 푸시 알림 ----

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function getRegistration() {
  if (!("serviceWorker" in navigator)) return null;
  return navigator.serviceWorker.register("/sw.js");
}

async function refreshNotifyButton() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    notifyBtn.disabled = true;
    notifyStatus.textContent = "이 브라우저는 웹 푸시를 지원하지 않습니다.";
    return;
  }
  const reg = await navigator.serviceWorker.ready.catch(() => null);
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  if (sub) {
    notifyBtn.textContent = "🔕 알림 끄기";
    notifyStatus.textContent = "매일 아침 7시 추천 알림이 켜져 있습니다.";
  } else {
    notifyBtn.textContent = "🔔 매일 아침 7시 알림 켜기";
    notifyStatus.textContent = "";
  }
}

async function enableNotifications() {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    notifyStatus.textContent = "알림 권한이 거부되었습니다. 브라우저 설정에서 허용해주세요.";
    return;
  }

  const keyRes = await fetch("/api/vapid-public-key");
  const { publicKey, configured } = await keyRes.json();
  if (!configured) {
    notifyStatus.textContent = "서버에 알림 키(VAPID)가 아직 설정되지 않았습니다.";
    return;
  }

  const reg = await getRegistration();
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });

  await fetch("/api/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub.toJSON()),
  });

  await refreshNotifyButton();
}

async function disableNotifications() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await fetch("/api/subscribe", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    });
    await sub.unsubscribe();
  }
  await refreshNotifyButton();
}

notifyBtn.addEventListener("click", async () => {
  notifyBtn.disabled = true;
  try {
    const reg = await navigator.serviceWorker.ready.catch(() => null);
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (sub) {
      await disableNotifications();
    } else {
      await enableNotifications();
    }
  } catch (err) {
    notifyStatus.textContent = "알림 설정 중 오류: " + err.message;
  } finally {
    notifyBtn.disabled = false;
  }
});

getRegistration().then(refreshNotifyButton);
loadToday();
loadPerformance();
loadLimitUpToday();
loadPrecursorStats();
