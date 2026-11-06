import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Drawer, Input, Modal, Spin, App } from 'antd';
import { ArrowUpOutlined, BookOutlined, CheckCircleFilled, FileSearchOutlined, LinkOutlined, SafetyCertificateOutlined, SearchOutlined } from '@ant-design/icons';
import { ApiError, api, formatTime } from '../api';
import type { Approval, ChatMessage, Citation, Order } from '../types';
import { PageTitle, Status, modeNames, ErrorState, LoadingLine, EmptyLine, type LoadStatus } from '../components';
import type { ViewKey } from '../App';

const suggestions=['7 天无理由退货需要满足哪些条件？','查询订单 SQ100002 的物流状态','订单 SQ100001 想申请退货，请创建工单','我们的售后政策支持永久退款吗？'];
type OrderLookup={status:'idle'}|{status:'loading';orderId:string}|{status:'loaded';order:Order}|{status:'not_found'|'error';orderId:string;message:string};

function DraftNotice({approval,navigate}:{approval:Approval;navigate:(key:ViewKey)=>void}){
  const content=approval.status==='approved'?{
    title:'工单草案已批准并执行',
    detail:`订单 ${approval.order_id} · 工单 ${approval.ticket_id||'已创建'}`,
    action:'查看审批与工单',
  }:approval.status==='rejected'?{
    title:'工单草案已拒绝，未执行',
    detail:`订单 ${approval.order_id} · 审批已拒绝${approval.decision_reason?`：${approval.decision_reason}`:''}`,
    action:'查看审批记录',
  }:{
    title:'工单草案已生成，尚未执行',
    detail:`订单 ${approval.order_id} · 等待人工审批`,
    action:'去审批',
  };
  return <div className="draft-notice" data-status={approval.status}><SafetyCertificateOutlined/><div><b>{content.title}</b><p>{content.detail}</p></div><Button size="small" onClick={()=>navigate('approvals')}>{content.action}</Button></div>;
}

export default function Chat({navigate,backendAvailable}:{navigate:(key:ViewKey)=>void;backendAvailable:boolean}) {
  const {message}=App.useApp();
  const [history,setHistory]=useState<ChatMessage[]>([]);
  const [input,setInput]=useState('');
  const [loading,setLoading]=useState(false);
  const [historyStatus,setHistoryStatus]=useState<LoadStatus>('loading');
  const [historyError,setHistoryError]=useState('');
  const [citation,setCitation]=useState<Citation>();
  const [feedback,setFeedback]=useState<ChatMessage>();
  const [reason,setReason]=useState('');
  const [orders,setOrders]=useState<Order[]>([]);
  const [orderLookup,setOrderLookup]=useState<OrderLookup>({status:'idle'});
  const endRef=useRef<HTMLDivElement>(null);
  const load=useCallback(async()=>{
    setHistoryStatus('loading');
    try{
      const [messages,orderData]=await Promise.all([api<ChatMessage[]>('/messages'),api<Order[]>('/orders')]);
      setHistory([...messages].reverse());setOrders(orderData);setHistoryStatus('loaded');setHistoryError('');
    }catch(error){setHistory([]);setOrders([]);setOrderLookup({status:'idle'});setHistoryStatus('error');setHistoryError(error instanceof Error?error.message:'会话数据加载失败');}
  },[]);
  useEffect(()=>{void load();},[load]);
  useEffect(()=>{endRef.current?.scrollIntoView({behavior:'smooth',block:'nearest'});},[history,loading]);
  const canSend=backendAvailable&&historyStatus==='loaded';
  async function ask(text=input){
    const question=text.trim();if(!question||loading||!canSend)return;
    const match=question.match(/SQ\d{6}/i);
    const orderId=match?.[0].toUpperCase();
    if(orderId)setOrderLookup({status:'loading',orderId});
    setLoading(true);
    try{
      const answer=await api<ChatMessage>('/chat',{method:'POST',body:JSON.stringify({question})});
      setHistory(h=>[...h,answer]);
      setInput(current=>current===text?'':current);
      if(orderId){
        try{
          const result=await api<{order:Order}>('/tools/orders/query',{method:'POST',body:JSON.stringify({order_id:orderId})});
          setOrderLookup({status:'loaded',order:result.order});
        }catch(error){
          const notFound=error instanceof ApiError&&error.status===404;
          setOrderLookup({status:notFound?'not_found':'error',orderId,message:notFound?'请核对订单号后重新查询。':error instanceof Error?error.message:'订单查询失败，请重试。'});
        }
      }
    }catch(e){
      if(orderId)setOrderLookup({status:'error',orderId,message:e instanceof Error?e.message:'问答请求失败，订单状态不可用。'});
      message.error(e instanceof Error?e.message:'问答请求失败');
    }finally{setLoading(false);}
  }
  async function sendFeedback(item:ChatMessage,helpful:boolean,why?:string){
    try{await api('/feedback',{method:'POST',body:JSON.stringify({message_id:item.id,helpful,reason:why})});setHistory(h=>h.map(m=>m.id===item.id?{...m,localFeedback:true}:m));setFeedback(undefined);setReason('');message.success('反馈已保存，感谢你的核验');}catch(e){message.error(e instanceof Error?e.message:'反馈保存失败');}
  }
  const quickOrders=<div className="quick-orders">{orders.slice(0,4).map(o=><button key={o.order_id} disabled={!canSend||loading} onClick={()=>ask(`查询订单 ${o.order_id} 的状态`)}><span className="mono">{o.order_id}</span><Status value={o.status}/></button>)}</div>;
  return <div className="page chat-page">
    <PageTitle eyebrow="WORKSPACE / 知识到行动" title="知识与业务问答" description="查询企业制度与模拟订单。涉及工单创建时，系统只生成草案，等待人工审批。" extra={<span className="security-note"><SafetyCertificateOutlined/> 写操作保护已开启</span>}/>
    <div className="chat-workspace">
      <section className="conversation-panel">
        <div className="conversation-head"><div><b>售后处理会话</b><span>基于当前有效知识库</span></div><span className="trace-label">全程留痕</span></div>
        <div className="message-scroll">
          {historyStatus==='loading'?<LoadingLine text="正在加载历史会话…"/>:historyStatus==='error'?<><ErrorState title="历史会话加载失败" description={`后端不可用或返回异常，当前不能确认会话是否为空。${historyError}`} onRetry={load}/><EmptyLine text="会话数据加载失败，请重试"/></>:history.length===0?<div className="chat-welcome"><div className="welcome-icon"><FileSearchOutlined/></div><h2>先找到依据，再给出答案</h2><p>你可以询问退货、物流与保修政策，也可以输入订单号办理售后。</p><div className="example-grid">{suggestions.map((s,i)=><button key={s} disabled={!canSend||loading} onClick={()=>ask(s)}><span>0{i+1}</span>{s}<ArrowUpOutlined/></button>)}</div></div>:
          history.map(item=><div className="exchange" key={item.id}>
            <div className="user-message"><div className="message-avatar">我</div><div><p>{item.question}</p><time>{formatTime(item.created_at)}</time></div></div>
            <div className="assistant-message"><div className="message-avatar ai"><BookOutlined/></div><div className="answer-body">
              <div className="answer-meta"><b>知衡</b><span>{modeNames[item.mode]||item.mode}</span><span>{item.latency_ms} ms</span></div>
              <div className="answer-text">{item.answer.replace(/^#{1,6}\s+/gm,'')}</div>
              {item.citations.length>0&&<div className="citation-block"><div className="citation-heading"><LinkOutlined/> 回答依据 <span>{item.citations.length} 条</span></div><div className="citation-list">{item.citations.map((c,i)=><button className="citation-item" key={c.chunk_id} onClick={()=>setCitation(c)}><span className="citation-no">{i+1}</span><span><b>{c.document_name}</b><small>{c.locator} · {c.version?`v${c.version}`:'版本未记录'}</small></span><FileSearchOutlined/></button>)}</div></div>}
              {item.answer.includes('依据不足')&&<div className="insufficient"><SearchOutlined/><span>没有足够依据，因此未生成事实性结论或引用。</span></div>}
              {item.approval&&<DraftNotice approval={item.approval} navigate={navigate}/>}
              <div className="answer-footer"><span>{item.token_usage.prompt_tokens+item.token_usage.completion_tokens} tokens</span><div>{item.localFeedback?<span className="feedback-saved"><CheckCircleFilled/> 已反馈</span>:<><Button type="text" size="small" onClick={()=>sendFeedback(item,true)}>有帮助</Button><Button type="text" size="small" onClick={()=>setFeedback(item)}>无帮助</Button></>}</div></div>
            </div></div>
          </div>)}
          {loading&&<div className="assistant-message loading-message"><div className="message-avatar ai"><BookOutlined/></div><div><Spin size="small"/><span>正在检索有效文档并核对业务数据…</span></div></div>}
          <div ref={endRef}/>
        </div>
        <div className="composer-wrap"><div className="composer"><Input.TextArea value={input} onChange={e=>setInput(e.target.value)} onPressEnter={e=>{if(!e.shiftKey){e.preventDefault();void ask();}}} autoSize={{minRows:1,maxRows:4}} disabled={!canSend} placeholder="输入政策问题，或 SQ + 6 位数字的订单号…"/><Button type="primary" disabled={!input.trim()||loading||!canSend} onClick={()=>ask()} aria-label="发送问题">发送</Button></div><p>Enter 发送 · Shift + Enter 换行　回答仅基于模拟企业数据，请核验引用后使用</p></div>
      </section>
      <aside className="chat-aside">
        <section className="aside-section"><div className="aside-title">业务速查 <span>ORDER LOOKUP</span></div>
          {orderLookup.status==='loaded'?<div className="order-focus"><div className="order-focus-top"><span className="mono">{orderLookup.order.order_id}</span><Status value={orderLookup.order.status}/></div><h3>{orderLookup.order.product}</h3><dl><div><dt>客户</dt><dd>{orderLookup.order.customer_name}</dd></div><div><dt>实付金额</dt><dd>¥{orderLookup.order.amount.toLocaleString()}</dd></div><div><dt>物流状态</dt><dd>{orderLookup.order.logistics}</dd></div><div><dt>下单时间</dt><dd>{orderLookup.order.ordered_at}</dd></div></dl></div>:orderLookup.status==='loading'?<div className="order-lookup-state" role="status">正在查询订单 <b className="mono">{orderLookup.orderId}</b>…</div>:orderLookup.status==='not_found'||orderLookup.status==='error'?<div className={`order-lookup-state ${orderLookup.status}`}><b>订单 {orderLookup.orderId} {orderLookup.status==='not_found'?'未找到':'当前不可用'}</b><p>{orderLookup.message}</p><Button size="small" disabled={!canSend||loading} onClick={()=>ask(`查询订单 ${orderLookup.orderId} 的状态`)}>重新查询</Button></div>:<><p className="aside-hint">点击订单号，快速查询当前业务状态。</p>{quickOrders}</>}
        </section>
        <section className="aside-section guardrail"><div className="aside-title">本次会话的边界</div><ul><li><CheckCircleFilled/>仅引用有效文档版本</li><li><CheckCircleFilled/>无依据时明确说明不足</li><li><CheckCircleFilled/>订单查询不会改变业务状态</li><li><SafetyCertificateOutlined/>工单必须审批后才能创建</li></ul></section>
        <section className="aside-section source-scope"><div className="aside-title">当前知识范围</div><div><span>售后政策</span><span>物流配送</span><span>保修服务</span></div><p>模拟电商售后知识库 · 3 个主题</p></section>
      </aside>
    </div>
    <Drawer title="引用原文核验" width={500} open={!!citation} onClose={()=>setCitation(undefined)}>{citation&&<div className="citation-drawer"><div className="source-document"><FileSearchOutlined/><div><h3>{citation.document_name}</h3><p>{citation.version?`版本 v${citation.version}`:'版本未记录'} · {citation.locator}</p></div></div><div className="evidence-label">原文片段</div><blockquote>{citation.content}</blockquote><dl><div><dt>文档 ID</dt><dd className="mono">{citation.document_id}</dd></div><div><dt>切片 ID</dt><dd className="mono">{citation.chunk_id}</dd></div><div><dt>检索相关度</dt><dd>{Math.round(citation.score*100)} / 100</dd></div></dl><div className="drawer-note">此片段来自当前有效文档版本，与回答保存时的引用记录一致。</div></div>}</Drawer>
    <Modal title="标记回答无帮助" open={!!feedback} onCancel={()=>setFeedback(undefined)} onOk={()=>feedback&&sendFeedback(feedback,false,reason)} okText="提交反馈" cancelText="取消"><p className="modal-description">请说明问题所在，反馈将关联当前回答与引用版本。</p><Input.TextArea rows={4} value={reason} onChange={e=>setReason(e.target.value)} placeholder="例如：回答遗漏了退货条件，或引用与问题无关…"/></Modal>
  </div>;
}
