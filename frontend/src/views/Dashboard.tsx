import { useCallback, useEffect, useState } from 'react';
import { Button, Table } from 'antd';
import { ArrowRightOutlined, FileTextOutlined, MessageOutlined, SafetyCertificateOutlined, CheckOutlined, DatabaseOutlined } from '@ant-design/icons';
import { api, formatTime } from '../api';
import type { Approval, DashboardData, Order, TaskItem } from '../types';
import { PageTitle, SectionTitle, Status, EmptyLine, ErrorState, LoadingLine, type LoadStatus } from '../components';
import type { ViewKey } from '../App';

export default function Dashboard({navigate,healthStatus}:{navigate:(key:ViewKey)=>void;healthStatus:LoadStatus}) {
  const [data,setData]=useState<DashboardData>();
  const [orders,setOrders]=useState<Order[]>([]);
  const [approvals,setApprovals]=useState<Approval[]>([]);
  const [tasks,setTasks]=useState<TaskItem[]>([]);
  const [status,setStatus]=useState<LoadStatus>('loading');
  const [error,setError]=useState('');
  const load=useCallback(async()=>{
    setStatus('loading');
    try{
      const [d,o,a,t]=await Promise.all([api<DashboardData>('/dashboard'),api<Order[]>('/orders'),api<Approval[]>('/approvals'),api<TaskItem[]>('/tasks')]);
      setData(d);setOrders(o);setApprovals(a);setTasks(t);setStatus('loaded');setError('');
    }catch(cause){
      setData(undefined);setOrders([]);setApprovals([]);setTasks([]);setStatus('error');
      setError(cause instanceof Error?cause.message:'运营数据加载失败');
    }
  },[]);
  useEffect(()=>{void load();},[load]);
  const loaded=status==='loaded';
  const stats=[
    {label:'有效知识文档',value:loaded?data?.documents??0:'—',unit:'份',note:loaded?`${data?.chunks??0} 个可检索切片`:'等待运营数据',icon:<FileTextOutlined/>},
    {label:'待审批操作',value:loaded?data?.pending_approvals??0:'—',unit:'项',note:'批准前不产生业务写入',icon:<SafetyCertificateOutlined/>},
    {label:'模拟业务订单',value:loaded?data?.orders??0:'—',unit:'笔',note:'订单查询为只读工具',icon:<DatabaseOutlined/>},
    {label:'已创建工单',value:loaded?data?.tickets??0:'—',unit:'张',note:'全流程保留执行记录',icon:<CheckOutlined/>},
  ];
  const latest=tasks.slice(0,4);
  const metrics=data?.latest_eval?.metrics;
  const unapprovedWrites=metrics?.unapproved_writes;
  const systemReady=loaded&&healthStatus==='loaded';
  const systemError=status==='error'||healthStatus==='error';
  const emptyText=(text:string)=>status==='loading'?<LoadingLine/>:status==='error'?<EmptyLine text="数据加载失败，请重试"/>:<EmptyLine text={text}/>;
  return <div className="page dashboard-page">
    <PageTitle eyebrow="OPERATIONS / 运营总览" title="把企业知识，转化为可控行动" description="从制度依据到订单处理，在一条可追踪的工作流中完成查询、决策与执行。" extra={<Button type="primary" icon={<MessageOutlined/>} onClick={()=>navigate('chat')}>开始一次问答</Button>}/>
    {status==='error'&&<ErrorState title="运营数据加载失败" description={`后端不可用或返回异常，当前数字不代表真实业务状态。${error}`} onRetry={load}/>}
    <div className={`system-strip ${systemError?'error':systemReady?'ready':'loading'}`}>
      <span><i className="pulse-dot"/>{systemReady?'系统运行正常':systemError?'后端不可用':'正在核验系统状态'}</span>
      <span>{systemReady?'本地检索引擎已就绪':systemError?'运营数据加载失败':'正在加载运营数据'}</span>
      <span>{systemError?'写操作已暂停':'写操作保护已开启'}</span><span className="strip-right">演示环境 · 电商售后</span>
    </div>
    <section className="metrics-grid">{stats.map(s=><div className="metric" key={s.label}><div className="metric-label">{s.label}<span>{s.icon}</span></div><div className="metric-value">{s.value}<small>{s.unit}</small></div><p>{s.note}</p></div>)}</section>
    <div className="dashboard-grid">
      <section className="surface orders-section">
        <SectionTitle title="最近业务订单" description="可直接在问答中输入订单号，查询最新状态。" extra={<Button type="link" onClick={()=>navigate('chat')}>进入问答 <ArrowRightOutlined/></Button>}/>
        <Table rowKey="order_id" pagination={false} size="middle" dataSource={loaded?orders.slice(0,5):[]} locale={{emptyText:emptyText('暂无业务订单')}} columns={[
          {title:'订单号',dataIndex:'order_id',render:v=><span className="mono strong">{v}</span>},
          {title:'商品',dataIndex:'product',ellipsis:true},
          {title:'金额',dataIndex:'amount',align:'right',render:v=><span className="mono">¥{v.toLocaleString()}</span>},
          {title:'状态',dataIndex:'status',render:v=><Status value={v}/>},
          {title:'下单日期',dataIndex:'ordered_at',render:v=><span className="muted mono">{v}</span>},
        ]}/>
      </section>
      <section className="surface workflow-section">
        <SectionTitle title="受控工作流" description="AI 提供建议，最终决定权留给人。"/>
        <div className="workflow-list">
          {[['01','检索依据','只读取当前有效的文档版本'],['02','核验回答','原文引用可展开逐条检查'],['03','人工审批','支持修改参数或拒绝执行'],['04','留痕执行','幂等写入并保存完整审计']].map(([n,t,d],i)=><div className="workflow-step" key={n}><span className="step-num">{n}</span><div><b>{t}</b><p>{d}</p></div>{i<3&&<span className="step-line"/>}</div>)}
        </div>
        <div className="quality-note"><SafetyCertificateOutlined/><span>最近一次评测 · 未经审批写入<strong>{typeof unapprovedWrites==='number'?`${unapprovedWrites} 次`:'未测量'}</strong><small>{typeof unapprovedWrites==='number'?metrics?.unapproved_writes_scope||'测量范围未提供':'尚无可用评测指标，不构成安全保证'}</small></span></div>
      </section>
    </div>
    <div className="dashboard-grid lower-grid">
      <section className="surface task-section"><SectionTitle title="任务动态" description="文档索引与处理状态持续可见。" extra={<Button type="link" onClick={()=>navigate('documents')}>管理知识库 <ArrowRightOutlined/></Button>}/>{status!=='loaded'?emptyText('尚无任务记录'):latest.length?latest.map(t=><div className="activity-row" key={t.id}><div><b>文档索引任务</b><span className="mono">{t.entity_id.slice(0,8)}</span></div><Status value={t.status}/><span className="muted">{formatTime(t.updated_at)}</span></div>):<EmptyLine text="尚无任务记录"/>}</section>
      <section className="surface approval-section"><SectionTitle title="审批队列" description="先检查业务参数，再决定是否执行。" extra={<Button type="link" onClick={()=>navigate('approvals')}>全部审批 <ArrowRightOutlined/></Button>}/>{status!=='loaded'?emptyText('当前没有待审批操作'):approvals.length?approvals.slice(0,3).map(a=><div className="activity-row" key={a.id}><div><b>{a.order_id} · {a.draft.reason}</b><span>{a.draft.ticket_type} / {a.draft.priority}</span></div><Status value={a.status}/></div>):<EmptyLine text="当前没有待审批操作"/>}</section>
    </div>
  </div>;
}
