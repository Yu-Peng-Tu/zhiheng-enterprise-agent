import { useCallback, useEffect, useState } from 'react';
import { Button, Layout, Tooltip } from 'antd';
import { AppstoreOutlined, CommentOutlined, DatabaseOutlined, SafetyCertificateOutlined, FundOutlined, RightOutlined, CheckCircleFilled, ExperimentOutlined } from '@ant-design/icons';
import Dashboard from './views/Dashboard';
import Chat from './views/Chat';
import Documents from './views/Documents';
import Approvals from './views/Approvals';
import Evaluation from './views/Evaluation';
import { api } from './api';
import type { Health } from './types';
import { ErrorState, type LoadStatus } from './components';

export type ViewKey = 'dashboard'|'chat'|'documents'|'approvals'|'evaluation';
const items: {key:ViewKey; label:string; caption:string; icon:React.ReactNode}[] = [
  { key:'dashboard', label:'运营概览', caption:'OVERVIEW', icon:<AppstoreOutlined /> },
  { key:'chat', label:'知识与业务问答', caption:'WORKSPACE', icon:<CommentOutlined /> },
  { key:'documents', label:'知识库管理', caption:'KNOWLEDGE', icon:<DatabaseOutlined /> },
  { key:'approvals', label:'审批中心', caption:'APPROVALS', icon:<SafetyCertificateOutlined /> },
  { key:'evaluation', label:'评测与审计', caption:'OBSERVABILITY', icon:<FundOutlined /> },
];
const titles: Record<ViewKey,string> = { dashboard:'运营概览', chat:'知识与业务问答', documents:'知识库管理', approvals:'审批中心', evaluation:'评测与审计' };
function currentView(): ViewKey { const key = location.hash.slice(1) as ViewKey; return items.some(i=>i.key===key) ? key : 'dashboard'; }

export default function App() {
  const [view,setView] = useState<ViewKey>(currentView);
  const [health,setHealth] = useState<Health>();
  const [healthStatus,setHealthStatus] = useState<LoadStatus>('loading');
  const [healthError,setHealthError] = useState('');
  const navigate = (key:ViewKey) => { location.hash = key; setView(key); };
  const checkHealth = useCallback(async () => {
    setHealthStatus('loading');
    try { setHealth(await api<Health>('/health')); setHealthStatus('loaded'); setHealthError(''); }
    catch (error) { setHealth(undefined); setHealthStatus('error'); setHealthError(error instanceof Error ? error.message : '后端连接失败'); }
  },[]);
  useEffect(()=>{ const change=()=>setView(currentView()); window.addEventListener('hashchange',change); return ()=>window.removeEventListener('hashchange',change); },[]);
  useEffect(()=>{ void checkHealth(); },[view,checkHealth]);
  const backendAvailable = healthStatus === 'loaded' || (healthStatus === 'loading' && !healthError);
  const modeText = healthStatus === 'loading' ? '正在检查后端状态' : healthStatus === 'error' ? '后端不可用' : health?.llm_enabled ? '在线模型已连接' : '离线可验收模式';
  return <Layout className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={()=>navigate('dashboard')} aria-label="返回概览">
        <span className="brand-mark"><i/><i/><i/></span>
        <span><strong>知衡</strong><small>企业知识与流程 Agent</small></span>
      </button>
      <div className="workspace-label">工作台 <span>PRO</span></div>
      <nav className="main-nav" aria-label="主导航">
        {items.map(item=><button key={item.key} className={view===item.key?'nav-item active':'nav-item'} onClick={()=>navigate(item.key)}>
          <span className="nav-icon">{item.icon}</span><span className="nav-copy"><b>{item.label}</b><small>{item.caption}</small></span>{view===item.key&&<RightOutlined className="nav-arrow"/>}
        </button>)}
      </nav>
      <div className="sidebar-spacer"/>
      <div className="principle">
        <ExperimentOutlined />
        <strong>可控，始于可核验</strong>
        <p>每个结论有出处，每次写入需审批。</p>
      </div>
      <div className="runtime">
        <span className="runtime-dot"/><span>本地工作空间</span><span className="version">{health?`v${health.version}`:'—'}</span>
      </div>
      <div className="profile"><div className="avatar">运</div><div><b>运营工作台</b><small>演示管理员</small></div><Tooltip title="模拟业务环境"><CheckCircleFilled className="verified"/></Tooltip></div>
    </aside>
    <Layout className="main-layout">
      <header className="topbar"><div className="breadcrumb">知衡工作台 <span>/</span> <b>{titles[view]}</b></div><div className="topbar-right"><span className="demo-badge">模拟业务数据</span><span className="separator"/><span className={`mode-indicator ${healthStatus}`} data-health-state={healthStatus}><i/>{modeText}</span>{healthStatus==='error'&&<Button type="link" size="small" onClick={checkHealth}>重试连接</Button>}</div></header>
      <main className="content">
        {healthStatus==='error'&&<ErrorState title="后端不可用" description={`页面数据可能不是最新，写操作已暂停。${healthError}`} onRetry={checkHealth}/>}
        {view==='dashboard'&&<Dashboard navigate={navigate} healthStatus={healthStatus}/>}
        {view==='chat'&&<Chat navigate={navigate} backendAvailable={backendAvailable}/>}
        {view==='documents'&&<Documents backendAvailable={backendAvailable}/>}
        {view==='approvals'&&<Approvals backendAvailable={backendAvailable}/>}
        {view==='evaluation'&&<Evaluation backendAvailable={backendAvailable}/>}
      </main>
      <footer className="app-footer"><span>ZHIHENG · KNOWLEDGE TO ACTION</span><span>FastAPI · React · RAG · Human-in-the-loop</span></footer>
    </Layout>
  </Layout>;
}
