const state = {
  indicators: [],
  results: {},
  integrations: null,
  references: null,
};

const labels = {
  completeness: "完整性",
  consistency: "一致性",
  timeliness: "时效性",
  validity: "有效性",
  uniqueness: "唯一性",
  integrity: "参照完整性",
  stability: "稳定性",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || `请求失败 (${response.status})`);
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function externalLink(url, label) {
  if (!url || !/^https:\/\/[a-z0-9.-]+\//i.test(url)) {
    return `<span class="reference-link disabled">${escapeHtml(label)}</span>`;
  }
  return `<a class="reference-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function toast(message) {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 2800);
}

function statusText(result) {
  if (!result) return "等待测试";
  return result.passed ? "通过" : "未通过";
}

function conciseMetric(result) {
  if (!result) return "尚无运行结果";
  const metrics = result.metrics || {};
  const preferred = [
    "compression_ratio",
    "parsing_accuracy_percent",
    "alignment_accuracy_percent",
    "ingestion_samples_per_second",
    "minimum_dimension",
    "fused_rows",
    "registered_adapters",
    "dimension_count",
  ];
  const key = preferred.find((item) => Object.hasOwn(metrics, item));
  if (!key) return result.passed ? "目标已满足" : "需要复核";
  const value = metrics[key];
  const units = {
    compression_ratio: ":1",
    parsing_accuracy_percent: "%",
    alignment_accuracy_percent: "%",
    ingestion_samples_per_second: " samples/s",
    minimum_dimension: "%",
  };
  return `${key.replaceAll("_", " ")} ${value}${units[key] || ""}`;
}

function renderOverview() {
  const grid = document.querySelector("#overview-grid");
  grid.innerHTML = state.indicators.map((item) => {
    const result = state.results[item.id];
    const klass = result ? (result.passed ? "pass" : "fail") : "";
    return `
      <article class="metric-card" data-indicator="${item.id}">
        <div class="metric-top">
          <span class="metric-id">${item.id}</span>
          <span class="metric-state ${klass}">${statusText(result)}</span>
        </div>
        <h3>${item.title}</h3>
        <p>${result ? conciseMetric(result) : item.target}</p>
      </article>
    `;
  }).join("");
}

function renderIndicatorList() {
  const list = document.querySelector("#indicator-list");
  list.innerHTML = state.indicators.map((item) => {
    const result = state.results[item.id];
    const klass = result ? (result.passed ? "pass" : "fail") : "";
    return `
      <article class="indicator-row">
        <span class="code">${item.id}</span>
        <div>
          <h3>${item.title}</h3>
          <p>governance/indicator_${item.id.replace(".", "_")}.py</p>
        </div>
        <p>${item.target}</p>
        <div>
          <button class="button secondary run-one" data-id="${item.id}">运行测试</button>
          <div class="row-result ${klass}" id="row-result-${item.id.replace(".", "-")}">${result ? conciseMetric(result) : ""}</div>
        </div>
      </article>
    `;
  }).join("");
  document.querySelectorAll(".run-one").forEach((button) => {
    button.addEventListener("click", () => runOne(button.dataset.id, button));
  });
}

function renderIntegrations() {
  if (!state.integrations || !state.references) return;
  const integrationSummary = state.integrations.summary;
  const referenceSummary = state.references.summary;
  document.querySelector("#integration-summary").innerHTML = `
    <div><span>当前实现</span><strong>${integrationSummary.active}</strong><small>可运行算法</small></div>
    <div><span>计划接入</span><strong>${integrationSummary.planned}</strong><small>外部实现</small></div>
    <div><span>参考技术</span><strong>${referenceSummary.total}</strong><small>论文 / 项目</small></div>
    <div><span>版本待固定</span><strong>${referenceSummary.commit_pending}</strong><small>commit SHA</small></div>
  `;
  const manifestErrors = document.querySelector("#manifest-errors");
  if (state.integrations.load_errors.length) {
    manifestErrors.classList.remove("hidden");
    manifestErrors.innerHTML = `
      <strong>有 ${state.integrations.load_errors.length} 个外部 manifest 未加载</strong>
      ${state.integrations.load_errors.map((item) => `
        <p>${escapeHtml(item.path)} · ${escapeHtml(item.error_type)} · ${escapeHtml(item.message)}</p>
      `).join("")}
    `;
  } else {
    manifestErrors.classList.add("hidden");
    manifestErrors.innerHTML = "";
  }

  const indicatorById = Object.fromEntries(state.indicators.map((item) => [item.id, item]));
  document.querySelector("#integration-matrix").innerHTML =
    state.integrations.indicator_matrix.map((row) => {
      const current = row.current_methods.map((item) => item.method).join("；") || "尚未登记";
      const planned = row.planned_integrations.map((item) => item.name).join("；") || "暂无外部实现";
      return `
        <article class="integration-row">
          <span class="integration-code">${escapeHtml(row.indicator)}</span>
          <div>
            <small>指标</small>
            <strong>${escapeHtml(indicatorById[row.indicator]?.title || row.indicator)}</strong>
          </div>
          <div>
            <small>当前采用方法</small>
            <p>${escapeHtml(current)}</p>
          </div>
          <div>
            <small>待接入论文 / 代码</small>
            <p>${escapeHtml(planned)}</p>
          </div>
          <span class="integration-status ${row.planned_integrations.length ? "planned" : "stable"}">
            ${row.planned_integrations.length ? "接口就绪" : "当前稳定"}
          </span>
        </article>
      `;
    }).join("");

  document.querySelector("#reference-grid").innerHTML =
    state.references.items.map((item) => {
      const licenseClass = item.license_status === "confirmed" ? "confirmed" : "pending";
      const commitText = item.commit_sha ? item.commit_sha.slice(0, 8) : "commit 待固定";
      return `
        <article class="reference-card">
          <div class="reference-topline">
            <span>${escapeHtml(item.venue)}</span>
            <span class="integration-status planned">待接入</span>
          </div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.notes)}</p>
          <div class="concept-list">
            ${item.concepts.map((concept) => `<span>${escapeHtml(concept)}</span>`).join("")}
          </div>
          <dl>
            <div><dt>对应指标</dt><dd>${escapeHtml(item.indicator_ids.join("、"))}</dd></div>
            <div><dt>代码许可</dt><dd class="${licenseClass}">${escapeHtml(item.code_license)}</dd></div>
            <div><dt>版本状态</dt><dd class="${item.commit_sha ? "confirmed" : "pending"}">${escapeHtml(commitText)}</dd></div>
          </dl>
          <div class="reference-actions">
            ${externalLink(item.paper_url, "查看论文")}
            ${externalLink(item.repository_url, item.repository_url ? "查看代码" : "代码待提供")}
          </div>
        </article>
      `;
    }).join("");
}

async function runOne(id, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "测试中";
  try {
    const result = await api(`/api/benchmark/${id}`, {
      method: "POST",
      body: "{}",
    });
    state.results[id] = result;
    renderOverview();
    renderIndicatorList();
    toast(`${id} ${result.passed ? "已通过" : "未通过"}：${conciseMetric(result)}`);
  } catch (error) {
    toast(error.message);
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function runAll() {
  const button = document.querySelector("#run-all");
  button.disabled = true;
  button.textContent = "正在执行 9 项测试";
  try {
    const report = await api("/api/benchmark/all", { method: "POST", body: "{}" });
    report.results.forEach((result) => { state.results[result.indicator] = result; });
    renderOverview();
    renderIndicatorList();
    document.querySelector("#last-run").textContent =
      `${report.generated_at} · ${report.summary.passed}/${report.summary.total} 通过`;
    toast(report.passed ? "全部指标自测通过，报告已生成" : "自测完成，存在未通过指标");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "运行全部自测";
  }
}

async function analyzeData() {
  const button = document.querySelector("#analyze-data");
  const status = document.querySelector("#analysis-status");
  button.disabled = true;
  button.textContent = "治理中";
  status.className = "status-chip idle";
  status.textContent = "正在分析";
  try {
    const result = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        content: document.querySelector("#data-input").value,
        format: document.querySelector("#format-select").value,
      }),
    });
    document.querySelector("#analysis-empty").classList.add("hidden");
    document.querySelector("#analysis-results").classList.remove("hidden");
    document.querySelector("#result-format").textContent = result.source.format.toUpperCase();
    document.querySelector("#result-records").textContent = result.source.records;
    document.querySelector("#result-score").textContent = `${result.quality.overall}%`;
    document.querySelector("#data-preview").textContent =
      JSON.stringify(result.preview, null, 2);
    const bars = document.querySelector("#quality-bars");
    bars.innerHTML = Object.entries(result.quality.dimensions).map(([key, value]) => `
      <div class="quality-row">
        <span>${labels[key] || key}</span>
        <div class="quality-track"><div class="quality-fill" style="width:${Math.max(0, Math.min(value, 100))}%"></div></div>
        <strong>${value}%</strong>
      </div>
    `).join("");
    status.className = `status-chip ${result.quality.minimum >= 95 ? "pass" : "fail"}`;
    status.textContent = result.quality.minimum >= 95 ? "质量达标" : "需治理";
    toast(`已解析 ${result.source.records} 条记录并完成质量测评`);
  } catch (error) {
    status.className = "status-chip fail";
    status.textContent = "处理失败";
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "解析并治理";
  }
}

async function runFusion() {
  const button = document.querySelector("#run-fusion");
  button.disabled = true;
  button.textContent = "融合中";
  try {
    const result = await api("/api/fusion/demo", { method: "POST", body: "{}" });
    document.querySelector("#fusion-result").innerHTML = `
      <span>${result.metrics.sequence_rows} 条序列记录关联 ${result.metrics.relation_rows} 条工单</span>
      <strong>${result.metrics.matched_rows} 条命中 · ${result.metrics.rows_per_second} rows/s</strong>
    `;
    toast("序列与关系数据融合完成");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "运行融合演示";
  }
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
      button.classList.add("active");
      document.querySelector(`#view-${button.dataset.view}`).classList.add("active");
    });
  });
}

function setupFileInput() {
  document.querySelector("#file-input").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    document.querySelector("#data-input").value = await file.text();
    document.querySelector("#input-meta").textContent =
      `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
    const extension = file.name.split(".").pop().toLowerCase();
    const known = ["csv", "tsv", "json", "jsonl", "xml", "ini"];
    document.querySelector("#format-select").value = known.includes(extension) ? extension : "auto";
  });
}

async function init() {
  setupNavigation();
  setupFileInput();
  document.querySelector("#run-all").addEventListener("click", runAll);
  document.querySelector("#analyze-data").addEventListener("click", analyzeData);
  document.querySelector("#run-fusion").addEventListener("click", runFusion);
  try {
    const [catalog, integrations, references] = await Promise.all([
      api("/api/indicators"),
      api("/api/integrations"),
      api("/api/references"),
    ]);
    state.indicators = catalog.items;
    state.integrations = integrations;
    state.references = references;
    renderOverview();
    renderIndicatorList();
    renderIntegrations();
  } catch (error) {
    toast(`无法加载系统元数据：${error.message}`);
  }
}

init();
