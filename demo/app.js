/* Static experience. All market data is synthetic; scoring is exported from StrategyEngine. */
(() => {
  'use strict';
  const data = window.ZHIXING_DEMO;
  const stocks = data.stocks;
  const content = document.getElementById('content');
  const storageKey = 'zhixing-static-demo-v1';
  const defaults = ['demo01', 'demo03', 'demo06'];
  const colors = ['#55794b', '#af8650', '#7a83a4'];
  const names = { research: '个股研究', pool: '参考池与自选', compare: '股票对比', snapshots: '研究快照' };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const number = value => Number(value).toFixed(2);
  const signed = value => `${value > 0 ? '+' : ''}${number(value)}`;
  const tone = value => value >= 0 ? 'up' : 'down';
  const findStock = code => stocks.find(stock => stock.code === code);
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(storageKey)) || {}; } catch { /* Continue in memory. */ }
  if (typeof stored !== 'object' || Array.isArray(stored)) stored = {};
  const validSnapshot = item => item && typeof item.id === 'string' && findStock(item.code)
    && typeof item.note === 'string' && typeof item.savedAt === 'string' && !Number.isNaN(Date.parse(item.savedAt))
    && typeof item.version === 'string' && typeof item.fingerprint === 'string'
    && ['S', 'A', 'B', 'C'].includes(item.grade) && [item.total, item.price, item.change].every(Number.isFinite)
    && Array.isArray(item.dimensions) && item.dimensions.every(dim => typeof dim.label === 'string'
      && Number.isFinite(dim.score) && Array.isArray(dim.reasons) && dim.reasons.every(reason => typeof reason === 'string'));
  const state = {
    route: 'research', stock: stocks[0].code, range: 60, detail: 'overview',
    query: '', pool: 'all', grade: 'all', kind: 'all', note: '',
    compare: ['demo01', 'demo03'],
    watch: new Set(Array.isArray(stored.watch) ? stored.watch.filter(code => findStock(code)) : defaults),
    snapshots: Array.isArray(stored.snapshots) ? stored.snapshots.filter(validSnapshot).slice(0, 20) : [],
    snapshotId: '',
  };
  let toastTimer;
  function toast(message) {
    const el = document.getElementById('toast');
    el.textContent = message; el.classList.add('visible');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('visible'), 3300);
  }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify({ watch: [...state.watch], snapshots: state.snapshots })); return true; }
    catch { toast('浏览器存储不可用，修改在本次打开期间保留。'); return false; }
  }
  function syncNavigation() {
    document.querySelectorAll('[data-nav]').forEach(link => {
      if (link.dataset.nav === state.route) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    document.getElementById('watch-count').textContent = state.watch.size;
    document.getElementById('breadcrumb').textContent = names[state.route];
    document.title = `${names[state.route]} · 知行股研演示`;
  }
  function readRoute() {
    const [route, code] = location.hash.slice(1).split('/');
    state.route = Object.hasOwn(names, route) ? route : 'research';
    if (state.route === 'research' && findStock(code)) {
      if (state.stock !== code) state.note = '';
      state.stock = code;
    }
    state.snapshotId = state.route === 'snapshots' ? code || '' : '';
    render();
  }
  function navigate(route, code = '') {
    const hash = `#${route}${code ? `/${code}` : ''}`;
    if (location.hash === hash) { readRoute(); return; }
    location.hash = hash;
  }
  function render() {
    syncNavigation();
    content.innerHTML = ({ research: researchPage, pool: poolPage, compare: comparePage, snapshots: snapshotsPage })[state.route]();
  }
  function heading(kicker, title, description, action = '') {
    return `<div class="page-heading"><div><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
  }
  function gradeTag(stock) { return `<span class="grade grade-${stock.score.grade}">${stock.score.grade}</span>`; }
  function watchButton(stock, compact = false) {
    const watched = state.watch.has(stock.code);
    return compact
      ? `<button class="star" data-action="watch" data-code="${stock.code}" aria-label="${watched ? '移出自选' : '加入自选'}：${stock.name}" aria-pressed="${watched}">${watched ? '★' : '☆'}</button>`
      : `<button class="btn ${watched ? 'saved' : ''}" data-action="watch" data-code="${stock.code}" aria-pressed="${watched}">${watched ? '★ 已加入自选' : '☆ 加入自选'}</button>`;
  }
  function movingAverage(bars, count, index) {
    if (index < count - 1) return null;
    return bars.slice(index - count + 1, index + 1).reduce((sum, bar) => sum + bar.close, 0) / count;
  }
  function chart(stock) {
    const all = stock.bars, start = all.length - state.range, bars = all.slice(start);
    const width = 720, left = 47, right = 18, plotWidth = width - left - right;
    const low = Math.min(...bars.map(bar => bar.low)) * .985;
    const high = Math.max(...bars.map(bar => bar.high)) * 1.015;
    const y = value => 26 + (high - value) / (high - low) * 211;
    const x = index => left + (index + .5) * plotWidth / bars.length;
    const barWidth = Math.max(2, plotWidth / bars.length * .62);
    const grid = Array.from({ length: 5 }, (_, i) => {
      const value = high - (high - low) * i / 4, height = y(value);
      return `<line x1="${left}" x2="${width - right}" y1="${height}" y2="${height}" stroke="#edf0e8"/><text x="${left - 9}" y="${height + 3}" text-anchor="end" fill="#96a18c" font-size="10">${number(value)}</text>`;
    }).join('');
    const candles = bars.map((bar, i) => {
      const fill = bar.close >= bar.open ? '#bc796b' : '#7a9984';
      return `<line x1="${x(i)}" x2="${x(i)}" y1="${y(bar.high)}" y2="${y(bar.low)}" stroke="${fill}"/><rect x="${x(i) - barWidth / 2}" y="${Math.min(y(bar.open), y(bar.close))}" width="${barWidth}" height="${Math.max(1, Math.abs(y(bar.open) - y(bar.close)))}" fill="${fill}"/>`;
    }).join('');
    const averages = [[5, '#ba965e'], [20, '#688968']].map(([count, color]) => {
      const points = bars.flatMap((_, i) => {
        const value = movingAverage(all, count, start + i);
        return value == null ? [] : [`${x(i)},${y(value)}`];
      });
      return `<polyline fill="none" stroke="${color}" stroke-width="1.5" points="${points.join(' ')}"/>`;
    }).join('');
    const maxVolume = Math.max(...bars.map(bar => bar.volume));
    const volume = bars.map((bar, i) => `<rect x="${x(i) - barWidth / 2}" y="${293 - bar.volume / maxVolume * 29}" width="${barWidth}" height="${bar.volume / maxVolume * 29}" fill="${bar.close >= bar.open ? '#d9b3a9' : '#b6c8b3'}"/>`).join('');
    const labels = [0, Math.floor(bars.length / 2), bars.length - 1].map(i => `<text x="${x(i)}" y="319" text-anchor="${i === 0 ? 'start' : i === bars.length - 1 ? 'end' : 'middle'}" fill="#96a18c" font-size="10">${bars[i].date}</text>`).join('');
    const hover = bars.map((_, i) => `<rect class="chart-point" data-bar="${start + i}" x="${left + i * plotWidth / bars.length}" y="25" width="${plotWidth / bars.length}" height="272"/>`).join('');
    return `<svg class="price-chart" viewBox="0 0 720 333" role="img" aria-label="${escape(stock.name)}最近 ${state.range} 个样本交易日的合成 K 线，包含 MA5、MA20 与成交量"><title>合成 K 线 · ${stock.name}</title>${grid}${candles}${averages}<line x1="${left}" x2="702" y1="256" y2="256" stroke="#edf0e8"/>${volume}${labels}${hover}</svg>`;
  }
  function scoreMini(stock) {
    return stock.score.dimensions.map(dim => `<div><label>${escape(dim.label)}</label><span class="score-track"><i style="width:${Math.min(100, Math.abs(dim.score) / 20 * 100)}%;background:${dim.score < 0 ? '#bc9480' : '#83a06d'}"></i></span><b>${dim.score > 0 ? '+' : ''}${dim.score}</b></div>`).join('');
  }
  function researchPage() {
    const stock = findStock(state.stock), q = stock.input, result = stock.score;
    return heading('01 / EQUITY RESEARCH', '让每一次判断，有据可循。', '选取一个样本，查看走势、评分依据和研究记录。',
      `<form class="search-form" id="stock-search"><input id="search-input" aria-label="搜索演示样本" placeholder="搜索演示名称或代码" autocomplete="off"><button type="submit">查找</button><div id="search-results" class="search-results"></div></form>`)
      + `<div class="quick-picks">${stocks.slice(0, 6).map(s => `<button class="${s.code === state.stock ? 'active' : ''}" data-action="open-stock" data-code="${s.code}" aria-pressed="${s.code === state.stock}">${s.name}</button>`).join('')}</div>
      <section class="quote-card" aria-label="样本行情"><div class="quote-top"><div class="stock-identity"><div class="stock-avatar" aria-hidden="true">${stock.name[0]}</div><div><h2>${stock.name}</h2><small>${stock.code.toUpperCase()} · ${stock.sector} · 演示样本</small></div></div><div class="quote-value"><strong>${number(q.price)}</strong><span class="${tone(q.change_pct)}">${signed(q.change_pct)}%</span></div><div class="quote-actions">${watchButton(stock)}<button class="btn" data-action="add-compare" data-code="${stock.code}">⇄ 加入对比</button></div></div>
      <div class="quote-bottom"><div><span>换手率</span><b>${number(q.turnover_pct)}%</b></div><div><span>市盈率 PE</span><b>${number(q.pe)}</b></div><div><span>市净率 PB</span><b>${number(q.pb)}</b></div><div><span>样本行业涨幅</span><b class="${tone(q.sector_change_pct)}">${signed(q.sector_change_pct)}%</b></div><div><span>样本日期</span><b>${data.asOf}</b></div></div></section>
      <div class="research-grid"><section class="panel"><div class="panel-head"><h2>价格与趋势</h2><div class="segment" aria-label="图表范围">${[60, 120].map(range => `<button class="${state.range === range ? 'active' : ''}" data-action="range" data-range="${range}" aria-pressed="${state.range === range}">${range} 日</button>`).join('')}</div></div><div class="chart-meta"><span>前复权日线样式 · 合成路径</span><b>MA5 ${number(q.ma5)}</b><b>MA20 ${number(q.ma20)}</b></div><div class="chart-wrap">${chart(stock)}</div><div class="chart-readout" id="chart-readout">移动或轻触 K 线，查看当日开高低收与样本成交量。</div><div class="chart-footer"><span>红涨 / 绿跌 · 底部为样本成交量</span><span>120 个样本交易日</span></div></section>
      <section class="panel score-panel"><div class="panel-head"><h2>规则评分</h2><small>7 个维度</small></div><div class="score-main"><div class="grade-orb">${result.grade}</div><div><strong>${result.total_score}</strong><small>规则累计分 · 非百分制</small></div></div><p class="score-description">${result.grade} 级 / ${result.total_score >= 14 ? '查看高贡献因子，结合扣分项继续研究。' : '结合薄弱因子，记录待验证的研究问题。'}</p><div class="score-mini">${scoreMini(stock)}</div><button class="score-link" data-action="detail" data-detail="score">查看评分拆解 <span aria-hidden="true">↗</span></button></section></div>
      <div class="detail-tabs" aria-label="研究内容">${[['overview', '研究概览'], ['score', '评分明细'], ['sources', '数据依据']].map(([key, label]) => `<button class="${state.detail === key ? 'active' : ''}" data-action="detail" data-detail="${key}" aria-pressed="${state.detail === key}">${label}</button>`).join('')}</div><div id="research-detail">${researchDetail(stock)}</div>
      <div class="note-editor"><label for="research-note">研究笔记</label><textarea id="research-note" maxlength="1000" placeholder="例如：继续观察量价配合，核对行业变化…">${escape(state.note)}</textarea><button class="btn primary" data-action="save-snapshot">＋ 保存研究快照</button></div>`;
  }
  function factors(dimensions) {
    return `<div class="factor-list">${dimensions.map(dim => `<div class="factor-row"><span>${escape(dim.label)}</span><strong>${dim.score > 0 ? '+' : ''}${dim.score}</strong><p>${dim.reasons.length ? dim.reasons.map(escape).join('；') : '本维度未触发加减分条件'}</p></div>`).join('')}</div>`;
  }
  function researchDetail(stock) {
    const result = stock.score;
    if (state.detail === 'score') return `<section class="panel">${factors(result.dimensions)}<div class="factor-total"><span>累计分 <strong>${result.total_score}</strong> · ${result.grade} 级</span><span>S ≥ 22 · A ≥ 14 · B ≥ 5 · C &lt; 5</span></div></section><p class="rules-note">策略 ${escape(result.strategy_id)} v${escape(result.strategy_version)} · 规则指纹 ${escape(result.rule_fingerprint)}。分数是确定性规则的累加结果，不代表上涨概率；与完整版的 0–100 知行指数分别计算。</p>`;
    if (state.detail === 'sources') return `<div class="source-grid"><article class="panel"><span>合成样本</span><h3>行情与走势</h3><p>标的、价格、财务字段与日期序列均由固定随机种子生成。展示 ${data.asOf} 的模拟场景，不对应真实证券。</p></article><article class="panel"><span>真实规则计算</span><h3>评分与因子</h3><p>将样本输入项目中的 StrategyEngine，保留七维分数、触发原因、策略版本与规则指纹。</p></article><article class="panel"><span>浏览器本地保存</span><h3>自选与研究快照</h3><p>自选列表和快照保存在当前浏览器中。完整版使用腾讯、东方财富等数据适配器及 SQLite 存储。</p></article></div><p class="rules-note">演示不请求行情服务。样本交易日仅排除周末，不是实际交易所日历。版本 ${data.version}。</p>`;
    const positives = result.dimensions.filter(dim => dim.score > 0).sort((a, b) => b.score - a.score).slice(0, 3);
    const negatives = result.dimensions.filter(dim => dim.score < 0);
    return `<div class="evidence-grid"><section class="panel evidence"><h3>↗ 支撑本次评分的因素</h3>${positives.length ? positives.map(dim => `<p>${escape(dim.label)}贡献 +${dim.score}：${dim.reasons.map(escape).join('；') || '规则条件满足'}。</p>`).join('') : '<p>当前样本没有正向加分项，可先检查估值、资金和趋势条件。</p>'}</section><section class="panel evidence caution"><h3>◇ 需要继续核对</h3>${negatives.slice(0, 2).map(dim => `<p>${escape(dim.label)} ${dim.score}：${dim.reasons.map(escape).join('；')}。</p>`).join('')}<p>${negatives.length ? '结合不同时间窗口确认信号是否持续。' : '当前样本未触发扣分项，仍需结合更长周期和其他资料判断。'}</p><p>样本的评分仅展示规则触发过程，不能据此推断未来表现。</p></section></div>`;
  }
  function filteredStocks() {
    return stocks.filter(stock => (state.pool !== 'watch' || state.watch.has(stock.code))
      && (state.grade === 'all' || stock.score.grade === state.grade)
      && (state.kind === 'all' || stock.kind === state.kind)
      && `${stock.name} ${stock.code} ${stock.sector}`.toLowerCase().includes(state.query.trim().toLowerCase()));
  }
  function poolRows() {
    const rows = filteredStocks();
    return rows.length ? rows.map(stock => `<tr><td>${watchButton(stock, true)}</td><td><button class="stock-link" data-action="open-stock" data-code="${stock.code}"><strong>${stock.name}</strong><small>${stock.code.toUpperCase()}</small></button></td><td>${stock.sector}</td><td>${number(stock.input.price)}</td><td class="${tone(stock.input.change_pct)}">${signed(stock.input.change_pct)}%</td><td>${gradeTag(stock)} <span style="margin-left:9px">${stock.score.total_score}</span></td><td><button class="btn" data-action="open-stock" data-code="${stock.code}" aria-label="研究${stock.name}">查看研究 ↗</button></td></tr>`).join('')
      : '<tr><td colspan="7" class="empty-state">没有匹配的样本。可以调整筛选条件，或在参考池中点击星标加入自选。</td></tr>';
  }
  function poolPage() {
    return heading('02 / RESEARCH UNIVERSE', '从参考池，建立研究范围。', '筛选样本、管理自选，再进入个股研究。')
      + `<div class="pool-summary"><div><span>演示参考池</span><strong>${stocks.length}<small> 个样本</small></strong></div><div><span>股票样本 / ETF 样本</span><strong>6 <small>/</small> 2</strong></div><div><span>我的自选</span><strong>${state.watch.size}<small> 个样本</small></strong></div><div><span>已保存快照</span><strong>${state.snapshots.length}<small> 份研究</small></strong></div></div>
      <section class="panel"><div class="pool-toolbar"><div class="segment"><button data-action="pool" data-pool="all" class="${state.pool === 'all' ? 'active' : ''}" aria-pressed="${state.pool === 'all'}">参考池</button><button data-action="pool" data-pool="watch" class="${state.pool === 'watch' ? 'active' : ''}" aria-pressed="${state.pool === 'watch'}">我的自选</button></div><input id="pool-search" aria-label="筛选名称、代码或行业" placeholder="搜索名称、代码或行业" value="${escape(state.query)}"><label>等级<select id="grade-filter">${['all', 'S', 'A', 'B', 'C'].map(value => `<option value="${value}" ${state.grade === value ? 'selected' : ''}>${value === 'all' ? '全部' : value}</option>`).join('')}</select></label><select id="kind-filter" aria-label="样本类型">${[['all', '全部类型'], ['stock', '股票样本'], ['etf', 'ETF 样本']].map(([value, label]) => `<option value="${value}" ${state.kind === value ? 'selected' : ''}>${label}</option>`).join('')}</select></div><div class="table-wrap"><table class="data-table"><thead><tr><th>自选</th><th>样本名称 / 代码</th><th>行业</th><th>样本价格</th><th>涨跌幅</th><th>等级 / 规则分</th><th>研究</th></tr></thead><tbody id="pool-rows">${poolRows()}</tbody></table></div></section>
      <p class="rules-note">演示包含 8 个虚构样本；完整版支持全市场搜索与可选的 66 只 A 股、11 只 ETF 参考池。S/A/B/C 采用同一份策略阈值，点击个股可查看每一项分数。</p>`;
  }
  function compareChart(selected) {
    const series = selected.map(stock => { const bars = stock.bars.slice(-60); return bars.map(bar => bar.close / bars[0].close * 100); });
    const values = series.flat(), low = Math.min(...values, 100) - 2, high = Math.max(...values, 100) + 2;
    const y = value => 25 + (high - value) / (high - low) * 205;
    const grid = Array.from({ length: 5 }, (_, i) => { const value = high - (high - low) * i / 4; return `<line x1="45" x2="925" y1="${y(value)}" y2="${y(value)}" stroke="#e9eee1"/><text x="36" y="${y(value) + 4}" text-anchor="end" fill="#8f9c82" font-size="11">${number(value)}</text>`; }).join('');
    return `<svg viewBox="0 0 950 275" role="img" aria-label="所选样本的60日归一化合成走势，起点均为100">${grid}<line x1="45" x2="925" y1="${y(100)}" y2="${y(100)}" stroke="#a7b49c" stroke-dasharray="4 5"/>${series.map((values, i) => `<polyline fill="none" stroke="${colors[i]}" stroke-width="2.5" points="${values.map((value, j) => `${45 + j * 880 / 59},${y(value)}`).join(' ')}"/>`).join('')}<text x="45" y="260" fill="#8f9c82" font-size="11">${selected[0].bars.at(-60).date}</text><text x="925" y="260" text-anchor="end" fill="#8f9c82" font-size="11">${data.asOf}</text></svg>`;
  }
  function comparePage() {
    const selected = state.compare.map(findStock);
    return heading('03 / SIDE BY SIDE', '把差异，放在同一尺度。', '选择 2–3 个样本，对照趋势和规则贡献。')
      + `<div class="compare-picks">${stocks.map(stock => `<label><input type="checkbox" data-compare="${stock.code}" ${state.compare.includes(stock.code) ? 'checked' : ''}>${stock.name}</label>`).join('')}</div>`
      + (selected.length < 2 ? `<section class="panel empty-state"><h2>再选一个样本</h2><p>至少选择两个样本后，显示归一化走势和评分比较。</p></section>`
        : `<section class="panel"><div class="panel-head"><h2>60 日相对走势</h2><small>起点 = 100 · 合成数据</small></div><div class="compare-legend">${selected.map((stock, i) => `<span style="--series:${colors[i]}">${stock.name}</span>`).join('')}</div><div class="compare-chart">${compareChart(selected)}</div></section><section class="panel compare-table"><div class="table-wrap"><table class="data-table"><thead><tr><th>指标</th>${selected.map(stock => `<th><button class="stock-link" data-action="open-stock" data-code="${stock.code}"><strong>${stock.name} ↗</strong></button></th>`).join('')}</tr></thead><tbody><tr><td>规则等级 / 累计分</td>${selected.map(stock => `<td>${gradeTag(stock)} <b>${stock.score.total_score}</b></td>`).join('')}</tr><tr><td>60 日区间变化</td>${selected.map(stock => { const value = (stock.bars.at(-1).close / stock.bars.at(-60).close - 1) * 100; return `<td class="${tone(value)}">${signed(value)}%</td>`; }).join('')}</tr>${stocks[0].score.dimensions.map((dim, index) => `<tr><td>${escape(dim.label)}</td>${selected.map(stock => `<td>${stock.score.dimensions[index].score > 0 ? '+' : ''}${stock.score.dimensions[index].score}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`)
      + '<p class="rules-note">走势按每个样本区间首日收盘价归一化；所有比较使用同一日期范围、策略版本和规则指纹。区间变化为合成价格路径的计算结果。</p>';
  }
  function snapshotsPage() {
    const snapshot = state.snapshots.find(item => item.id === state.snapshotId);
    const detail = snapshot ? `<section class="snapshot-detail"><h2>${escape(findStock(snapshot.code).name)} · 已保存的研究</h2><p>${escape(snapshot.note || '未填写研究笔记。')}</p><p>样本价格 ${number(snapshot.price)} · 涨跌幅 ${signed(snapshot.change)}% · ${snapshot.grade} 级 / ${snapshot.total} 分</p><p>保存时间 ${escape(new Date(snapshot.savedAt).toLocaleString('zh-CN'))} · ${escape(snapshot.version)} · 规则 ${escape(snapshot.fingerprint)}</p><section class="panel">${factors(snapshot.dimensions)}</section><button class="btn" style="margin-top:16px" data-action="close-snapshot">收起快照</button></section>` : '';
    return heading('04 / RESEARCH JOURNAL', '留住判断，也留住依据。', '保存当时的分数与笔记，回看每一次研究。', '<a class="btn primary" href="#research">＋ 开始研究</a>')
      + detail + (state.snapshots.length ? `<div class="snapshot-list">${state.snapshots.map(item => `<article class="panel snapshot-card"><div><div class="eyebrow">RESEARCH SNAPSHOT / ${item.grade} · ${item.total} 分</div><h2>${escape(findStock(item.code).name)}</h2><small>${escape(new Date(item.savedAt).toLocaleString('zh-CN'))} · ${item.code.toUpperCase()}</small><p>${escape(item.note || '已记录样本行情与逐项评分。')}</p></div><div class="snapshot-actions"><button class="btn" data-action="open-snapshot" data-id="${escape(item.id)}">回看快照 ↗</button><button class="btn" data-action="open-stock" data-code="${item.code}">继续研究</button></div></article>`).join('')}</div>`
        : '<section class="panel empty-state"><div class="eyebrow">YOUR FIRST RESEARCH NOTE</div><h2>第一份研究，从一个问题开始。</h2><p>进入个股研究，写下需要继续观察的因素，点击“保存研究快照”。</p><a class="btn primary" href="#research">研究一个样本 ↗</a></section>')
      + '<p class="rules-note">快照保存当时的行情摘要、评分明细与研究笔记；同一内容重复保存会复用记录。演示最多保留最近 20 份快照，刷新页面后仍可在当前浏览器中回看。</p>';
  }
  function saveSnapshot() {
    const stock = findStock(state.stock), note = state.note.trim();
    const duplicate = state.snapshots.find(item => item.code === stock.code && item.note === note && item.version === data.version && item.fingerprint === stock.score.rule_fingerprint);
    if (duplicate) { toast('相同研究已保存，可以在研究快照中回看。'); return; }
    const snapshot = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, code: stock.code,
      note, savedAt: new Date().toISOString(), version: data.version, total: stock.score.total_score,
      grade: stock.score.grade, price: stock.input.price, change: stock.input.change_pct,
      fingerprint: stock.score.rule_fingerprint, dimensions: JSON.parse(JSON.stringify(stock.score.dimensions)) };
    state.snapshots.unshift(snapshot); state.snapshots = state.snapshots.slice(0, 20);
    if (persist()) toast('研究快照已保存，可在侧栏“研究快照”中回看。');
  }
  content.addEventListener('click', event => {
    const button = event.target.closest('[data-action]'); if (!button) return;
    const { action, code } = button.dataset;
    if (action === 'open-stock') { state.detail = 'overview'; navigate('research', code); }
    else if (action === 'watch') {
      if (state.watch.has(code)) state.watch.delete(code); else state.watch.add(code);
      const saved = persist(); render();
      if (saved) toast(state.watch.has(code) ? '已加入自选，刷新后仍会保留。' : '已移出自选。');
    } else if (action === 'range') { state.range = Number(button.dataset.range); render(); }
    else if (action === 'detail') {
      state.detail = button.dataset.detail;
      document.querySelectorAll('[data-action="detail"]').forEach(el => {
        if (el.closest('.detail-tabs')) { el.classList.toggle('active', el.dataset.detail === state.detail); el.setAttribute('aria-pressed', el.dataset.detail === state.detail); }
      });
      document.getElementById('research-detail').innerHTML = researchDetail(findStock(state.stock));
      if (button.classList.contains('score-link')) document.querySelector('.detail-tabs').scrollIntoView({ block: 'nearest', behavior: 'instant' });
    } else if (action === 'add-compare') {
      if (!state.compare.includes(code)) {
        if (state.compare.length >= 3) { toast('最多同时对比 3 个样本，请先在股票对比中取消一个。'); return; }
        state.compare.push(code);
      }
      navigate('compare');
    } else if (action === 'pool') { state.pool = button.dataset.pool; render(); }
    else if (action === 'save-snapshot') saveSnapshot();
    else if (action === 'open-snapshot') navigate('snapshots', button.dataset.id);
    else if (action === 'close-snapshot') navigate('snapshots');
  });
  function searchResults() {
    const input = document.getElementById('search-input'), target = document.getElementById('search-results');
    const query = input.value.trim().toLowerCase();
    if (!query) { target.innerHTML = ''; return; }
    const matches = stocks.filter(stock => `${stock.name} ${stock.code} ${stock.sector}`.toLowerCase().includes(query));
    target.innerHTML = matches.length ? matches.map(stock => `<button type="button" data-action="open-stock" data-code="${stock.code}"><span>${stock.name}</span><small>${stock.code.toUpperCase()}</small></button>`).join('') : '<p>没有匹配的演示样本。试试“星河”或“DEMO03”。</p>';
  }
  content.addEventListener('submit', event => {
    if (event.target.id !== 'stock-search') return;
    event.preventDefault();
    const query = document.getElementById('search-input').value.trim().toLowerCase();
    if (!query) { toast('请输入一个演示名称或代码。'); return; }
    const matches = stocks.filter(stock => `${stock.name} ${stock.code} ${stock.sector}`.toLowerCase().includes(query));
    if (matches.length === 1) navigate('research', matches[0].code); else searchResults();
  });
  content.addEventListener('input', event => {
    if (event.target.id === 'research-note') state.note = event.target.value;
    if (event.target.id === 'search-input') searchResults();
    if (event.target.id === 'pool-search') { state.query = event.target.value; document.getElementById('pool-rows').innerHTML = poolRows(); }
  });
  content.addEventListener('change', event => {
    if (event.target.id === 'grade-filter') { state.grade = event.target.value; document.getElementById('pool-rows').innerHTML = poolRows(); }
    if (event.target.id === 'kind-filter') { state.kind = event.target.value; document.getElementById('pool-rows').innerHTML = poolRows(); }
    if (event.target.hasAttribute('data-compare')) {
      const code = event.target.dataset.compare;
      if (event.target.checked && state.compare.length >= 3) { event.target.checked = false; toast('最多同时对比 3 个样本。'); return; }
      state.compare = event.target.checked ? [...state.compare, code] : state.compare.filter(value => value !== code);
      render();
    }
  });
  content.addEventListener('pointermove', event => {
    const barIndex = event.target.dataset.bar;
    if (barIndex == null || state.route !== 'research') return;
    const bar = findStock(state.stock).bars[Number(barIndex)];
    document.getElementById('chart-readout').textContent = `${bar.date} · 开 ${number(bar.open)} 高 ${number(bar.high)} 低 ${number(bar.low)} 收 ${number(bar.close)} · 量 ${bar.volume}（样本单位）`;
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { const results = document.getElementById('search-results'); if (results) results.innerHTML = ''; } });
  document.addEventListener('click', event => { if (!event.target.closest('.search-form')) { const results = document.getElementById('search-results'); if (results) results.innerHTML = ''; } });
  document.getElementById('reset-demo').addEventListener('click', () => {
    if (!window.confirm('恢复初始自选并清空演示研究快照？这只影响当前浏览器中的知行股研演示。')) return;
    state.watch = new Set(defaults); state.snapshots = []; state.note = ''; state.stock = stocks[0].code;
    state.compare = ['demo01', 'demo03']; state.detail = 'overview'; state.range = 60;
    state.query = ''; state.pool = 'all'; state.grade = 'all'; state.kind = 'all';
    const saved = persist(); navigate('research'); if (saved) toast('已恢复初始演示。');
  });
  document.querySelector('.skip-link').addEventListener('click', event => {
    event.preventDefault(); content.focus(); content.scrollIntoView({ block: 'start' });
  });
  window.addEventListener('hashchange', () => {
    readRoute(); window.scrollTo(0, 0); content.focus({ preventScroll: true });
  });
  readRoute();
})();
