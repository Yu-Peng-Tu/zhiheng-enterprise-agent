# 知衡 · 企业知识与流程 Agent

一个面向模拟电商售后场景的全栈 AI 应用。它把企业文档、订单查询与工单审批串成一条可核验、可控制、可恢复的业务闭环，而不是只做“上传文档后聊天”。

**核心原则：有依据地回答，受控制地执行。**

## English overview

Zhiheng is a full-stack enterprise AI application built around a simulated e-commerce after-sales workflow. It connects document-grounded answers, order lookup, ticket drafting, human approval, idempotent execution, evaluation, and audit trails in one controlled business loop.

**Design principle: answer with evidence; execute under control.**

- **Traceable RAG**: document versioning, chunk-level citations, hybrid retrieval, and explicit insufficient-evidence responses.
- **Controlled actions**: schema-validated tools, editable ticket drafts, human approval, and idempotent ticket creation.
- **Recoverable operations**: asynchronous document jobs, status updates, safe retries, audit events, and backup/recovery documentation.
- **Full-stack implementation**: React, TypeScript, FastAPI, SQL, Redis/RQ, and Docker Compose, with an offline acceptance mode.

The project is intended for trusted local demonstrations and isolated pilots. It is not a production-ready multi-tenant SaaS system.

## 一分钟理解

```text
企业文档 → 可追溯问答 → 订单查询 → 工单草案
        → 人工审批 → 幂等创建工单 → 处理报告
        → 固定集评测与完整审计
```

知衡不是单纯的聊天页面或传统后台，而是一个**单 Agent + 确定性工作流**的企业应用：模型负责理解与建议，系统通过 Schema、人工审批和幂等机制控制真实业务写入。项目可用于演示以下工程主题：

- RAG 检索、引用版本与无依据拒答；
- Agent 工具调用和业务参数校验；
- Human-in-the-loop 审批与有副作用操作的受控执行；
- 幂等写入、审计追踪、固定集评测和交付边界管理；
- React / FastAPI / SQL / Redis / Docker 组成的全栈应用结构。

演示状态：项目支持本地与 Docker Compose 演示，当前未提供公网托管地址。

## 已实现功能

- **知识库管理**：PDF / DOCX / TXT / MD 上传，空文件与重复文件校验，解析、切片、索引状态展示，切片原文查看，重建索引、失败重试与文档停用。
- **可追溯问答**：本地哈希向量与关键词混合检索，回答关联有效文档版本、切片原文、定位和相关分数；低相关问题时明确提示依据不足。
- **业务工具**：自然语言或订单号查询模拟订单；非法订单号由 Schema 拒绝，不存在的订单返回可诊断结果。
- **受控工单**：只生成工单草案；审批人可修改类型、原因与优先级，也可以拒绝；批准后才执行创建。幂等键避免同一审批重复创建工单。
- **异步任务**：本地开发使用 FastAPI 后台任务，Compose 使用 Redis + RQ；文档任务支持 SSE 状态订阅、错误诊断与安全重试。
- **质量评测**：版本化 JSON 固定集，保存逐用例输出、引用、延迟和 Token 记录，展示通过率与未经审批写入次数。
- **审计与反馈**：保存问答、检索工具、订单查询、审批与执行事件；支持回答有帮助 / 无帮助反馈。
- **处理报告**：基于订单与已创建工单生成可编辑 Markdown 报告并下载。
- **离线可验收**：不配置 API Key 时，检索、依据摘录、订单、审批、评测和报告均可用；配置 OpenAI 兼容接口后可启用在线生成，失败自动降级。

## 技术架构

```text
React + TypeScript + Ant Design（桌面 Web）
                   │ REST / SSE
                   ▼
FastAPI ── 文档解析 / 混合检索 / 引用核验
   │      ── 显式业务分流 / 工具 Schema / 审批状态
   │      ── 固定集评测 / 审计 / 报告
   ├────────────── Redis + RQ（Compose 异步任务）
   ├────────────── PostgreSQL + pgvector（Compose 持久化）
   └────────────── SQLite（本地默认持久化）

Mock Tools：订单查询（只读） / 工单创建（审批后写入）
Model Adapter：OpenAI 兼容 API（可选） / 本地依据生成（默认）
```

当前检索由应用层计算 256 维哈希向量并融合关键词得分，避免本地运行依赖外部嵌入服务。Compose 提供 pgvector 数据库，应用向量仍以 JSON 字段保存并由应用层排序；后续可在不改变 API 的情况下替换为数据库向量检索或独立嵌入模型。

## 交付边界

本项目的交付定位是**受信隔离环境中的企业演示／单机关试点**，不是正式规模生产系统。当前不具备真实身份认证、组织权限、SSO、租户隔离、正式 schema 迁移、完整监控告警或规模压测结论；“演示管理员”不是安全身份，不应将服务暴露到非受信网络。

- [企业交付清单](docs/ENTERPRISE_DELIVERY.md)：部署前检查、已验证范围、待甲方环境验证项和正式生产外部条件。
- [备份与恢复手册](docs/BACKUP_RESTORE.md)：SQLite 一致性备份、上传文件、Compose PostgreSQL／卷、隔离恢复和 RQ 一致性边界。
- [复验证据模板](docs/acceptance-evidence-template.md)：由最终复验人填写实际结果，不预设“全部通过”。

## 本地启动

要求：Python 3.12+、Node.js 22+。

```bash
# 1. 后端环境（项目已有 .venv 时可跳过创建与安装）
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. 前端依赖
npm install --prefix frontend

# 3. 同时启动 FastAPI 与 Vite
npm run dev -- --host 0.0.0.0 --port 7100
```

访问 `http://localhost:7100`。FastAPI 默认位于 `127.0.0.1:8017`，Vite 将 `/api` 代理到后端。`Ctrl+C` 会同时停止两个服务。若需修改后端端口，可使用 `API_PORT=8020 npm run dev`，启动器会同步更新前端代理。

也可以分别启动：

```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8017 --app-dir backend
npm run dev --prefix frontend -- --host 0.0.0.0 --port 7100
```

## Docker Compose 启动

要求：Docker 与 Docker Compose v2。无需模型密钥。

```bash
cp .env.example .env
# 修改 .env 中的 POSTGRES_PASSWORD；本地演示也可保留默认值

docker compose up --build -d
docker compose ps
```

访问 `http://localhost:8080`。Compose 启动前端、后端、RQ worker、PostgreSQL/pgvector 与 Redis。上传文件、数据库和 Redis 数据均使用命名卷持久化。

```bash
# 查看健康状态与日志
docker compose ps
docker compose logs -f backend worker

# 停止但保留数据
docker compose down

# 仅在确定要清空全部演示数据时
docker compose down -v
```

## 可选在线模型

在 `.env` 中设置：

```dotenv
LLM_API_KEY=你的服务端密钥
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=kimi-k2.5
```

密钥只由后端读取，不会发送到前端或写入审计记录。未配置时页面显示“离线可验收模式”。

## 推荐验收路径

1. **概览**：确认知识文档、订单、待审批与工单统计正常。
2. **知识问答**：输入 `7 天无理由退货需要满足哪些条件？`，展开引用，核对文档名、版本、定位与原文。
3. **无依据处理**：输入 `我们的售后政策支持永久退款吗？`，应明确提示依据不足且不伪造引用。
4. **订单查询**：输入 `查询订单 SQ100002 的物流状态`，查看结构化订单和工具记录。
5. **工单草案**：输入 `订单 SQ100001 想申请退货，请创建工单`，回答中只出现待审批草案。
6. **人工审批**：在审批中心修改申请原因或优先级，批准后得到 `GD` 开头工单号；重复批准不会重复创建。
7. **处理报告**：对已批准记录生成报告，编辑并下载 Markdown。
8. **文档管理**：上传一个包含企业政策的 TXT 或 MD 文件，观察处理状态、查看切片、重建索引或停用。
9. **固定集评测**：运行评测并展开逐用例结果，再查看审计事件与工具调用。

模拟订单：`SQ100001`—`SQ100006`。所有客户、商品、文档、订单与工单均为自行构造的演示数据。

## 测试与检查

```bash
# 后端：检索、拒答、上传、审批、幂等、评测、报告等
PYTHONPATH=backend .venv/bin/pytest backend/tests -q

# 前端：TypeScript 与生产构建
npm run build --prefix frontend

# 浏览器：独立测试数据库上的完整业务闭环
# 优先使用本机 Chrome；其他环境可先执行 npx playwright install chromium
npm run test:e2e --prefix frontend

# Compose 仅做静态配置检查；不能证明守护进程或容器运行通过
docker compose config --quiet
docker info

# 甲方异常路径独立副本 + 交付安全负控
.venv/bin/python scripts/run_delivery_regression.py --suite all

# 备份恢复工具安全测试（仅临时数据库和上传目录）
.venv/bin/python scripts/test_delivery_tools.py

# 关键源码、测试、文档与甲方材料版本指纹
.venv/bin/python scripts/version_fingerprint.py --output delivery-evidence/source-sha256.txt
```

端到端测试会自动启动独立服务、重建 `backend/data/e2e.db`、执行真实 Chrome 操作并在结束后清理进程，不会改写日常演示数据。交付回归把甲方原探针复制到 `frontend/artifacts/delivery-*` 新目录后执行，保留原证据；只有结果 JSON 中 `failed=0` 才算通过。安全探针包含隔离库的审计负控，详见[企业交付清单](docs/ENTERPRISE_DELIVERY.md)。

本地恢复只接受全新目标目录，Compose 恢复只接受显式的新项目和新卷；不要在日常数据上试验恢复。执行[备份与恢复手册](docs/BACKUP_RESTORE.md)中的隔离演练，并保留实际证据。Docker 守护进程不可用时，必须将 Compose、PostgreSQL、Redis/RQ 和卷恢复标为未实测。

API 文档：本地启动后访问 `http://127.0.0.1:8017/docs`。

## 项目结构

```text
enterprise-agent/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置与数据库
│   │   ├── data/          # 模拟政策与固定评测集
│   │   ├── services/      # 文档、检索、模型、工具、评测、审计
│   │   ├── main.py        # FastAPI API 边界
│   │   ├── models.py      # 业务数据实体
│   │   └── worker.py      # RQ 任务入口
│   └── tests/
├── frontend/
│   ├── src/views/         # 概览、问答、文档、审批、评测审计
│   ├── src/api.ts         # API 客户端与错误处理
│   └── src/styles.css     # 桌面工作台设计系统
├── scripts/
│   ├── dev.mjs                  # 双进程开发启动与退出清理
│   ├── run_delivery_regression.py # 甲方异常路径与安全回归入口
│   ├── delivery_backup.py       # SQLite／Compose 非覆盖备份
│   ├── delivery_restore.py      # 显式新目标隔离恢复
│   └── version_fingerprint.py   # 非 Git 目录的 SHA-256 基线
├── docs/                       # 交付、备份恢复与复验证据材料
├── docker-compose.yml
└── PRD.md
```

## 边界与技术取舍

- 这是**单 Agent + 确定性工作流**，不引入无必要的多智能体协作。
- 写操作没有绕过审批的 API；参数白名单、Schema、业务校验和幂等共同控制副作用。安全指标来自持久化 Ticket／Approval／审批审计关系，只说明该测量范围，不等于渗透测试或未知越权路径保证。
- 本地默认 SQLite 降低运行门槛；Compose 配置使用 PostgreSQL、Redis 和持久化卷，实机运行与 PostgreSQL 并发必须另行验证。
- 当前只支持文本型 PDF，不做扫描件 OCR；目标为桌面现代 Chrome / Edge，甲方独立实测为 Chrome，Edge 待复验，不支持移动端。
- 固定集指标只说明当前模拟环境，不代表企业生产质量；模型辅助评审没有替代人工金标。
- 不包含真实企业系统接入、复杂组织权限、模型训练、高并发 SaaS 或支付能力。正式生产前置条件见[企业交付清单](docs/ENTERPRISE_DELIVERY.md)。
