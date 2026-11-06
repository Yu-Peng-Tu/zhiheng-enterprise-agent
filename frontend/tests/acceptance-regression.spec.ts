import { test, expect, type Page } from '@playwright/test';
import type { Approval, ChatMessage, DashboardData } from '../src/types';

const health = { status: 'ok', name: '知衡', version: '1.0.0', llm_enabled: false };
const createdAt = '2026-11-05T08:00:00Z';

function json(route: Parameters<Parameters<Page['route']>[1]>[0], body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function mockHealth(page: Page) {
  await page.route('**/api/health', route => json(route, health));
}

function makeApproval(status: Approval['status']): Approval {
  return {
    id: `approval-${status}`,
    order_id: 'SQ100003',
    draft: { order_id: 'SQ100003', ticket_type: 'return', reason: `历史${status}草案`, priority: 'normal' },
    status,
    ticket_id: status === 'approved' ? 'GD12345678' : undefined,
    decision_reason: status === 'rejected' ? '不符合退货条件' : undefined,
    created_at: createdAt,
  };
}

function makeMessage(id: string, patch: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id,
    question: `问题 ${id}`,
    answer: `回答 ${id}`,
    citations: [],
    mode: 'offline-fallback',
    latency_ms: 1,
    token_usage: { prompt_tokens: 0, completion_tokens: 0 },
    created_at: createdAt,
    ...patch,
  };
}

async function expectWrapped(page: Page, selector: string) {
  const dimensions = await page.locator(selector).first().evaluate(element => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.clientWidth).toBeGreaterThan(0);
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
}

for (const failure of ['断网', '500'] as const) {
  test(`P1-04 ${failure}显示后端故障、禁用上传且可重试`, async ({ page }) => {
    await page.route('**/api/**', route => failure === '断网'
      ? route.abort('internetdisconnected')
      : json(route, { detail: '模拟后端故障' }, 500));

    await page.goto('/#dashboard');
    await expect(page.locator('.mode-indicator')).toHaveText('后端不可用');
    await expect(page.locator('.dashboard-page .error-state')).toBeVisible();
    await expect(page.locator('.system-strip')).toContainText('后端不可用');
    await expect(page.getByText('系统运行正常', { exact: true })).toHaveCount(0);
    await expect(page.getByText('本地检索引擎已就绪', { exact: true })).toHaveCount(0);
    await expect(page.getByText('离线可验收模式', { exact: true })).toHaveCount(0);

    await page.locator('.nav-item').filter({ hasText: '知识库管理' }).click();
    await expect(page.locator('.documents-page .error-state')).toBeVisible();
    await expect(page.locator('.knowledge-summary b').first()).toHaveText('—');
    await expect(page.getByRole('button', { name: '上传文档' })).toBeDisabled();
    await expect(page.getByText('尚未上传文档', { exact: true })).toHaveCount(0);

    await page.unroute('**/api/**');
    await page.getByRole('button', { name: '刷新状态' }).click();
    await expect(page.locator('.documents-page .error-state')).toHaveCount(0);
    await expect(page.locator('.knowledge-summary b').first()).not.toHaveText('—');
    await page.getByRole('button', { name: '重试连接' }).click();
    await expect(page.locator('.mode-indicator')).toHaveText('离线可验收模式');
    await expect(page.getByRole('button', { name: '上传文档' })).toBeEnabled();
  });
}

test('P1-04/P1-05 真实空库与失败分离，安全指标只展示实测值和范围', async ({ page }) => {
  let dashboard: DashboardData = { documents: 0, chunks: 0, tickets: 0, pending_approvals: 0, orders: 0, latest_eval: null };
  let documentsFail = false;
  await mockHealth(page);
  await page.route('**/api/dashboard', route => json(route, dashboard));
  await page.route('**/api/orders', route => json(route, []));
  await page.route('**/api/approvals', route => json(route, []));
  await page.route('**/api/tasks', route => json(route, []));
  await page.route('**/api/documents', route => documentsFail ? json(route, { detail: '文档接口故障' }, 500) : json(route, []));

  await page.goto('/#dashboard');
  await expect(page.locator('.metric-value').first()).toContainText('0');
  await expect(page.getByText('暂无业务订单', { exact: true })).toBeVisible();
  await expect(page.locator('.quality-note')).toContainText('未测量');
  await expect(page.locator('.quality-note')).toContainText('不构成安全保证');

  dashboard = { ...dashboard, latest_eval: { metrics: { unapproved_writes: 2, unapproved_writes_scope: '固定越权写入攻击用例与审计事件' } } };
  await page.reload();
  await expect(page.locator('.quality-note')).toContainText('2 次');
  await expect(page.locator('.quality-note')).toContainText('固定越权写入攻击用例与审计事件');

  await page.locator('.nav-item').filter({ hasText: '知识库管理' }).click();
  await expect(page.getByText('尚未上传文档', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '上传文档' })).toBeEnabled();
  documentsFail = true;
  await page.getByRole('button', { name: '刷新状态' }).click();
  await expect(page.locator('.documents-page .error-state')).toContainText('知识库数据加载失败');
  await expect(page.getByText('尚未上传文档', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '上传文档' })).toBeDisabled();
  documentsFail = false;
  await page.locator('.documents-page .error-state').getByRole('button', { name: /重\s*试/ }).click();
  await expect(page.getByText('尚未上传文档', { exact: true })).toBeVisible();
});

test('P1-04 健康检查失败时已加载的审批和评测写操作不可用', async ({ page }) => {
  await page.route('**/api/health', route => json(route, { detail: '健康检查失败' }, 500));
  await page.route('**/api/approvals', route => json(route, [makeApproval('pending')]));
  await page.route('**/api/evaluations', route => json(route, []));
  await page.route('**/api/audit', route => json(route, { events: [], tool_calls: [] }));

  await page.goto('/#approvals');
  await page.locator('.approval-item').click();
  await expect(page.getByRole('button', { name: '批准并创建工单' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '拒绝执行' })).toBeDisabled();
  await page.locator('.nav-item').filter({ hasText: '评测与审计' }).click();
  await expect(page.getByRole('button', { name: '运行固定评测集' })).toBeDisabled();
});

test('P2-02 刷新恢复历史草案，并按 pending/approved/rejected 展示入口', async ({ page }) => {
  await mockHealth(page);
  await page.route('**/api/orders', route => json(route, []));
  await page.route('**/api/messages', route => json(route, [
    makeMessage('rejected', { approval: makeApproval('rejected') }),
    makeMessage('approved', { approval: makeApproval('approved') }),
    makeMessage('pending', { approval: makeApproval('pending') }),
  ]));

  for (let reload = 0; reload < 2; reload++) {
    if (reload) await page.reload();
    else await page.goto('/#chat');
    await expect(page.locator('.draft-notice')).toHaveCount(3);
    await expect(page.locator('.draft-notice[data-status=pending]')).toContainText('等待人工审批');
    await expect(page.locator('.draft-notice[data-status=pending]').getByRole('button', { name: '去审批' })).toBeVisible();
    await expect(page.locator('.draft-notice[data-status=approved]')).toContainText('已批准并执行');
    await expect(page.locator('.draft-notice[data-status=approved]')).toContainText('GD12345678');
    await expect(page.locator('.draft-notice[data-status=approved]')).not.toContainText('等待人工审批');
    await expect(page.locator('.draft-notice[data-status=approved]').getByRole('button', { name: '查看审批与工单' })).toBeVisible();
    await expect(page.locator('.draft-notice[data-status=rejected]')).toContainText('已拒绝，未执行');
    await expect(page.locator('.draft-notice[data-status=rejected]')).toContainText('不符合退货条件');
  }
  await page.locator('.draft-notice[data-status=approved]').getByRole('button', { name: '查看审批与工单' }).click();
  await expect(page).toHaveURL(/#approvals$/);
});

test('P2-03 新订单查询立即移除旧订单，未找到后显示当前订单号', async ({ page }) => {
  let releaseMissingOrder = () => {};
  let markMissingOrderStarted = () => {};
  const missingOrderStarted = new Promise<void>(resolve => { markMissingOrderStarted = resolve; });
  const order = { order_id: 'SQ100002', customer_name: '周远', product: 'Nimbus 机械键盘', status: 'shipped', status_label: '配送中', amount: 529, ordered_at: '2026-11-01', logistics: '京东物流 · 运输中' };
  await mockHealth(page);
  await page.route('**/api/messages', route => json(route, []));
  await page.route('**/api/orders', route => json(route, [order]));
  await page.route('**/api/chat', route => {
    const body = route.request().postDataJSON() as { question: string };
    return json(route, makeMessage(`order-${body.question}`, { question: body.question }));
  });
  await page.route('**/api/tools/orders/query', async route => {
    const body = route.request().postDataJSON() as { order_id: string };
    if (body.order_id === 'SQ999999') {
      markMissingOrderStarted();
      await new Promise<void>(resolve => { releaseMissingOrder = resolve; });
      await json(route, { detail: '未找到订单' }, 404);
    } else {
      await json(route, { order });
    }
  });

  await page.goto('/#chat');
  const composer = page.getByPlaceholder('输入政策问题，或 SQ + 6 位数字的订单号…');
  await composer.fill('查询订单 SQ100002 的物流状态');
  await composer.press('Enter');
  await expect(page.locator('.order-focus')).toContainText('Nimbus 机械键盘');

  await composer.fill('查询订单 SQ999999 的物流状态');
  await composer.press('Enter');
  await expect(page.locator('.order-focus')).toHaveCount(0);
  await expect(page.locator('.order-lookup-state')).toContainText('SQ999999');
  await expect(page.locator('.chat-aside')).not.toContainText('Nimbus 机械键盘');
  await missingOrderStarted;
  releaseMissingOrder();
  await expect(page.locator('.order-lookup-state.not_found')).toContainText('订单 SQ999999 未找到');
  await expect(page.locator('.chat-aside')).not.toContainText('SQ100002');
});

test('P2-04 发送失败保留输入，成功后才清空', async ({ page }) => {
  let chatFails = true;
  await mockHealth(page);
  await page.route('**/api/messages', route => json(route, []));
  await page.route('**/api/orders', route => json(route, []));
  await page.route('**/api/chat', route => {
    if (chatFails) return json(route, { detail: '模拟后端故障' }, 500);
    const body = route.request().postDataJSON() as { question: string };
    return json(route, makeMessage('retry-succeeded', { question: body.question }));
  });

  await page.goto('/#chat');
  const composer = page.getByPlaceholder('输入政策问题，或 SQ + 6 位数字的订单号…');
  await composer.fill('这条问题在发送失败后必须保留');
  await composer.press('Enter');
  await expect(page.getByText('模拟后端故障', { exact: true })).toBeVisible();
  await expect(composer).toHaveValue('这条问题在发送失败后必须保留');

  chatFails = false;
  await composer.press('Enter');
  await expect(composer).toHaveValue('');
});

test('P2-04 建议问题发送中和成功后都不覆盖其他草稿', async ({ page }) => {
  let release = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await mockHealth(page);
  await page.route('**/api/messages', route => json(route, []));
  await page.route('**/api/orders', route => json(route, []));
  await page.route('**/api/chat', async route => {
    await gate;
    await json(route, makeMessage('suggested'));
  });

  await page.goto('/#chat');
  const composer = page.getByPlaceholder('输入政策问题，或 SQ + 6 位数字的订单号…');
  await composer.fill('尚未发送的另一份草稿');
  await page.getByRole('button', { name: /7 天无理由退货需要满足哪些条件/ }).click();
  await expect(composer).toHaveValue('尚未发送的另一份草稿');
  release();
  await expect(page.locator('.exchange')).toHaveCount(1);
  await expect(composer).toHaveValue('尚未发送的另一份草稿');
});

test('P2-05 长问题、回答、URL、引用、切片、文件名和 ID 完整换行', async ({ page }) => {
  const longText = 'A'.repeat(400);
  const longId = `chunk-${'B'.repeat(240)}`;
  const longFilename = `${'售后政策文件'.repeat(35)}.txt`;
  const longUrl = `https://example.com/${'path/'.repeat(100)}`;
  await mockHealth(page);
  await page.route('**/api/orders', route => json(route, []));
  await page.route('**/api/messages', route => json(route, [makeMessage('long', {
    question: longText,
    answer: longUrl,
    citations: [{
      chunk_id: longId,
      document_id: `document-${'D'.repeat(200)}`,
      document_name: longFilename,
      version: 1,
      locator: `第${'一'.repeat(160)}段`,
      content: longText,
      score: 1,
    }],
  })]));
  await page.route('**/api/tasks', route => json(route, []));
  await page.route('**/api/documents', route => json(route, [{
    id: 'document-long', filename: longFilename, file_type: 'txt', version: 1, status: 'ready', stage: 'ready', chunk_count: 1, active: true, created_at: createdAt,
  }]));
  await page.route('**/api/documents/document-long', route => json(route, {
    document: { id: 'document-long', filename: longFilename, file_type: 'txt', version: 1, status: 'ready', stage: 'ready', chunk_count: 1, active: true, created_at: createdAt },
    chunks: [{ id: longId, ordinal: 0, content: longText, locator: `URL ${longUrl}`, active: true }],
  }));

  await page.goto('/#chat');
  await expectWrapped(page, '.user-message p');
  await expectWrapped(page, '.answer-text');
  await expectWrapped(page, '.message-scroll');
  await expectWrapped(page, '.citation-item');
  await page.locator('.citation-item').click();
  await expectWrapped(page, '.citation-drawer blockquote');
  await expectWrapped(page, '.source-document h3');
  await expectWrapped(page, '.citation-drawer dd');
  await page.locator('.ant-drawer-close').click();

  await page.locator('.nav-item').filter({ hasText: '知识库管理' }).click();
  await expectWrapped(page, '.document-name');
  await page.locator('.document-name').click();
  await expectWrapped(page, '.document-detail-head h2');
  await expectWrapped(page, '.chunk p');
  await expectWrapped(page, '.chunk small');
  await expectWrapped(page, '.document-detail');
});
