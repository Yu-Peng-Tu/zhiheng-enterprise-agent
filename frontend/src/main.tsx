import '@ant-design/v5-patch-for-react-19';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './styles.css';

const theme = {
  token: {
    colorPrimary: '#3563d9',
    colorInfo: '#3563d9',
    colorText: '#202939',
    colorTextSecondary: '#697386',
    colorBgLayout: '#f5f6f8',
    colorBorder: '#dfe3ea',
    borderRadius: 7,
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif',
  },
  components: {
    Button: { controlHeight: 36, fontWeight: 500 },
    Input: { controlHeight: 38 },
    Select: { controlHeight: 38 },
    Table: { headerBg: '#f7f9f6', headerColor: '#63716e', cellPaddingBlock: 14 },
    Menu: { itemHeight: 44, itemBorderRadius: 6 },
  },
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp><App /></AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
