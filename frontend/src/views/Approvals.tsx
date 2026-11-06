import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Button, Drawer, Empty, Input, Modal, Segmented, Select } from 'antd';
import { CheckOutlined, CloseOutlined, DownloadOutlined, FileDoneOutlined, SafetyCertificateOutlined, StopOutlined } from '@ant-design/icons';
import { api, downloadText, formatTime, report } from '../api';
import type { Approval, TicketDraft } from '../types';
import { PageTitle, Status, priorities, ticketTypes, ErrorState, LoadingLine, EmptyLine, type LoadStatus } from '../components';

export default function Approvals({backendAvailable}:{backendAvailable:boolean}){
  const {message}=App.useApp();
  const [items,setItems]=useState<Approval[]>([]);
  const [filter,setFilter]=useState<string>('pending');
  const [selected,setSelected]=useState<Approval>();
  const [draft,setDraft]=useState<TicketDraft>();
  const [decision,setDecision]=useState<'approve'|'reject'>();
  const [reason,setReason]=useState('');
  const [busy,setBusy]=useState(false);
  const [reportText,setReportText]=useState<string>();
  const [status,setStatus]=useState<LoadStatus>('loading');
  const [error,setError]=useState('');
  const load=useCallback(async()=>{
    setStatus(current=>current==='loaded'?'loaded':'loading');
    try{
      const data=await api<Approval[]>('/approvals');setItems(data);setSelected(current=>current?data.find(a=>a.id===current.id):undefined);setStatus('loaded');setError('');
    }catch(cause){setItems([]);setSelected(undefined);setStatus('error');setError(cause instanceof Error?cause.message:'审批数据加载失败');}
  },[]);
  useEffect(()=>{void load();},[load]);
  useEffect(()=>{if(selected)setDraft({...selected.draft});else setDraft(undefined);},[selected]);
  const filtered=useMemo(()=>items.filter(i=>filter==='all'||(filter==='pending'?i.status==='pending':i.status!=='pending')),[items,filter]);
  const changed=selected&&draft&&JSON.stringify(selected.draft)!==JSON.stringify(draft);
  const canWrite=backendAvailable&&status==='loaded';
  async function submitDecision(){
    if(!selected||!canWrite)return;if(decision==='reject'&&!reason.trim()){message.warning('请填写拒绝原因');return;}setBusy(true);
    try{const updated=await api<Approval>(`/approvals/${selected.id}/${decision}`,{method:'POST',body:JSON.stringify({reason:reason||undefined,modifications:decision==='approve'?{ticket_type:draft?.ticket_type,reason:draft?.reason,priority:draft?.priority}:undefined})});setSelected(updated);setItems(list=>list.map(i=>i.id===updated.id?updated:i));setDecision(undefined);setReason('');message.success(decision==='approve'?`工单 ${updated.ticket_id} 已创建`:'已拒绝执行，未创建工单');}catch(e){message.error(e instanceof Error?e.message:'审批失败');}finally{setBusy(false);}
  }
  async function makeReport(){if(!selected||!canWrite)return;try{setReportText(await report(selected.order_id,selected.ticket_id));}catch(e){message.error(e instanceof Error?e.message:'生成失败');}}
  const count=(value:number)=>status==='loaded'?value:'—';
  return <div className="page approvals-page">
    <PageTitle eyebrow="HUMAN-IN-THE-LOOP / 人工审批" title="审批中心" description="工单在执行前保持可修改、可拒绝。批准动作只执行一次，完整保留审批记录。" extra={<span className="security-note"><SafetyCertificateOutlined/> 无直接写入入口</span>}/>
    {status==='error'&&<ErrorState title="审批数据加载失败" description={`后端不可用或返回异常，审批操作已暂停。${error}`} onRetry={load}/>}
    <div className="approval-stats"><div><span>等待审批</span><b>{count(items.filter(i=>i.status==='pending').length)}</b></div><div><span>已批准执行</span><b>{count(items.filter(i=>i.status==='approved').length)}</b></div><div><span>已拒绝</span><b>{count(items.filter(i=>i.status==='rejected').length)}</b></div><p><StopOutlined/> 未获得有效审批的写操作始终被阻止</p></div>
    <div className="approval-workspace">
      <section className="approval-list"><div className="approval-filter"><Segmented value={filter} onChange={v=>setFilter(v as string)} options={[{label:'待审批',value:'pending'},{label:'已处理',value:'done'},{label:'全部',value:'all'}]}/><Button type="text" onClick={load}>刷新</Button></div><div className="approval-items">{status==='loading'?<LoadingLine text="正在加载审批记录…"/>:status==='error'?<EmptyLine text="审批数据加载失败，请重试"/>:filtered.length?filtered.map(a=><button className={selected?.id===a.id?'approval-item selected':'approval-item'} key={a.id} onClick={()=>setSelected(a)}><div className="approval-item-top"><span className="mono">{a.order_id}</span><Status value={a.status}/></div><h3>{ticketTypes[a.draft.ticket_type]}工单 <span>· {priorities[a.draft.priority]}优先级</span></h3><p>{a.draft.reason}</p><div className="approval-item-bottom"><span>{formatTime(a.created_at)}</span><span>{a.ticket_id||`草案 #${a.id.slice(0,8)}`}</span></div></button>):<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前队列没有记录"/>}</div></section>
      <section className="approval-detail">{selected&&draft?<><div className="detail-head"><div><span className="eyebrow">APPROVAL / {selected.id.slice(0,8).toUpperCase()}</span><h2>工单参数核验</h2></div><Status value={selected.status}/></div><div className="execution-warning"><SafetyCertificateOutlined/><div><b>{selected.status==='pending'?'当前仅为参数草案':'审批决定已记录'}</b><p>{selected.status==='pending'?'在批准之前，系统不会调用工单创建工具。':selected.status==='approved'?`已创建工单 ${selected.ticket_id}`:'该草案已拒绝，未产生业务写入。'}</p></div></div><div className="parameter-form"><label><span>关联订单 <em>只读</em></span><Input value={draft.order_id} disabled className="mono"/></label><label><span>工单类型</span><Select value={draft.ticket_type} disabled={selected.status!=='pending'||!canWrite} onChange={v=>setDraft({...draft,ticket_type:v})} options={Object.entries(ticketTypes).map(([value,label])=>({value,label}))}/></label><label><span>优先级</span><Select value={draft.priority} disabled={selected.status!=='pending'||!canWrite} onChange={v=>setDraft({...draft,priority:v})} options={Object.entries(priorities).map(([value,label])=>({value,label}))}/></label><label className="reason-field"><span>申请原因 <em>{draft.reason.length} / 1000</em></span><Input.TextArea value={draft.reason} disabled={selected.status!=='pending'||!canWrite} onChange={e=>setDraft({...draft,reason:e.target.value})} rows={5} maxLength={1000} showCount={false}/></label></div>{changed&&<div className="changed-note">参数已修改，批准时将重新进行 Schema 与业务规则校验。</div>}<div className="approval-meta"><div><span>创建时间</span><b>{formatTime(selected.created_at)}</b></div><div><span>审批记录</span><b className="mono">{selected.id}</b></div>{selected.decision_reason&&<div><span>决定原因</span><b>{selected.decision_reason}</b></div>}</div><div className="approval-actions">{selected.status==='pending'?<><Button danger icon={<CloseOutlined/>} disabled={!canWrite} onClick={()=>setDecision('reject')}>拒绝执行</Button><Button type="primary" icon={<CheckOutlined/>} disabled={!canWrite||draft.reason.trim().length<2} onClick={()=>setDecision('approve')}>批准并创建工单</Button></>:<><span><FileDoneOutlined/> 此记录已完成审批</span>{selected.status==='approved'&&<Button icon={<FileDoneOutlined/>} disabled={!canWrite} onClick={makeReport}>生成处理报告</Button>}</>}</div></>:<div className="approval-placeholder"><SafetyCertificateOutlined/><h2>选择一条审批记录</h2><p>核验订单、工单类型和申请原因后，再批准或拒绝执行。</p></div>}</section>
    </div>
    <Modal title={decision==='approve'?'确认批准并执行':'确认拒绝此草案'} open={!!decision} onCancel={()=>{setDecision(undefined);setReason('');}} onOk={submitDecision} confirmLoading={busy} okText={decision==='approve'?'确认创建工单':'确认拒绝'} cancelText="返回检查" okButtonProps={{danger:decision==='reject'}}><div className="decision-summary">{decision==='approve'?<><SafetyCertificateOutlined/><p>将对订单 <b>{selected?.order_id}</b> 创建 <b>{draft&&ticketTypes[draft.ticket_type]}</b>工单。同一审批的重复提交不会重复创建。</p></>:<><StopOutlined/><p>拒绝后不会调用工单创建工具，此决定会写入审计记录。</p></>}</div><Input.TextArea rows={3} value={reason} onChange={e=>setReason(e.target.value)} placeholder={decision==='approve'?'审批备注（可选）':'请填写拒绝原因（必填）'}/></Modal>
    <Drawer title="售后处理报告" width={600} open={reportText!==undefined} onClose={()=>setReportText(undefined)} extra={<Button icon={<DownloadOutlined/>} onClick={()=>reportText&&downloadText(`售后处理报告-${selected?.order_id}.md`,reportText)}>下载 Markdown</Button>}><p className="modal-description">报告由当前订单与工单结果生成，可在下载前编辑。</p><Input.TextArea className="report-editor" value={reportText} onChange={e=>setReportText(e.target.value)} rows={24}/></Drawer>
  </div>;
}
