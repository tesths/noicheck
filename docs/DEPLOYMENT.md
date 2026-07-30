# 生产部署与运维手册

更新时间：2026-07-29

本文记录当前生产部署、环境变量、迁移和线上核查方式。面向接手维护的人，优先保证能复现部署状态和排查队列问题。

## 当前线上状态

通过 Vercel CLI 于 2026-07-29 核查：

- Vercel scope：`tesths-projects`
- Vercel project：`noicheck`
- 线上主域名：`https://noi.bbbypw.online`
- 当前 production deployment：`dpl_BWcvBs2zbsMAmUxRukZ4nHaRJi5u`
- deployment 状态：`Ready`
- deployment 创建时间：2026-07-20 11:19:30 CST
- deployment URL：`https://noicheck-5h3f3r2xj-tesths-projects.vercel.app`
- 线上别名：
  - `https://noi.bbbypw.online`
  - `https://noicheck.vercel.app`
  - `https://noicheck-tesths-projects.vercel.app`
  - `https://noicheck-git-main-tesths-projects.vercel.app`

当前项目设置：

- Root Directory：`.`
- Framework Preset：Flask
- Install Command：`pip install -r requirements.txt`
- Build Command：None
- Output Directory：None
- Node.js Version：24.x

当前部署输出：

| 输出 | Runtime | Region | Timeout | 说明 |
| --- | --- | --- | --- | --- |
| `index` | Python 3.12 | `iad1` | 300s | Flask 主站 |
| `api/queues/process-submission` | Node.js 24.x | `iad1` | 60s | Vercel Queue consumer |

`vercel.json` 配置的队列 consumer：

- 入口：`api/queues/process-submission.js`
- trigger：`queue/v2beta`
- topic：`noi_submission_jobs`
- maxDuration：60s

## Vercel CLI 核查

如果本机走代理，Vercel CLI 58 不支持 `socks5h:` 作为代理协议。核查 Vercel 时只设置 HTTP 代理端口：

```bash
export http_proxy=http://127.0.0.1:21081
export HTTP_PROXY=http://127.0.0.1:21081
export https_proxy=http://127.0.0.1:21081
export HTTPS_PROXY=http://127.0.0.1:21081
```

查看当前域名指向的部署：

```bash
vercel inspect https://noi.bbbypw.online
vercel inspect https://noi.bbbypw.online --format=json
```

查看项目配置：

```bash
vercel project inspect noicheck
```

查看最近部署列表：

```bash
vercel ls --yes
```

如需核对环境变量名称，可以先链接本地项目，再查看 production 变量列表。不要把 `.vercel/` 提交到仓库，当前 `.gitignore` 已忽略该目录。

```bash
vercel link --project noicheck
vercel env list production
```

## 环境变量

生产环境以 `.env.example` 为模板。Vercel 上至少要确认这些变量：

| 变量 | 用途 | 备注 |
| --- | --- | --- |
| `SECRET_KEY` | Flask session 和 CSRF 密钥 | 必须替换成强随机值 |
| `DATABASE_URL` | 生产数据库 | 必须是公网 Postgres |
| `AI_API_KEY` | AI 服务密钥 | 不要写入仓库 |
| `AI_BASE_URL` | AI 服务地址 | 默认可用 DeepSeek 地址 |
| `AI_MODEL` | 默认模型名 | 当前后台只支持 `deepseek-v4-flash` / `deepseek-v4-pro` |
| `ADMIN_INIT_USERNAME` | 初始教师账号 | 首次部署或重建管理员时使用 |
| `ADMIN_INIT_PASSWORD` | 初始教师密码 | 必须替换 |
| `BOOTSTRAP_ON_STARTUP` | 启动时自动建表和初始化管理员 | 已有管理员后可设为 `false` |
| `REQUIRE_PRODUCTION_ENV` | 生产配置校验 | 生产建议 `true` |
| `JOB_QUEUE_BACKEND` | 队列后端 | 生产设为 `vercel` |
| `VERCEL_QUEUE_REGION` | Vercel Queue 区域 | 当前使用 `iad1` |
| `VERCEL_QUEUE_TOPIC` | Vercel Queue topic | 当前为 `noi_submission_jobs` |
| `INTERNAL_JOB_TOKEN` | Queue consumer 调 Flask 内部接口的鉴权 token | 必须和 Vercel 环境一致 |
| `APP_BASE_URL` | Flask 主站对外地址 | 生产应指向正式域名或当前 production alias |

稳定性和容量相关变量：

| 变量 | 默认建议 | 说明 |
| --- | --- | --- |
| `JOB_QUEUE_PUBLISH_TIMEOUT_SECONDS` | `3` | 提交链路内投递 Vercel Queue 的超时 |
| `JOB_QUEUE_PUBLISH_MAX_ATTEMPTS` | `2` | 队列投递最大尝试次数 |
| `JOB_QUEUE_PUBLISH_RETRY_BACKOFF_SECONDS` | `0.2` | 队列投递重试间隔 |
| `JOB_INTERNAL_REQUEST_TIMEOUT_SECONDS` | `15` | Node consumer 调内部任务接口的超时 |
| `JOB_INTERNAL_MAX_RETRIES` | `1` | 内部任务接口调用重试次数 |
| `SQLALCHEMY_POOL_SIZE` | `5` | Postgres pool_size，代码会做最小值兜底 |
| `SQLALCHEMY_MAX_OVERFLOW` | `10` | Postgres max_overflow，代码会做最小值兜底 |
| `SQLALCHEMY_POOL_TIMEOUT` | `10` | 获取数据库连接的等待时间，代码会做最小值兜底 |
| `AI_CONCURRENCY_LIMIT_STUDENT` | `8` | 学生提示 AI 并发上限 |
| `AI_CONCURRENCY_LIMIT_TEACHER` | `4` | 教师诊断 AI 并发上限 |
| `FETCH_CONCURRENCY_LIMIT` | `8` | OpenJudge 抓题并发上限 |
| `PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS` | `86400` | 同题题面快照复用窗口 |

兼容旧变量：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`

新部署建议直接使用 `AI_*` 变量。旧变量只用于兼容历史环境。

## 数据库迁移

生产迁移由 GitHub Actions 执行：

- Workflow：`.github/workflows/prod-db-migrate.yml`
- 触发条件：push 到 `main`，或手动 `workflow_dispatch`
- GitHub Secret：`MIGRATION_DATABASE_URL`
- 执行脚本：`scripts/prod-db-migrate.sh`

脚本执行顺序：

1. 输出 Alembic heads。
2. 运行 `scripts/prepare-legacy-migration-state.py`，补齐旧库 Alembic 状态。
3. 执行 `uv run flask db upgrade`。
4. 执行 `uv run flask clean-followup-history`，清洗旧版追问消息。

本地手动迁移前，先确认当前 shell 有 `DATABASE_URL` 或 `MIGRATION_DATABASE_URL`：

```bash
bash scripts/prod-db-migrate.sh
```

只想预览历史追问清洗影响时：

```bash
uv run flask clean-followup-history --dry-run
```

## 验证命令

Python 测试：

```bash
uv run pytest -q
```

覆盖率：

```bash
uv run --with coverage coverage run -m pytest -q
uv run --with coverage coverage report --fail-under=95
```

Node Queue consumer 测试：

```bash
node --test tests/node/process-submission.test.cjs
```

样式和静态检查：

```bash
uv run ruff check
```

验证前先确认本机安装了 `uv` 和 Node.js 24.x。Vercel 当前项目设置也是 Node.js 24.x，Queue consumer 测试应尽量使用同一主版本。

## 线上回归清单

发版后至少回归：

- 首页与学生、教师登录页可访问。
- 教师登录、学生登录、退出。
- 教师创建学生、重置密码、停用、启用。
- 学生 `自己提交`，确认学生提示生成。
- 学生 `提交给老师`，确认教师端完整诊断生成。
- 学生提交详情右侧追问抽屉，覆盖打开、关闭、多轮追问和跑题拒答。
- 教师提交列表筛选、详情查看、软删除。
- 教师学生视角预览，确认追问抽屉只读。
- 异步抓题与 AI 状态从 `queued` / `running` 进入 `success` 或有明确失败原因。

## 排错入口

Queue consumer 主要错误信号：

- `Queue consumer received unsupported payload shape ...`：consumer 没拿到可解析 body，也没有识别到可回拉 payload 的 CloudEvent 元数据。
- `queue_message_fetch_failed`：已识别 Queue CloudEvent，但回拉 Vercel Queue API 失败。继续检查 OIDC token、region、deployment id 和 Queue API 响应。
- `missing_internal_job_config`：`APP_BASE_URL` 或 `INTERNAL_JOB_TOKEN` 未配置。
- `internal_processor_unreachable`：Node consumer 无法访问 Flask 内部任务接口，检查 `APP_BASE_URL`、网络、函数状态和 `JOB_INTERNAL_REQUEST_TIMEOUT_SECONDS`。

AI 结果异常时优先检查：

- `AI_API_KEY` 是否存在。
- `AI_BASE_URL` 和 `AI_MODEL` 是否匹配供应商。
- 后台系统设置中的当前模型是否仍是允许值。
- 模型是否返回合法 JSON。解析层已做容错，但仍可能失败。

数据库异常时优先检查：

- `DATABASE_URL` 是否指向生产 Postgres。
- GitHub Actions 的 `MIGRATION_DATABASE_URL` 是否和 Vercel 生产库一致。
- 最新一次 `Production DB Migrate` workflow 是否成功。
- Postgres 连接池变量是否和预期一致。
