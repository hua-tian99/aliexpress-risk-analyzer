/**
 * 速卖通风险分析 — 前端交互
 */
(function() {
    'use strict';

    // ===== 状态 =====
    let currentPage = 1;
    const PAGE_SIZE = 50;

    // ===== DOM 引用 =====
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const fileInput = $('#fileInput');
    const uploadArea = $('#uploadArea');
    const uploadPreview = $('#uploadPreview');
    const fileName = $('#fileName');
    const fileCount = $('#fileCount');
    const step2Section = $('#step2-section');
    const step3Section = $('#step3-section');
    const step4Section = $('#step4-section');
    const progressBar = $('#progressBar');
    const progressText = $('#progressText');
    const startBtn = $('#startAnalysisBtn');
    const exportBtn = $('#exportBtn');
    const riskFilter = $('#riskFilter');
    const resultBody = $('#resultBody');
    const prevPageBtn = $('#prevPageBtn');
    const nextPageBtn = $('#nextPageBtn');
    const pageInfo = $('#pageInfo');
    const detailModal = $('#detailModal');
    const detailBody = $('#detailBody');
    const detailTitle = $('#detailTitle');
    const detailCloseBtn = $('#detailCloseBtn');
    const ruleIndexContent = $('#ruleIndexContent');

    // ===== 文件上传 =====
    uploadArea.addEventListener('click', () => fileInput.click());

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            handleFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFile(fileInput.files[0]);
        }
    });

    $('#changeFileBtn').addEventListener('click', () => {
        fileInput.click();
    });

    function handleFile(file) {
        if (!file.name.match(/\.xlsx?$/i)) {
            alert('仅支持 .xlsx / .xls 格式');
            return;
        }

        uploadArea.style.display = 'none';
        uploadPreview.style.display = 'flex';
        fileName.textContent = file.name;
        fileCount.textContent = '上传中...';

        const formData = new FormData();
        formData.append('file', file);

        fetch('/api/upload', { method: 'POST', body: formData })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    fileCount.textContent = `共 ${data.total_rows} 行 · ${data.columns.length} 列`;
                    step2Section.style.display = 'block';
                    step2Section.scrollIntoView({ behavior: 'smooth' });
                    updateStep(1);
                } else {
                    alert('上传失败: ' + data.error);
                    resetUpload();
                }
            })
            .catch(err => {
                alert('上传失败: ' + err.message);
                resetUpload();
            });
    }

    function resetUpload() {
        uploadArea.style.display = 'block';
        uploadPreview.style.display = 'none';
        fileInput.value = '';
    }

    // ===== 步骤 =====
    function updateStep(activeStep) {
        $$('.step').forEach(s => {
            const stepNum = parseInt(s.dataset.step);
            s.classList.toggle('active', stepNum === activeStep);
            s.classList.toggle('done', stepNum < activeStep);
        });
    }

    // ===== 检测器卡片 =====
    $$('.detector-card').forEach(card => {
        card.addEventListener('click', () => {
            card.classList.toggle('selected');
            const cb = card.querySelector('input[type="checkbox"]');
            cb.checked = card.classList.contains('selected');
        });
    });

    // ===== 开始分析 =====
    startBtn.addEventListener('click', () => {
        const selected = [];
        $$('.detector-card.selected').forEach(card => {
            selected.push(card.dataset.key);
        });

        if (selected.length === 0) {
            alert('请至少选择一个检测维度');
            return;
        }

        step3Section.style.display = 'block';
        step3Section.scrollIntoView({ behavior: 'smooth' });
        updateStep(3);
        progressBar.style.width = '10%';
        progressText.textContent = '正在分析...请稍候（图片分析可能需要较长时间）';

        fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ detectors: selected }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    progressBar.style.width = '100%';
                    progressText.textContent = '分析完成！';
                    showResults(data.stats);
                } else {
                    progressText.textContent = '分析失败: ' + data.error;
                    alert('分析失败: ' + data.error);
                }
            })
            .catch(err => {
                progressText.textContent = '分析出错: ' + err.message;
                alert('分析出错: ' + err.message);
            });
    });

    // ===== 显示结果 =====
    function showResults(stats) {
        step4Section.style.display = 'block';
        step4Section.scrollIntoView({ behavior: 'smooth' });
        updateStep(4);

        // 更新统计
        $('#statTotal').textContent = stats.total || 0;
        $('#statHigh').textContent = stats.high || 0;
        $('#statMedium').textContent = stats.medium || 0;
        $('#statLow').textContent = stats.low || 0;

        // 违规类别统计
        if (stats.category_counts && Object.keys(stats.category_counts).length > 0) {
            const categoryStats = $('#categoryStats');
            categoryStats.style.display = 'block';
            const chips = $('#categoryChips');
            chips.innerHTML = '';
            Object.entries(stats.category_counts).slice(0, 15).forEach(([cat, count]) => {
                const chip = document.createElement('span');
                chip.className = 'category-chip';
                chip.textContent = `${cat}: ${count}`;
                chips.appendChild(chip);
            });
        }

        // 加载产品列表
        currentPage = 1;
        loadProducts();

        // 加载规则索引
        loadRuleIndex();
    }

    // ===== 加载产品列表 =====
    function loadProducts() {
        const risk = riskFilter.value;
        resultBody.innerHTML = '<tr><td colspan="7" class="empty-row">加载中...</td></tr>';

        fetch(`/api/products?risk=${encodeURIComponent(risk)}&page=${currentPage}&page_size=${PAGE_SIZE}`)
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    resultBody.innerHTML = `<tr><td colspan="7" class="empty-row">加载失败: ${data.error}</td></tr>`;
                    return;
                }

                if (data.products.length === 0) {
                    resultBody.innerHTML = '<tr><td colspan="7" class="empty-row">暂无匹配产品</td></tr>';
                    return;
                }

                let html = '';
                data.products.forEach(p => {
                    const riskClass = p.risk.includes('高') ? 'high' : p.risk.includes('中') ? 'medium' : 'low';
                    const cats = (p.categories || []).slice(0, 3).join(', ');
                    const imgHtml = p.image
                        ? `<img class="product-thumb" src="${escapeHtml(p.image)}" alt="" onerror="this.style.display='none'">`
                        : '—';

                    html += `<tr>
                        <td>${escapeHtml(p.product_id)}</td>
                        <td title="${escapeHtml(p.name)}">${escapeHtml(p.name).substring(0, 60)}${p.name.length > 60 ? '...' : ''}</td>
                        <td>${imgHtml}</td>
                        <td>${escapeHtml(p.shop_name)}</td>
                        <td><span class="risk-badge ${riskClass}">${escapeHtml(p.risk)}</span></td>
                        <td>${escapeHtml(cats)}</td>
                        <td><button class="btn btn-sm btn-outline" onclick="showDetail(${p.index})">详情</button></td>
                    </tr>`;
                });

                resultBody.innerHTML = html;

                // 分页
                prevPageBtn.disabled = currentPage <= 1;
                nextPageBtn.disabled = currentPage >= data.total_pages;
                pageInfo.textContent = `第 ${currentPage} 页 / 共 ${data.total_pages} 页 (${data.total} 条)`;
            })
            .catch(err => {
                resultBody.innerHTML = `<tr><td colspan="7" class="empty-row">加载失败: ${err.message}</td></tr>`;
            });
    }

    // ===== 筛选 & 分页 =====
    riskFilter.addEventListener('change', () => {
        currentPage = 1;
        loadProducts();
    });

    prevPageBtn.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            loadProducts();
        }
    });

    nextPageBtn.addEventListener('click', () => {
        currentPage++;
        loadProducts();
    });

    // ===== 导出 =====
    exportBtn.addEventListener('click', () => {
        window.location.href = '/api/export';
    });

    // ===== 产品详情 =====
    window.showDetail = function(productIndex) {
        detailModal.style.display = 'flex';
        detailBody.innerHTML = '<div class="detail-loading">加载中...</div>';

        fetch(`/api/product/${productIndex}`)
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    detailBody.innerHTML = `<p>加载失败: ${data.error}</p>`;
                    return;
                }

                const p = data.product;
                let html = '';

                // 产品基本信息
                html += `<div class="detail-section">
                    <h3>📋 产品信息</h3>
                    <dl class="detail-info-grid">
                        <dt>产品ID</dt><dd>${escapeHtml(p.product_id)}</dd>
                        <dt>产品名称</dt><dd>${escapeHtml(p.name)}</dd>
                        <dt>店铺</dt><dd>${escapeHtml(p.shop)}</dd>
                        <dt>产品分组</dt><dd>${escapeHtml(p.category)}</dd>
                    </dl>
                </div>`;

                // 产品图片
                if (p.images && p.images.length > 0) {
                    html += `<div class="detail-section">
                        <h3>🖼️ 产品图片 (${p.images.length}张)</h3>
                        <div class="product-images">`;
                    p.images.forEach(url => {
                        html += `<img src="${escapeHtml(url)}" alt="" onerror="this.style.display='none'">`;
                    });
                    html += `</div></div>`;
                }

                // 风险等级
                const riskClass = data.risk_level.includes('高') ? 'high' : data.risk_level.includes('中') ? 'medium' : 'low';
                html += `<div class="detail-section">
                    <h3>⚠️ 风险评级</h3>
                    <p><span class="risk-badge ${riskClass}">${escapeHtml(data.risk_level)}</span></p>
                    <p>共发现 <strong>${data.total_findings}</strong> 项违规</p>
                </div>`;

                // 检测结果详情
                if (data.details && data.details.length > 0) {
                    html += `<div class="detail-section"><h3>🔍 违规详情</h3>`;

                    data.details.forEach(d => {
                        const symbol = d.risk_level === '高' ? '🔴' : d.risk_level === '中' ? '🟡' : '🟢';
                        html += `<div class="risk-item risk-${d.risk_level}">
                            <div class="risk-header">
                                ${symbol} <strong>[${escapeHtml(d.category)}]</strong>
                                ${escapeHtml(d.reason)}
                            </div>
                            <div class="risk-meta">
                                规则文件: <code>${escapeHtml(d.rule_wiki_link)}</code>
                                ${d.rule_clause ? ' — ' + escapeHtml(d.rule_clause) : ''}
                            </div>`;

                        if (d.rule_summary) {
                            html += `<div class="risk-rule-summary">📖 ${escapeHtml(d.rule_summary)}</div>`;
                        }

                        html += `<div class="risk-remedy"><strong>补救措施:</strong> ${escapeHtml(d.remedy)}</div>`;

                        // 图片相关
                        if (d.image_url) {
                            html += `<div class="risk-remedy" style="margin-top:6px;">
                                <strong>关联图片:</strong>
                                <img src="${escapeHtml(d.image_url)}" style="max-width:200px;max-height:200px;display:block;margin-top:4px;" onerror="this.style.display='none'">
                            </div>`;
                        }

                        // OCR文字
                        if (d.ocr_text) {
                            html += `<div class="risk-remedy" style="margin-top:6px;">
                                <strong>OCR识别文字:</strong>
                                <pre style="font-size:11px;background:#f5f5f5;padding:8px;border-radius:4px;overflow-x:auto;">${escapeHtml(d.ocr_text.substring(0, 500))}</pre>
                            </div>`;
                        }

                        // HTML片段
                        if (d.html_fragment) {
                            html += `<div class="risk-remedy" style="margin-top:6px;">
                                <strong>HTML片段:</strong>
                                <pre style="font-size:11px;background:#f5f5f5;padding:8px;border-radius:4px;overflow-x:auto;">${escapeHtml(d.html_fragment)}</pre>
                            </div>`;
                        }

                        html += `</div>`;
                    });

                    html += `</div>`;
                }

                // 高风险原因 & 补救措施
                if (data.high_risk_reasons) {
                    html += `<div class="detail-section">
                        <h3>🔴 高风险原因</h3>
                        <pre style="white-space:pre-wrap;font-size:13px;background:#fff0f0;padding:12px;border-radius:6px;">${escapeHtml(data.high_risk_reasons)}</pre>
                    </div>`;
                }
                if (data.high_risk_remedies) {
                    html += `<div class="detail-section">
                        <h3>🔴 高风险补救措施</h3>
                        <pre style="white-space:pre-wrap;font-size:13px;background:#fff0f0;padding:12px;border-radius:6px;">${escapeHtml(data.high_risk_remedies)}</pre>
                    </div>`;
                }

                // 中风险原因 & 补救措施
                if (data.medium_risk_reasons) {
                    html += `<div class="detail-section">
                        <h3>🟡 中风险原因</h3>
                        <pre style="white-space:pre-wrap;font-size:13px;background:#fffdf0;padding:12px;border-radius:6px;">${escapeHtml(data.medium_risk_reasons)}</pre>
                    </div>`;
                }
                if (data.medium_risk_remedies) {
                    html += `<div class="detail-section">
                        <h3>🟡 中风险补救措施</h3>
                        <pre style="white-space:pre-wrap;font-size:13px;background:#fffdf0;padding:12px;border-radius:6px;">${escapeHtml(data.medium_risk_remedies)}</pre>
                    </div>`;
                }

                // 所有原因（文本格式 — 保留兼容）
                if (data.reasons_text && !data.high_risk_reasons && !data.medium_risk_reasons) {
                    html += `<div class="detail-section">
                        <h3>📄 原因全文</h3>
                        <pre style="white-space:pre-wrap;font-size:13px;background:#f9f9f9;padding:12px;border-radius:6px;">${escapeHtml(data.reasons_text)}</pre>
                    </div>`;
                }

                // 所有补救措施（保留兼容）
                if (data.remedies_text && !data.high_risk_remedies && !data.medium_risk_remedies) {
                    html += `<div class="detail-section">
                        <h3>🛠️ 补救措施汇总</h3>
                        <pre style="white-space:pre-wrap;font-size:13px;background:#f9f9f9;padding:12px;border-radius:6px;">${escapeHtml(data.remedies_text)}</pre>
                    </div>`;
                }

                detailTitle.textContent = `产品详情 - ${escapeHtml(p.product_id)}`;
                detailBody.innerHTML = html;
            })
            .catch(err => {
                detailBody.innerHTML = `<p>加载失败: ${err.message}</p>`;
            });
    };

    // ===== 关闭弹窗 =====
    detailCloseBtn.addEventListener('click', () => {
        detailModal.style.display = 'none';
    });

    detailModal.addEventListener('click', (e) => {
        if (e.target === detailModal) {
            detailModal.style.display = 'none';
        }
    });

    // ===== 加载规则索引 =====
    function loadRuleIndex() {
        fetch('/api/rules')
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    let html = '';
                    data.rules.forEach(r => {
                        html += `<div class="rule-index-item">
                            <strong>${escapeHtml(r.wiki_link)}</strong>
                            ${r.summary ? ' — ' + escapeHtml(r.summary) : ''}
                            <span style="color:#888;font-size:11px;">(${r.clause_count} 个条款)</span>
                        </div>`;
                    });
                    ruleIndexContent.innerHTML = html;
                }
            })
            .catch(() => {
                ruleIndexContent.innerHTML = '<p>加载失败</p>';
            });
    }

    // ===== 工具 =====
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

})();
