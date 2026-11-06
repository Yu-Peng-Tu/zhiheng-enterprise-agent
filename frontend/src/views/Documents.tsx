import { useCallback, useEffect, useState } from 'react';
import { App, Button, Drawer, Popconfirm, Progress, Table, Tabs, Upload } from 'antd';
import { CloudUploadOutlined, FileTextOutlined, RedoOutlined, ReloadOutlined } from '@ant-design/icons';
import { api, formatTime } from '../api';
import type { DocumentItem, TaskItem } from '../types';
import { PageTitle, SectionTitle, Status, EmptyLine, ErrorState, LoadingLine, type LoadStatus } from '../components';

interface Chunk {id:string;ordinal:number;content:string;locator:string;active:boolean}
export default function Documents({backendAvailable}:{backendAvailable:boolean}){
  const {message}=App.useApp();
  const [docs,setDocs]=useState<DocumentItem[]>([]);
  const [tasks,setTasks]=useState<TaskItem[]>([]);
  const [uploading,setUploading]=useState(false);
  const [refreshing,setRefreshing]=useState(false);
  const [status,setStatus]=useState<LoadStatus>('loading');
  const [error,setError]=useState('');
  const [detail,setDetail]=useState<{document:DocumentItem;chunks:Chunk[]}>();
  const [tab,setTab]=useState('documents');
  const load=useCallback(async()=>{
    setRefreshing(true);setStatus(current=>current==='loaded'?'loaded':'loading');
    try{
      const [d,t]=await Promise.all([api<DocumentItem[]>('/documents'),api<TaskItem[]>('/tasks')]);
      setDocs(d);setTasks(t);setStatus('loaded');setError('');
    }catch(cause){
      setDocs([]);setTasks([]);setStatus('error');setError(cause instanceof Error?cause.message:'知识库数据加载失败');
    }finally{setRefreshing(false);}
  },[]);
  useEffect(()=>{void load();},[load]);
  useEffect(()=>{if(status!=='loaded')return;const timer=setInterval(()=>{if(document.visibilityState==='visible')void load();},4000);return()=>clearInterval(timer);},[load,status]);
  const canWrite=backendAvailable&&status!=='error';
  async function upload(file:File){
    if(!canWrite){message.warning('后端不可用，暂不能上传文档');return;}
    setUploading(true);const body=new FormData();body.append('file',file);
    try{await api('/documents',{method:'POST',body});message.success(`${file.name} 已上传，开始解析与索引`);await load();}catch(e){message.error(e instanceof Error?e.message:'上传失败');}finally{setUploading(false);}
  }
  async function view(doc:DocumentItem){try{setDetail(await api(`/documents/${doc.id}`));}catch(e){message.error(e instanceof Error?e.message:'无法读取文档');}}
  async function reindex(id:string){try{await api(`/documents/${id}/reindex`,{method:'POST'});message.success('已重新提交索引任务');void load();}catch(e){message.error(e instanceof Error?e.message:'重建失败');}}
  async function deactivate(id:string){try{await api(`/documents/${id}`,{method:'DELETE'});message.success('文档已停用，后续检索不会再引用');setDetail(undefined);void load();}catch(e){message.error(e instanceof Error?e.message:'操作失败');}}
  async function retry(id:string){try{await api(`/tasks/${id}/retry`,{method:'POST'});message.success('已从安全阶段重新执行');void load();}catch(e){message.error(e instanceof Error?e.message:'重试失败');}}
  const emptyText=(text:string)=>status==='loading'?<LoadingLine text="正在加载知识库数据…"/>:status==='error'?<EmptyLine text="知识库数据加载失败，请重试"/>:<EmptyLine text={text}/>;
  const count=(value:number)=>status==='loaded'?value:'—';
  return <div className="page documents-page">
    <PageTitle eyebrow="KNOWLEDGE / 文档生命周期" title="知识库管理" description="从上传到停用，每个版本的处理状态与切片内容都有据可查。" extra={<Button icon={<ReloadOutlined/>} onClick={load} loading={refreshing}>刷新状态</Button>}/>
    {status==='error'&&<ErrorState title="知识库数据加载失败" description={`后端不可用或返回异常，当前不能确认文档数量。${error}`} onRetry={load} retrying={refreshing}/>}
    <div className="knowledge-summary"><div><b>{count(docs.filter(d=>d.active).length)}</b><span>有效文档</span></div><div><b>{count(docs.reduce((n,d)=>n+d.chunk_count,0))}</b><span>知识切片</span></div><div><b>{count(docs.filter(d=>d.status==='failed').length)}</b><span>处理失败</span></div><p>支持 PDF、DOCX、TXT、MD<br/><span>单文件最大 10 MB · 重复内容自动识别</span></p></div>
    <section className="surface knowledge-main">
      <Tabs activeKey={tab} onChange={setTab} items={[{key:'documents',label:`文档库（${count(docs.length)}）`},{key:'tasks',label:`处理任务（${count(tasks.length)}）`}]} tabBarExtraContent={<Upload accept=".pdf,.docx,.txt,.md" showUploadList={false} beforeUpload={file=>{void upload(file);return false;}} disabled={!canWrite||uploading}><Button type="primary" icon={<CloudUploadOutlined/>} loading={uploading} disabled={!canWrite||uploading}>上传文档</Button></Upload>}/>
      {tab==='documents'?<Table rowKey="id" dataSource={status==='loaded'?docs:[]} pagination={false} locale={{emptyText:emptyText('尚未上传文档')}} columns={[
        {title:'文档',dataIndex:'filename',render:(v,d:DocumentItem)=><button className="document-name" onClick={()=>view(d)}><span className="file-icon"><FileTextOutlined/></span><span><b>{v}</b><small>{d.file_type.toUpperCase()} · 版本 v{d.version}</small></span></button>},
        {title:'处理状态',dataIndex:'status',width:150,render:(v,d:DocumentItem)=><div><Status value={v}/>{d.error&&<small className="error-text">{d.error}</small>}</div>},
        {title:'切片数',dataIndex:'chunk_count',width:100,align:'right',render:v=><span className="mono">{v}</span>},
        {title:'检索范围',dataIndex:'active',width:120,render:v=><span className={v?'scope-active':'scope-off'}>{v?'已启用':'已排除'}</span>},
        {title:'更新时间',dataIndex:'created_at',width:140,render:formatTime},
        {title:'操作',key:'actions',width:160,render:(_,d:DocumentItem)=><div className="table-actions"><Button type="text" title="查看切片" onClick={()=>view(d)}>详情</Button><Button type="text" title="重建索引" disabled={!canWrite} onClick={()=>reindex(d.id)}>重建</Button><Popconfirm title="停用这份文档？" description="历史引用将保留，但不再参与新检索。" onConfirm={()=>deactivate(d.id)} okText="确认停用" cancelText="取消"><Button type="text" danger disabled={!d.active||!canWrite}>停用</Button></Popconfirm></div>},
      ]}/>:<Table rowKey="id" dataSource={status==='loaded'?tasks:[]} pagination={false} locale={{emptyText:emptyText('暂无处理任务')}} columns={[
        {title:'任务',dataIndex:'kind',render:(v,t:TaskItem)=><div className="task-name"><b>{v==='document_index'?'文档解析与索引':v}</b><small className="mono">{t.id}</small></div>},
        {title:'阶段',dataIndex:'stage',width:170,render:(v,t:TaskItem)=><div className="task-progress"><span>{v}</span><Progress percent={t.progress} size="small" showInfo={false}/></div>},
        {title:'状态',dataIndex:'status',width:120,render:v=><Status value={v}/>},
        {title:'重试',dataIndex:'retry_count',width:80,align:'right'},
        {title:'最近更新',dataIndex:'updated_at',width:150,render:formatTime},
        {title:'诊断 / 操作',key:'error',width:280,render:(_,t:TaskItem)=><div className="task-error">{t.error&&<span>{t.error}</span>}{t.status==='failed'&&<Button size="small" icon={<RedoOutlined/>} disabled={!canWrite} onClick={()=>retry(t.id)}>安全重试</Button>}</div>},
      ]}/>}
    </section>
    <Drawer title="文档与切片详情" width={640} open={!!detail} onClose={()=>setDetail(undefined)} extra={detail&&<Status value={detail.document.status}/>}>{detail&&<div className="document-detail"><div className="document-detail-head"><h2>{detail.document.filename}</h2><p>版本 v{detail.document.version} · {detail.document.chunk_count} 个切片</p></div><SectionTitle title="解析内容" description="切片保留原始定位，用于引用一致性核验。"/>{detail.chunks.length?detail.chunks.map(c=><article className="chunk" key={c.id}><div><span>切片 {String(c.ordinal+1).padStart(2,'0')}</span><span>{c.locator}</span><Status value={c.active?'active':'deleted'} label={c.active?'有效':'已排除'}/></div><p>{c.content}</p><small className="mono">{c.id}</small></article>):<EmptyLine text="暂无可显示的切片"/>}</div>}</Drawer>
  </div>;
}
