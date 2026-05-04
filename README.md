# NOI 错题诊断系统

面向 NOI / OpenJudge 练习场景的代码诊断系统。

系统分两端：

- 学生端：登录后提交代码，拿到只给提示、不直接给答案的 AI 引导。
- 教师端：查看学生提交、题面快照、学生提示，并在需要时生成完整诊断和参考程序。

当前线上方案：

- Web 主站：Flask
- 异步队列：Vercel Queues
- 生产部署：Vercel 连接 GitHub 仓库自动部署
- 生产数据库迁移：GitHub Actions

## 文档入口

- [PROJECT_STATUS.md](./PROJECT_STATUS.md)：当前架构、业务流程、数据模型和实现状态
- [TASK_QUEUE.md](./TASK_QUEUE.md)：任务记录、已完成项和待办

## 主要能力

- 统一登录入口 `/`
- 学生端双提交流程：`自己提交` / `提交给老师`
- 教师后台学生管理：创建、重置密码、禁用、启用
- 教师后台系统设置：切换 AI 模型，分别配置老师版 / 学生版系统提示词
- 学生端与教师端 AI 结果分流
- 提交记录软删除
- OpenJudge 抓题与 AI 诊断异步处理

## 目录结构

```text
api/
  queues/process-submission.js    Vercel Queue consumer
public/                           静态资源
scripts/
  prod-db-migrate.sh              生产库迁移脚本
  prepare-legacy-migration-state.py
src/
  app/
    routes/                       Flask 路由
    services/                     抓题、AI、队列、认证等服务
    models/                       数据模型
    templates/                    页面模板
  index.py                        Flask 入口
tests/                            pytest 测试
```

## 本地开发

### 1. 环境要求

- Python 3.12
- `uv`

### 2. 安装依赖

```bash
uv sync --extra dev
```

### 3. 配置环境变量

复制 `.env.example` 到 `.env`，本地开发至少建议使用这些值：

```env
FLASK_ENV=development
APP_ENV=development
DATABASE_URL=sqlite:///instance/dev.db
AI_API_KEY=your-test-key
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-pro
JOB_QUEUE_BACKEND=inline
BOOTSTRAP_ON_STARTUP=false
REQUIRE_PRODUCTION_ENV=false
APP_BASE_URL=http://127.0.0.1:5000
```

补充说明：

- 本地默认可以直接用 SQLite。
- `JOB_QUEUE_BACKEND=inline` 表示本地直接在请求链路内执行任务，便于联调。
- 若要本地初始化管理员账号，可设置 `ADMIN_INIT_USERNAME` 和 `ADMIN_INIT_PASSWORD`，并把 `BOOTSTRAP_ON_STARTUP=true`。

### 4. 启动服务

```bash
uv run flask --app src.index run --debug
```

默认地址：

```text
http://127.0.0.1:5000
```

## 数据库与迁移

### 本地迁移

```bash
uv run flask --app src.index db upgrade
```

如果需要新建迁移：

```bash
uv run flask --app src.index db migrate -m "描述"
uv run flask --app src.index db upgrade
```

### 生产迁移

生产环境通过 GitHub Actions 执行：

- Workflow：`.github/workflows/prod-db-migrate.yml`
- 脚本：`scripts/prod-db-migrate.sh`

需要在 GitHub 仓库 Secrets 中配置：

- `MIGRATION_DATABASE_URL`

说明：

- workflow 在 `main` 分支 push 时自动运行。
- 脚本会先执行历史库 Alembic 基线补写，再执行 `flask db upgrade`。
- 这套流程就是为了适配 Vercel 直接导入 GitHub 仓库的部署方式。

如果要手动跑迁移：

```bash
bash scripts/prod-db-migrate.sh
```

前提是当前环境已设置 `DATABASE_URL` 或 `MIGRATION_DATABASE_URL`。

## 测试

跑全量测试：

```bash
uv run pytest -q
```

只跑某个文件：

```bash
uv run pytest tests/test_admin_submission_management.py -q
```

## 生产部署

### Vercel

这个项目当前按下面方式部署：

1. Vercel 直接连接 GitHub 仓库。
2. 推送到 `main` 后，Vercel 自动构建并发布 Web 站点。
3. 同一次 push 会触发 GitHub Actions 跑生产数据库迁移。

`vercel.json` 当前配置了队列 consumer：

- 入口：`api/queues/process-submission.js`
- topic：`noi_submission_jobs`

### 必要环境变量

建议直接参考 `.env.example`。生产至少要确认这些变量：

- `SECRET_KEY`
- `DATABASE_URL`
- `AI_API_KEY`
- `AI_BASE_URL`
- `AI_MODEL`
- `ADMIN_INIT_USERNAME`
- `ADMIN_INIT_PASSWORD`
- `JOB_QUEUE_BACKEND=vercel`
- `VERCEL_QUEUE_REGION`
- `VERCEL_QUEUE_TOPIC=noi_submission_jobs`
- `INTERNAL_JOB_TOKEN`
- `APP_BASE_URL`

兼容说明：

- AI 配置支持新变量名 `AI_*`
- 也兼容旧变量名 `DEEPSEEK_*`

## 线上回归建议

发版后建议至少回归这些链路：

- 首页与登录页可访问
- 教师登录、学生登录、退出
- 学生创建账号、重置密码、启停用
- 学生 `自己提交`
- 学生 `提交给老师`
- 教师列表筛选、详情查看、删除记录
- 异步抓题与 AI 状态流转

## 当前已知边界

- 学生端 AI 是提示链路，不是实际编译执行判题。
- OpenJudge 抓题依赖目标站点可访问性。
- 线上稳定性仍然依赖队列、外部抓题和模型接口。

## 补充

如果你想看更细的实现状态、字段设计和业务流转，直接看 [PROJECT_STATUS.md](./PROJECT_STATUS.md)。
