import type { ReactNode } from 'react';
import { Alert, Button, Tag } from 'antd';
import { CheckCircleFilled, ClockCircleFilled, CloseCircleFilled, MinusCircleFilled } from '@ant-design/icons';

export type LoadStatus = 'loading' | 'loaded' | 'error';

const statusMap: Record<string, { label: string; tone: string }> = {
  ready: { label: '可检索', tone: 'success' }, succeeded: { label: '已完成', tone: 'success' }, completed: { label: '已完成', tone: 'success' },
  approved: { label: '已批准', tone: 'success' }, active: { label: '运行中', tone: 'success' },
  pending: { label: '待处理', tone: 'warning' }, processing: { label: '处理中', tone: 'processing' }, queued: { label: '排队中', tone: 'processing' },
  failed: { label: '失败', tone: 'error' }, rejected: { label: '已拒绝', tone: 'error' },
  deleted: { label: '已停用', tone: 'neutral' }, not_found: { label: '未找到', tone: 'warning' },
  shipped: { label: '配送中', tone: 'processing' }, delivered: { label: '已签收', tone: 'success' }, cancelled: { label: '已取消', tone: 'neutral' },
};
export function Status({ value, label }: { value: string; label?: string }) {
  const item = statusMap[value] || { label: value, tone: 'neutral' };
  const icon = item.tone === 'success' ? <CheckCircleFilled /> : item.tone === 'error' ? <CloseCircleFilled /> : item.tone === 'warning' ? <ClockCircleFilled /> : item.tone === 'processing' ? <ClockCircleFilled /> : <MinusCircleFilled />;
  return <Tag className={`status-tag status-${item.tone}`} icon={icon}>{label || item.label}</Tag>;
}
export function PageTitle({ eyebrow, title, description, extra }: { eyebrow?: string; title: string; description: string; extra?: ReactNode }) {
  return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{extra && <div className="page-actions">{extra}</div>}</div>;
}
export function SectionTitle({ title, description, extra }: { title: string; description?: string; extra?: ReactNode }) {
  return <div className="section-title"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{extra}</div>;
}
export function EmptyLine({ text }: { text: string }) { return <div className="empty-line">{text}</div>; }
export function LoadingLine({ text = '正在加载数据…' }: { text?: string }) { return <div className="loading-line" role="status">{text}</div>; }
export function ErrorState({ title = '后端不可用，数据加载失败', description, onRetry, retrying = false }: { title?: string; description?: string; onRetry: () => void; retrying?: boolean }) {
  return <Alert className="error-state" type="error" showIcon={false} message={title} description={description} action={<Button size="small" onClick={onRetry} loading={retrying}>重试</Button>}/>;
}
export const ticketTypes: Record<string,string> = { refund: '退款', return: '退货', exchange: '换货', logistics: '物流异常', other: '其他' };
export const priorities: Record<string,string> = { low: '低', normal: '普通', high: '高', urgent: '紧急' };
export const modeNames: Record<string,string> = { 'deterministic-tool': '业务工具', 'offline-grounded': '本地依据生成', 'offline-fallback': '本地降级生成', 'openai-compatible': '在线模型' };
