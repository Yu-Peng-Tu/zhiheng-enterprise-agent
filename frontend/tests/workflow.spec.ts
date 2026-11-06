import { test, expect } from '@playwright/test';

test('知识、订单、审批、报告、文档与评测完整业务闭环', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '把企业知识，转化为可控行动' })).toBeVisible();
  await expect(page.locator('.metric-value').first()).toContainText('3');
  await page.screenshot({ path: 'artifacts/dashboard.png', fullPage: true });

  await page.locator('.nav-item').filter({ hasText: '知识与业务问答' }).click();
  await page.getByRole('button', { name: /7 天无理由退货需要满足哪些条件/ }).click();
  await expect(page.locator('.answer-text').last()).toContainText('七天无理由退货');
  await page.locator('.citation-item').first().click();
  await expect(page.getByText('引用原文核验')).toBeVisible();
  await expect(page.locator('.citation-drawer blockquote')).toContainText('自订单签收次日起七日内');
  await page.locator('.ant-drawer-close').click();

  const composer = page.getByPlaceholder('输入政策问题，或 SQ + 6 位数字的订单号…');
  await composer.fill('我们的售后政策支持永久退款吗？');
  await composer.press('Enter');
  await expect(page.locator('.insufficient').last()).toContainText('没有足够依据');

  await composer.fill('订单 SQ100001 想申请退货，请创建工单');
  await composer.press('Enter');
  await expect(page.locator('.draft-notice').last()).toContainText('尚未执行');
  await page.screenshot({ path: 'artifacts/chat-evidence.png', fullPage: true });
  await page.locator('.draft-notice').last().getByRole('button', { name: '去审批' }).click();

  await page.locator('.approval-item').filter({ hasText: 'SQ100001' }).first().click();
  await expect(page.getByRole('heading', { name: '工单参数核验' })).toBeVisible();
  await page.locator('.reason-field textarea').fill('客户申请七天无理由退货，已核对商品完好，等待仓库验收。');
  await expect(page.locator('.changed-note')).toContainText('重新进行');
  await page.getByRole('button', { name: '批准并创建工单' }).click();
  await page.getByRole('button', { name: '确认创建工单' }).click();
  await expect(page.locator('.execution-warning')).toContainText(/GD[0-9A-F]{8}/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.screenshot({ path: 'artifacts/approval-approved.png', fullPage: true });
  await page.getByRole('button', { name: '生成处理报告' }).click();
  await expect(page.locator('.report-editor')).toHaveValue(/售后处理报告/);
  await expect(page.locator('.report-editor')).toHaveValue(/SQ100001/);
  await page.locator('.ant-drawer-close').click();

  await page.locator('.nav-item').filter({ hasText: '知识库管理' }).click();
  await page.locator('input[type=file]').setInputFiles({
    name: 'enterprise-service-rule.txt', mimeType: 'text/plain',
    buffer: Buffer.from('企业服务补充规则\n\n客户申请发票补开时，客服应核对订单编号与开票抬头，再创建人工处理工单。'),
  });
  await expect(page.getByText('enterprise-service-rule.txt').first()).toBeVisible();
  await expect(page.locator('.ant-table-row').filter({ hasText: 'enterprise-service-rule.txt' })).toContainText('可检索');
  await page.getByRole('button', { name: 'enterprise-service-rule.txt' }).click();
  await expect(page.locator('.document-detail')).toContainText('客户申请发票补开时');
  await page.locator('.ant-drawer-close').click();

  await page.locator('.nav-item').filter({ hasText: '评测与审计' }).click();
  await page.getByRole('button', { name: '运行固定评测集' }).click();
  await expect(page.locator('.eval-results')).toContainText('逐用例结果');
  await expect(page.locator('.pass-score')).toContainText('100');
  await page.getByRole('tab', { name: /审计与工具记录/ }).click();
  await expect(page.locator('.audit-section')).toContainText('approved_and_executed');
  await page.getByRole('tab', { name: /工具调用/ }).click();
  await expect(page.locator('.audit-section')).toContainText('tickets.create');
  expect(errors).toEqual([]);
});
