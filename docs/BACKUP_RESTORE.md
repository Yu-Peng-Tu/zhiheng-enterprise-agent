# 备份与恢复运行手册（企业演示／单机关试点）

本文对应甲方 P2-07。目标是让本地 SQLite 与 Docker Compose 部署都有可执行、可核验、默认不覆盖日常数据的备份恢复路径。这里的“可恢复”不等同于正式生产级灾备，也不承诺未实测的 RPO／RTO。

> 所有命令默认在项目根目录 `enterprise-agent/` 执行。脚本也用自身位置定位项目根目录，因此从其他当前目录调用时仍可使用，但建议统一在根目录操作。路径含空格或中文时必须加引号。

## 1. 数据范围与一致性边界

| 数据 | 本地默认位置 | Compose 位置 | 备份方式 |
|---|---|---|---|
| 业务数据库 | `backend/data/app.db` | PostgreSQL `zhiheng` | Python `sqlite3.Connection.backup()`／`pg_dump` 自定义格式 |
| 上传文件 | `backend/data/uploads/` | `app-data` 命名卷 | 普通文件树复制／`tar` 归档 |
| 配置与版本材料 | Compose、依赖锁文件、`.env.example` 等 | 同左 | 只读快照与 SHA-256 清单 |
| Redis／RQ 队列 | 本地通常不使用 | `redis-data` 命名卷 | **不纳入恢复承诺** |

关键边界：

1. SQLite 在线备份 API 能取得一致性数据库快照，但数据库与上传目录之间不是分布式事务。要严格对齐两者，应安排维护窗口并停止上传、审批和其他写入。
2. Compose 备份脚本会拒绝在 `backend` 或 `worker` 运行时执行。先排空或停止写入，再备份 PostgreSQL 与上传卷。
3. Redis/RQ 的 queued、started、failed 等任务状态不与 PostgreSQL 同事务保存。简单复制 Redis 文件也不能证明队列与业务库一致，因此本工具不备份或恢复队列。恢复后应检查 `queued`／`running` 任务，依据文档当前状态人工重试；不得把旧队列重复执行当作安全恢复。
4. SHA-256 只能发现意外变化，不能证明备份来源可信，也不能加密数据。备份清单不记录 `.env`、模型密钥或数据库密码。
5. 上传目录中的符号链接、设备文件等特殊项会被拒绝，避免备份读取目录外内容或恢复不安全归档。

## 2. 备份前检查

- 确认当前数据库和上传目录；非默认 SQLite 路径必须显式传给 `--database`。
- 为严格一致性安排维护窗口，停止写入；记录正在执行的文档任务与审批操作。
- 确认目标备份卷有足够空间、可写，并且不是上传目录的子目录。
- 将数据库密码、模型密钥等秘密放在甲方认可的密码／秘密管理系统中单独备份；不要把 `.env` 放进交付包。
- 明确备份负责人、保留周期、异地副本、恢复目标与演练频率。

## 3. 本地 SQLite：备份

在线备份命令：

```bash
.venv/bin/python scripts/delivery_backup.py local \
  --database "backend/data/app.db" \
  --uploads "backend/data/uploads" \
  --output-dir "/absolute/path/to/backups/zhiheng-local-001"
```

`--database` 和 `--uploads` 可省略，默认值如上。`--output-dir` 必须显式指定且不存在；脚本拒绝覆盖既有目录，也拒绝把备份写进上传目录。备份先写入同文件系统的临时目录，完成后原子改名。

输出结构：

```text
zhiheng-local-001/
├── database.sqlite3          # sqlite3 backup API 生成的一致性快照
├── uploads/                  # 上传文件原目录结构
├── config/                   # 非秘密配置与依赖材料快照
├── version/source-sha256.txt # 关键源码、测试、文档和甲方探针指纹
├── manifest.json             # 表行数、文件数、大小、哈希与一致性说明
└── SHA256SUMS.txt            # 包括 manifest.json 在内的载荷校验
```

脚本会立即对快照执行 `PRAGMA quick_check` 并记录各表行数。目录和文件权限会尽量收紧为仅当前用户可读写（POSIX 下 `0700`／`0600`）。

macOS 可另做人工校验：

```bash
cd "/absolute/path/to/backups/zhiheng-local-001"
shasum -a 256 -c SHA256SUMS.txt
```

## 4. 本地 SQLite：恢复到全新目录

恢复脚本会验证清单和每个载荷的哈希、检查 tar／路径安全性（如适用）、执行 SQLite `quick_check`、比较所有表行数，并核对上传文件数量与总字节数。

```bash
.venv/bin/python scripts/delivery_restore.py local \
  --backup-dir "/absolute/path/to/backups/zhiheng-local-001" \
  --target-dir "/absolute/path/to/recovery/zhiheng-restored-001" \
  --confirm-target "/absolute/path/to/recovery/zhiheng-restored-001"
```

防误操作规则：

- `--target-dir` 与 `--confirm-target` 解析后的绝对路径必须完全一致。
- 目标目录必须不存在；**没有覆盖模式**。既有文件、日常 `backend/data`、旧恢复目录都不会被清空或替换。
- 恢复先写临时目录，核验通过后才改名为目标目录；失败会清理临时目录。
- 配置快照只供人工复核，不会自动覆盖当前配置。

恢复结果：

```text
zhiheng-restored-001/
├── app.db
├── uploads/
└── RESTORE_INFO.json          # 实际表行数、上传文件数与来源 manifest 哈希
```

### 4.1 恢复后业务核验

先检查恢复信息：

```bash
.venv/bin/python -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])), ensure_ascii=False, indent=2))' \
  "/absolute/path/to/recovery/zhiheng-restored-001/RESTORE_INFO.json"
```

应用切换不能只设置 `DATABASE_URL`，因为当前上传目录仍由应用固定为 `backend/data/uploads`。正式切换前应：

1. 停止本地前后端，确认没有写入进程。
2. 再用第 3 节命令为**当前日常数据**生成一份新的安全备份。
3. 在甲方批准的维护窗口，将原 `backend/data` 整体移动到有独立保护的历史目录；不要使用 `rm -rf`。
4. 将已验证恢复目录中的 `app.db` 与 `uploads/` 复制到 `backend/data/`，确认属主和权限正确。
5. 启动应用，依次检查 `/api/health`、`/api/dashboard`、`/api/documents`、`/api/approvals`、`/api/tickets`，抽查一条引用、一条审批和一条工单。
6. 核对恢复前 `manifest.json` 的表行数与恢复后数据；若启动后种子数据或新业务写入改变行数，应在记录中解释差异。
7. 确认队列／任务状态。未完成的文档任务根据文档状态人工重试，不恢复旧 RQ 队列。

恢复脚本故意不自动执行第 3—4 步，避免把“恢复演练”误变成“覆盖日常数据”。

## 5. Compose：备份 PostgreSQL 与上传卷

前置条件：Docker 守护进程可用，现有 Compose 已正常运行。`docker compose config --quiet` 只检查静态配置，不证明守护进程、镜像、数据库、Redis 或卷可用。

### 5.1 排空并停止写入

```bash
docker compose ps
# 可选观察默认队列；非 0 时先决定完成、取消或恢复后重试，不要直接忽略。
docker compose exec -T redis redis-cli LLEN rq:queue:default

docker compose stop backend worker
```

### 5.2 执行备份

```bash
.venv/bin/python scripts/delivery_backup.py compose \
  --output-dir "/absolute/path/to/backups/zhiheng-compose-001"
```

脚本将：

- 再次确认 `backend`／`worker` 不在运行，`postgres` 正在运行；
- 通过 `pg_dump --format=custom --no-owner --no-privileges` 写入 `database.pgdump`；
- 通过一次性 backend 容器把 `app-data` 卷写为 `uploads-volume.tar`；
- 检查归档路径、文件数、配置快照与版本指纹；
- 拒绝覆盖已有输出。

完成后恢复服务：

```bash
docker compose start backend worker
docker compose ps
```

若备份命令失败，也应在排查后按需执行 `docker compose start backend worker`；脚本不会擅自重启业务。

## 6. Compose：隔离恢复演练

恢复只接受一个新的 Compose 项目名，并拒绝：

- 使用日常演示项目名；
- 目标 `postgres-data` 或 `app-data` 卷已存在；
- 目标项目已有容器；
- 项目名与确认名不一致。

### 6.1 自动核验并清理的演练

```bash
.venv/bin/python scripts/delivery_restore.py compose \
  --backup-dir "/absolute/path/to/backups/zhiheng-compose-001" \
  --project-name "zhiheng-restore-001" \
  --confirm-project "zhiheng-restore-001" \
  --cleanup-after-verify
```

该命令只启动隔离项目的 PostgreSQL，并通过一次性容器恢复上传卷；不会启动 backend／worker。它使用 `pg_restore` 和 `psql` 核验关键表，再比较上传文件数。`--cleanup-after-verify` 只删除刚创建的隔离项目及其新卷；失败时也会尝试清理该新项目。

### 6.2 保留隔离环境做应用核验

去掉 `--cleanup-after-verify` 执行同一恢复命令，然后：

```bash
docker compose -p zhiheng-restore-001 up -d backend worker
docker compose -p zhiheng-restore-001 ps
docker compose -p zhiheng-restore-001 exec -T backend \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())"
docker compose -p zhiheng-restore-001 exec -T backend \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/dashboard').read().decode())"
```

此时 Redis 是新项目的空队列，不包含旧任务。完成核验后：

```bash
# 保留恢复卷，停止容器
docker compose -p zhiheng-restore-001 down

# 仅当明确结束隔离演练且不再需要恢复卷时
docker compose -p zhiheng-restore-001 down -v
```

不要在日常项目名上执行 `down -v`。真实灾难切换需要甲方批准、最新安全备份、网络／端口／秘密配置复核和业务核验，本脚本不自动替换日常 Compose 卷。

## 7. 加密、权限与保留建议

- 传输和离线保存时使用甲方批准的工具加密，例如 age／GPG 或企业备份系统；密钥与备份分离保管，并验证密钥恢复流程。
- 备份账户只读源数据、只写专用备份区；恢复使用独立受控账户。限制备份目录、对象存储和管理员终端权限。
- 至少保留一份异地／离线副本，可采用 3-2-1 思路。定期核对备份可读性与哈希。
- 试点可从“每日保留 7 份、每周保留 4 份、每月保留 3 份”起步，最终按甲方数据分级、法规和 RPO 调整；不要机械套用。
- 至少每季度做一次隔离恢复演练，记录备份时间、版本指纹、恢复耗时、核验结果、差异和整改人。
- 日志、备份与证据不得包含真实客户敏感信息、`.env`、模型密钥或数据库密码。

## 8. 工具自身安全测试

以下测试只在 `delivery-evidence/tmp/` 下创建临时数据库和上传文件，结束后自动删除：

```bash
.venv/bin/python scripts/test_delivery_tools.py
```

覆盖：临时库完整往返、源库不变、备份不覆盖、恢复不覆盖、确认路径、防篡改、防递归备份、指纹格式与不覆盖。它不替代真实 PostgreSQL／Compose 恢复演练。
