# 企业演示／单机关试点交付清单

## 1. 交付定位

本包面向**隔离、受信、单机或小型试点环境中的流程演示与验收**。它提供可复现的离线业务闭环、异常路径探针、版本指纹和备份恢复工具，不是正式规模生产系统，也不构成高可用、等保、渗透测试、企业身份治理或大数据量性能承诺。

- 甲方初始结论与原始证据：`frontend/artifacts/client-acceptance/initial-report.md`，该目录中的原报告和原探针不修改。
- 甲方最终复验报告：`frontend/artifacts/client-acceptance/final-report.md`，独立实测证据位于 `frontend/artifacts/client-acceptance/final/`。
- 备份恢复手册：[`docs/BACKUP_RESTORE.md`](BACKUP_RESTORE.md)。
- 复验记录模板：[`docs/acceptance-evidence-template.md`](acceptance-evidence-template.md)。
- 最终交付应以同一版本指纹下的复验结果为准，不能用本文中的工具自检代替甲方签收复验。

## 1.1 本轮甲方最终复验结论

**企业演示／受信单机试点交付通过；正式规模生产放行不在本结论范围内。**

- 原 P0 为 0 项；P1 5／5、P2 8／8 关闭；新增 P0／P1／P2 均为 0。
- 甲方独立执行 43／43 项通过：HTTP 25 项、真实 Chrome 9 项、旧库迁移 3 项、本地备份恢复 6 项。
- 交付方集成验证另行通过：后端 42 项、浏览器 10 项、交付工具 7 项，以及独立 HTTP 27／27、浏览器 8／8、安全 6／6。
- 日常演示库 11 张表行级数据未变，数据库及上传文件 48／48 哈希一致；本轮探针端口均已释放。
- Compose、PostgreSQL／pgvector、Redis／RQ、Compose 恢复、在线模型、Edge 和规模性能仍未实测，详见第 6 节及甲方最终报告。

## 2. 部署前检查

### 环境与生境

- [ ] 操作系统、Python 3.12+、Node.js 22+、npm、桌面 Chrome 版本已记录。
- [ ] `.venv` 依赖来自 `backend/requirements.txt`，前端依赖已由锁文件安装。
- [ ] 部署目录有读写权限，磁盘容量覆盖数据库、上传文件、日志和备份。
- [ ] 演示数据不含真实客户秘密；模型密钥和数据库密码由受控秘密渠道提供，不写入证据。
- [ ] 服务仅绑定受信网络；未接入真实身份前不暴露到非受信网络或多人生产环境。

### 配置与版本

- [ ] `docker compose config --quiet` 在实际部署环境成功。
- [ ] Docker 场景另执行 `docker info`，确认守护进程真正可用；静态配置成功不等于容器可运行。
- [ ] 已设置非默认 `POSTGRES_PASSWORD`，并核对 CORS、端口、模型配置和上传存储位置。
- [ ] 已生成 `source-sha256.txt`，交付、复验和备份使用同一批源码与材料。
- [ ] 已阅读[备份恢复手册](BACKUP_RESTORE.md)，明确维护窗口、备份位置、保留策略、加密和恢复负责人。

### 验收与退出

- [ ] 后端测试、前端构建、浏览器主闭环和交付异常路径均保留命令、退出码和结果文件。
- [ ] 备份工具安全测试通过；在目标环境完成隔离恢复演练并核对业务数据。
- [ ] 所有由探针启动的 Uvicorn、Vite、Chrome 和临时 Compose 项目均已停止或按演练约定保留，未误留进程。
- [ ] 未验证项已写入交付记录，没有用“全部通过”覆盖环境限制。

## 3. 本轮交付侧实际自检（范围受限）

以下为交付工具整改期间的实测，不是甲方最终复验结论：

| 项目 | 实际结果 | 证据 |
|---|---|---|
| 备份／恢复工具安全测试 | 7 项通过：临时 SQLite 往返、源库不变、输出与恢复不覆盖、确认路径、防篡改、防递归、指纹不覆盖 | `delivery-evidence/tool-safety-tests.txt` |
| Python 静态编译 | 本轮交付脚本 `py_compile` 成功 | `delivery-evidence/python-compile.txt` |
| 甲方 HTTP 探针独立副本 | 27／27 通过，包含 5 轮每轮 8 路并发；使用独立数据库，原探针未修改 | `frontend/artifacts/delivery-http-toolcheck/delivery-summary.json` |
| 甲方浏览器探针兼容副本 | 8／8 通过，使用独立数据库与真实 Chrome；仅运行副本适配修复后的可见状态 | `frontend/artifacts/delivery-browser-toolcheck-2/delivery-summary.json` |
| 交付安全探针 | 6／6 通过：草案未批不写、拒绝不写、顺序重复一张、8 路并发一张、审计派生指标负控 | `frontend/artifacts/delivery-security-toolcheck-2/security-results.json` |
| 安全指标负控 | 隔离库注入一条无审批审计的孤儿工单后，`unapproved_writes` 从 0 变为 1；不接触日常库 | 同上，`independent_derivation` |
| Compose 静态配置 | `docker compose config --quiet` 退出码 0 | `delivery-evidence/compose-config.txt` |
| Docker 守护进程 | `docker info` 退出码 1，当前无法做实机容器验证 | `delivery-evidence/docker-info.txt` |

首次安全工具自检曾因探针自身变量命名冲突中止，保留在 `frontend/artifacts/delivery-security-toolcheck/`；修正后使用全新目录得到上述 6／6 结果。首次浏览器副本也因原探针等待已被修复清除的旧订单元素而超时，保留在 `frontend/artifacts/delivery-browser-toolcheck/`；兼容副本得到上述 8／8 结果。失败记录均未被覆盖。

## 4. 可重复交付回归入口

在项目根目录执行：

```bash
# 全量交付异常路径：HTTP + 浏览器 + 安全负控
.venv/bin/python scripts/run_delivery_regression.py --suite all

# 也可分项执行
.venv/bin/python scripts/run_delivery_regression.py --suite http
.venv/bin/python scripts/run_delivery_regression.py --suite browser
.venv/bin/python scripts/run_delivery_regression.py --suite security
```

也可指定新的证据目录，但必须是 `frontend/artifacts/` 的直接子目录：

```bash
.venv/bin/python scripts/run_delivery_regression.py \
  --suite all \
  --output-dir "frontend/artifacts/delivery-final-001"
```

工作方式与预期：

1. 包装器把甲方两项探针复制到本次运行目录，利用相同目录深度定位项目根目录；数据库、日志、JSON 和截图全部写入新目录。HTTP 副本不变；浏览器副本只做下述新状态兼容适配。
2. 包装器记录原探针 SHA-256，运行后再次核对，不修改 `frontend/artifacts/client-acceptance/` 中的原始报告、探针或历史结果。浏览器适配后的副本哈希另记在交付摘要。
3. 只有进程退出码为 0 且结果 JSON 的 `failed=0` 才判定该套件通过；原探针即使打印 FAIL 也可能自行退出 0，不能只看 shell 退出码。
4. HTTP 覆盖并发／冲突审批、非法 modifications、报告跨关联、审计原始参数、文档异常等甲方路径。
5. 浏览器覆盖断网、刷新恢复、旧订单清理、失败输入保留、长文本、XSS、拒绝确认等路径。运行副本允许已修复的旧订单面板和假空库文案“不存在”，并将可见 `.error-state` 与旧 toast 都计为错误提示；不断言旧错误必须出现，也不放宽健康假象、旧订单残留等原有判定。任何执行异常仍记为未通过。
6. 安全探针使用独立 SQLite，先验证草案、拒绝、顺序与并发幂等，再独立读取 Ticket 与审批审计计算未审批工单数。最后仅向隔离库注入一条合成孤儿工单，验证指标随证据从 0 增至 1。
7. 安全指标只表示持久化 Ticket／Approval／审批审计关系一致性，不是渗透测试，也不能证明所有未知越权路径不存在。
8. 每次运行生成 `run-manifest.json`、`source-sha256.txt`、各套件执行日志和 `delivery-summary.json`。交付摘要较大，控制台只显示精简计数。

## 5. 版本指纹

项目不是 Git 仓库，不自行初始化或提交。生成目录基线：

```bash
.venv/bin/python scripts/version_fingerprint.py \
  --output "delivery-evidence/source-sha256.txt"
```

默认拒绝覆盖；确需为新一轮复验更新同一文件时，显式使用 `--overwrite`，并保留旧证据副本。指纹覆盖关键后端／前端源码、既有测试、交付脚本、文档、Compose、依赖锁文件、甲方原报告和两项原探针，不包含 `.env`、日常数据库、上传文件、`node_modules` 或运行产物。

## 6. 待甲方环境验证

以下项目当前没有实测依据，不得宣称通过：

1. **Compose 实机**：镜像构建、容器启动与停止、健康检查、PostgreSQL/pgvector、Redis/RQ worker、命名卷持久化。
2. **Compose 恢复**：`pg_dump`／`pg_restore`、上传卷归档恢复、隔离项目业务核验及清理。
3. **PostgreSQL 并发**：SQLite 的并发结果不能外推到 PostgreSQL，必须重跑同类 approve/approve 与 approve/reject 组合。
4. **在线模型与降级**：真实密钥、回答质量、超时、限流、密钥外部传输和降级行为。
5. **Edge**：当前独立探针使用 Chrome，Edge 需实机复验。
6. **规模与资源**：大知识库、超大文档、多用户并发、RQ 积压、CPU／内存／磁盘压力和备份恢复耗时。
7. **扫描件 OCR**：产品明确不支持，不作为已通过功能。

## 7. 正式规模生产的外部前置条件

这些不应被“企业演示／单机关试点可交付”措辞掩盖：

- 真实身份认证、组织／角色权限、最小授权、SSO、租户隔离；当前“演示管理员”不是安全身份。
- 上传内容类型嗅探、病毒扫描、解压炸弹防护、限流、配额、存储生命周期和敏感数据治理。
- 数据库／向量索引、分页检索、资源限额，以及面向目标数据量的性能预算和压测。
- Alembic 或等效 schema 版本迁移、升级／回滚演练；`create_all` 不是正式迁移体系。
- 数据库、Redis、worker 的深度就绪／存活探针，结构化日志、指标、告警、轮转与容量管理。
- 完整审计分页、不可篡改存储、留存策略、用户／请求关联和合规归档；当前 API 截断列表不能承担合规归档。
- 企业秘密管理、TLS、网络安全组、密钥轮换、最小网络暴露和默认密码替换。
- 高可用、异地灾备、明确 RPO／RTO、定期恢复演练和应急响应。
- 前端路由拆包和性能预算；主包大小不影响本地试点，但应纳入生产优化。

## 8. 最终签收材料

主 Agent／交付负责人应在版本冻结后填写[验收证据模板](acceptance-evidence-template.md)，至少附：

- 环境、时间、执行人、源码指纹与配置差异说明；
- 基线测试、构建、HTTP、浏览器、安全探针的实际摘要和证据路径；
- 本地与 Compose 备份恢复的实际演练结果，未执行则明确标注；
- 所有剩余失败、超时、环境限制和未实测项；
- 进程与临时资源清理记录；
- 甲方对“企业演示／单机关试点”边界的确认，而非正式生产认可。
