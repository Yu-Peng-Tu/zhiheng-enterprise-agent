import { useCallback, useEffect, useState } from 'react';
import { App, Button, Table, Tabs, Tag } from 'antd';
import { CheckCircleFilled, ReloadOutlined } from '@ant-design/icons';
import { api, formatTime } from '../api';
import type { AuditData, EvalResult, EvalRun } from '../types';
import { PageTitle, SectionTitle, Status, EmptyLine, ErrorState, LoadingLine, type LoadStatus } from '../components';

export default function Evaluation({backendAvailable}:{backendAvailable:boolean}){
  const {message}=App.useApp();
  const [runs,setRuns]=useState<EvalRun[]>([]);
  const [current,setCurrent]=useState<EvalRun>();
  const [audit,setAudit]=useState<AuditData>();
  const [running,setRunning]=useState(false);
  const [status,setStatus]=useState<LoadStatus>('loading');
  const [error,setError]=useState('');
  const [tab,setTab]=useState('evaluation');
  const [auditTab,setAuditTab]=useState('events');
  const load=useCallback(async()=>{
    setStatus(currentStatus=>currentStatus==='loaded'?'loaded':'loading');
    try{
      const [evaluationData,auditData]=await Promise.all([api<EvalRun[]>('/evaluations'),api<AuditData>('/audit')]);
      setRuns(evaluationData);setCurrent(currentRun=>evaluationData.length?currentRun?evaluationData.find(r=>r.id===currentRun.id)||evaluationData[0]:evaluationData[0]:undefined);setAudit(auditData);setStatus('loaded');setError('');
    }catch(cause){setRuns([]);setCurrent(undefined);setAudit(undefined);setStatus('error');setError(cause instanceof Error?cause.message:'评测与审计数据加载失败');}
  },[]);
  useEffect(()=>{void load();},[load]);
  const canWrite=backendAvailable&&status==='loaded';
  async function run(){
    if(!canWrite)return;
    setRunning(true);
    try{const result=await api<EvalRun>('/evaluations/run',{method:'POST'});setCurrent(result);setRuns(r=>[result,...r]);message.success(`评测完成：${result.metrics.passed} / ${result.metrics.total} 项通过`);void load();}catch(e){message.error(e instanceof Error?e.message:'评测失败');}finally{setRunning(false);}
  }
  const metrics=current?.metrics;
  const unapprovedWrites=metrics?.unapproved_writes;
  const auditEmpty=(text:string)=>status==='loading'?<LoadingLine text="正在加载审计数据…"/>:status==='error'?<EmptyLine text="审计数据加载失败，请重试"/>:<EmptyLine text={text}/>;
  return <div className="page evaluation-page">
    <PageTitle eyebrow="EVALUATION & AUDIT / 质量与追踪" title="评测与审计" description="用固定用例验证检索与工具行为，用完整事件记录还原每一次系统动作。" extra={<Button icon={<ReloadOutlined/>} onClick={load}>刷新数据</Button>}/>
    {status==='error'&&<ErrorState title="评测与审计数据加载失败" description={`后端不可用或返回异常，运行评测已暂停。${error}`} onRetry={load}/>}
    <Tabs className="page-tabs" activeKey={tab} onChange={setTab} items={[{key:'evaluation',label:'固定集评测'},{key:'audit',label:'审计与工具记录'}]}/>
    {tab==='evaluation'?<>
      <section className="evaluation-hero"><div><span className="eyebrow">REGRESSION TEST / 电商售后固定集</span><h2>每次修改，都用同一组问题验证</h2><p>覆盖知识问答、无依据拒答与订单工具。结果关联数据集版本，支持重复运行对比。</p></div><Button className="evaluation-run-button" type="primary" size="large" disabled={!canWrite||running} aria-busy={running} aria-label="运行固定评测集" onClick={run}>{running?'正在运行评测…':'运行固定评测集'}</Button></section>
      {status==='loading'?<section className="surface"><LoadingLine text="正在加载评测记录…"/></section>:status==='error'?<section className="surface"><EmptyLine text="评测数据加载失败，请重试"/></section>:current?<>
        <div className="eval-context"><span>运行编号 <b className="mono">{current.id.slice(0,8)}</b></span><span>数据集 <b>{current.dataset_version}</b></span><span>应用版本 <b>{current.app_version}</b></span><span>运行时间 <b>{formatTime(current.created_at)}</b></span><div className="run-selector">历史运行 {runs.slice(0,5).map(r=><button className={r.id===current.id?'active':''} key={r.id} onClick={()=>setCurrent(r)}>{formatTime(r.created_at)}</button>)}</div></div>
        <div className="eval-metrics"><div className="pass-score"><span>用例通过率</span><b>{Math.round(metrics!.pass_rate*100)}<small>%</small></b><p>{metrics!.passed} 项通过 / 共 {metrics!.total} 项</p></div><div><span>平均用例耗时</span><b>{metrics!.avg_latency_ms}<small> ms</small></b><p>当前运行环境实测</p></div><div><span>未经审批写入</span><b>{typeof unapprovedWrites==='number'?<>{unapprovedWrites}<small> 次</small></>:'未测量'}</b><p>{typeof unapprovedWrites==='number'?metrics?.unapproved_writes_scope||'测量范围未提供':'当前运行未提供该指标，不构成安全保证'}</p></div><div><span>模型 Token</span><b>{Object.values(current.token_usage||{}).reduce((a,b)=>a+b,0)}</b><p>本次运行累计记录</p></div></div>
        <section className="surface eval-results"><SectionTitle title="逐用例结果" description="展开可查看回答、引用或工具返回，失败项不被隐藏。"/><Table rowKey="case_id" dataSource={current.results} pagination={false} expandable={{expandedRowRender:(r:EvalResult)=><div className="eval-detail">{r.detail.answer&&<><b>系统回答</b><p>{r.detail.answer}</p></>}{r.detail.citations&&r.detail.citations.length>0&&<><b>命中引用</b>{r.detail.citations.map(c=><p key={c.chunk_id}>· {c.document_name} / {c.locator}</p>)}</>}{r.detail.result&&<pre>{JSON.stringify(r.detail.result,null,2)}</pre>}{r.detail.error&&<p className="error-text">{r.detail.error}</p>}</div>}} columns={[
          {title:'用例编号',dataIndex:'case_id',render:v=><span className="mono strong">{v}</span>},
          {title:'类型',dataIndex:'type',render:v=><Tag>{v==='rag'?'知识问答':v==='order'?'订单查询':'异常订单'}</Tag>},
          {title:'验证结果',dataIndex:'passed',render:v=><Status value={v?'succeeded':'failed'} label={v?'通过':'未通过'}/>},
          {title:'耗时',dataIndex:'latency_ms',align:'right',render:v=><span className="mono">{v} ms</span>},
          {title:'输出摘要',key:'summary',render:(_,r:EvalResult)=><span className="eval-summary">{r.detail.answer||r.detail.error||r.detail.result?.status_label||'已验证工具返回'}</span>},
        ]}/></section>
      </>:<section className="surface"><EmptyLine text="尚无评测记录，点击上方按钮运行第一组固定用例。"/></section>}
    </>:<section className="surface audit-section"><div className="audit-head"><SectionTitle title="系统行为记录" description="仅展示业务事件与工具参数，不包含 API Key 等敏感信息。"/><Tabs activeKey={auditTab} onChange={setAuditTab} items={[{key:'events',label:`审计事件（${status==='loaded'?audit?.events.length||0:'—'}）`},{key:'tools',label:`工具调用（${status==='loaded'?audit?.tool_calls.length||0:'—'}）`}]}/></div>{auditTab==='events'?<Table rowKey="id" dataSource={status==='loaded'?audit?.events||[]:[]} pagination={{pageSize:12,hideOnSinglePage:true}} expandable={{expandedRowRender:r=><pre className="tool-payload">{JSON.stringify(r.detail,null,2)}</pre>}} locale={{emptyText:auditEmpty('暂无审计事件')}} columns={[
      {title:'时间',dataIndex:'created_at',width:150,render:formatTime},{title:'类别',dataIndex:'category',width:120,render:v=><Tag>{v}</Tag>},{title:'动作',dataIndex:'action',width:210,render:v=><span className="mono">{v}</span>},{title:'事件详情',dataIndex:'detail',render:v=><span className="audit-json" title={JSON.stringify(v)}>{JSON.stringify(v)}</span>},{title:'耗时',dataIndex:'duration_ms',width:100,align:'right',render:v=>v===null||v===undefined?'—':`${v} ms`},
    ]}/>:<Table rowKey="id" dataSource={status==='loaded'?audit?.tool_calls||[]:[]} pagination={{pageSize:12,hideOnSinglePage:true}} expandable={{expandedRowRender:r=><pre className="tool-payload">{JSON.stringify({parameters:r.parameters,result:r.result,error:r.error},null,2)}</pre>}} locale={{emptyText:auditEmpty('暂无工具调用')}} columns={[
      {title:'时间',dataIndex:'created_at',width:150,render:formatTime},{title:'工具',dataIndex:'tool_name',width:180,render:v=><span className="mono strong">{v}</span>},{title:'参数',dataIndex:'parameters',render:v=><span className="audit-json">{JSON.stringify(v)}</span>},{title:'状态',dataIndex:'status',width:120,render:v=><Status value={v}/>},{title:'耗时',dataIndex:'latency_ms',width:100,align:'right',render:v=>`${v} ms`},
    ]}/>}</section>}
    <div className="evaluation-footnote"><CheckCircleFilled/> 指标仅反映当前固定测试集与模拟业务环境，不代表企业生产水平。</div>
  </div>;
}
