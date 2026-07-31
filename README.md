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

当前生产部署状态：

- 2026-07-29 通过 Vercel CLI 核查，`https://noi.bbbypw.online` 指向 `tesths-projects/noicheck`
- 当前 production deployment：`dpl_BWcvBs2zbsMAmUxRukZ4nHaRJi5u`
- deployment 状态：`Ready`
- Flask 主站运行在 Python 3.12 lambda，Queue consumer 运行在 Node.js 24.x lambda，区域均为 `iad1`

最近一次界面与测试回归结论：

- 2026-07-20 已完成全站 daisyUI 组件化视觉迁移
- 当前主题以棕色为主，`btn-primary`、表单、表格、卡片均使用 daisyUI 默认组件形态
- 已移除旧的自定义按钮类与大圆角 / 阴影式旧样式，保留少量结构布局 CSS
- 已用 Playwright 检查桌面端 `1280px` 与移动端 `375px` 的按钮颜色、输入框 / 按钮对齐和横向溢出
- 本地回归 `uv run pytest -q`：`179 passed`
- 覆盖率回归 `uv run --with coverage coverage report --fail-under=95`：总覆盖率 `98%`

最近一次稳定性回归结论：

- 2026-05-17 已定点修复一轮线上 `500` 与慢请求问题
- 真站 `https://noi.bbbypw.online/` 已完成学生 self-check `5` 并发、`8` 并发压测
- `8` 并发实测 `8/8` 成功，提交页 `302`、详情页 `200`
- 本轮压测下提交请求耗时约 `1.6s ~ 1.9s`，整条跳转链路约 `3.8s ~ 4.3s`

## 文档入口

- [PROJECT_STATUS.md](./PROJECT_STATUS.md)：当前架构、业务流程、数据模型和实现状态
- [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)：生产部署、环境变量、Vercel CLI 核查、迁移和排错
- [docs/PLATFORM_RESEARCH.md](./docs/PLATFORM_RESEARCH.md)：免费部署多个 Python 项目的平台调研结论
- [TASK_QUEUE.md](./TASK_QUEUE.md)：任务记录、已完成项和待办

## 主要能力

- 统一登录入口 `/`
- 学生端双提交流程：`自己提交` / `提交给老师`
- 学生提交详情右侧追问抽屉：保留原始代码和学生提示，支持围绕当前题目继续多轮追问
- 学生端薄弱点行动版：在“我的提交”汇总重复知识点 / 错因，给出复盘动作和证据题链接
- 追问链路只回答题目相关的编程问题，跑题内容会统一拒答并引导回代码、输入输出和调试
- 教师可从学生视角查看同一套追问记录抽屉（只读）
- 教师后台学生管理：创建、批量导入、重置密码、禁用、启用（每位老师仅能管理自己创建的学生）
- 教师后台任务健康页：按抓题、学生提示、老师诊断分类查看失败和处理中任务
- 内部任务健康 JSON 端点：供外部监控轮询汇总状态，不暴露学生或题目明细
- 教师后台系统设置：切换 AI 模型，分别配置老师版 / 学生版系统提示词
- 学生端与教师端 AI 结果分流
- 提交记录软删除
- OpenJudge 抓题与 AI 诊断异步处理
- Queue consumer 已兼容解析对象 body、原始请求流，以及仅带 `ce-vqs*` 头的 CloudEvent 回调
- 全站页面使用 daisyUI 组件和棕色主题，桌面 / 移动端表单操作保持对齐

## 目录结构

```text
api/
  queues/process-submission.js    Vercel Queue consumer
public/                           静态资源
docs/                             使用说明、部署手册和交付文档
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
tests/                            Python pytest 和 Node consumer 测试
```

## 本地开发

### 1. 环境要求

- Python 3.12
- `uv`
- Node.js 24.x（用于 Vercel Queue consumer 测试）

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
- 脚本会先执行历史库 Alembic 基线补写，再执行 `flask db upgrade`，最后清洗旧版追问消息内容。
- 迁移脚本和相关 revision 已按线上旧库场景做幂等处理，避免重复补列或补表时报错。
- 这套流程就是为了适配 Vercel 直接导入 GitHub 仓库的部署方式。

如果要手动跑迁移：

```bash
bash scripts/prod-db-migrate.sh
```

前提是当前环境已设置 `DATABASE_URL` 或 `MIGRATION_DATABASE_URL`。

如果只想检查或清洗历史追问记录，可单独执行：

```bash
uv run flask clean-followup-history --dry-run
uv run flask clean-followup-history
```

## 测试

跑 Python 全量测试：

```bash
uv run pytest -q
```

跑覆盖率门槛：

```bash
uv run --with coverage coverage run -m pytest -q
uv run --with coverage coverage report --fail-under=95
```

只跑某个文件：

```bash
uv run pytest tests/test_admin_submission_management.py -q
```

跑 Vercel Queue consumer 测试：

```bash
node --test tests/node/process-submission.test.cjs
```

跑静态检查：

```bash
uv run ruff check
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
- runtime：Node.js 24.x
- maxDuration：60s

用 Vercel CLI 复查当前线上部署：

```bash
vercel inspect https://noi.bbbypw.online
vercel project inspect noicheck
```

如果本机需要代理，Vercel CLI 58 不支持 `socks5h:`，请只给 Vercel CLI 设置 HTTP 代理端口：

```bash
export http_proxy=http://127.0.0.1:21081
export HTTP_PROXY=http://127.0.0.1:21081
export https_proxy=http://127.0.0.1:21081
export HTTPS_PROXY=http://127.0.0.1:21081
```

### 必要环境变量

生产环境变量以 `.env.example` 为模板，所有 `replace-*` 值都必须替换。重点确认：

- 基础密钥：`SECRET_KEY`、`ADMIN_INIT_PASSWORD`、`INTERNAL_JOB_TOKEN`
- 数据库：`DATABASE_URL`
- AI 服务：`AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`
- 队列：`JOB_QUEUE_BACKEND=vercel`、`VERCEL_QUEUE_REGION`、`VERCEL_QUEUE_TOPIC=noi_submission_jobs`
- 主站地址：`APP_BASE_URL`
- 稳定性参数：`JOB_QUEUE_PUBLISH_*`、`JOB_INTERNAL_*`、`SQLALCHEMY_*`、`AI_CONCURRENCY_*`、`FETCH_CONCURRENCY_LIMIT`

兼容说明：

- AI 配置支持新变量名 `AI_*`
- 也兼容旧变量名 `DEEPSEEK_*`
- 线上 Queue callback 优先使用请求头里的 `x-vercel-oidc-token` 回拉消息；仅本地联调或脱离 Vercel 环境复现时，才需要额外提供 `VERCEL_OIDC_TOKEN`
- 详细变量说明、部署状态和排错入口见 [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)

## Queue Consumer 说明

当前 `api/queues/process-submission.js` 会按下面顺序解析消息：

1. 直接读取 `req.body`
2. 如果 `req.body` 为空，再读原始请求流
3. 如果 body 仍为空，但存在 `ce-vqs*` CloudEvent 头，则按 `messageId` 回拉 Vercel Queue payload

线上排错时可以先看这两个信号：

- `Queue consumer received unsupported payload shape ...`
  说明 consumer 既没拿到 body，也没识别出可回拉的 Queue callback 元数据
- `queue_message_fetch_failed`
  说明已经识别出 Queue CloudEvent，但回拉 Vercel Queue API 失败，应继续检查 OIDC token、region、deployment id 或 Queue API 响应

最近一轮稳定性收敛后，主站的队列发布策略是：

- 发布超时默认从 `10s` 收敛到 `3s`
- 同一进程内复用 `httpx.Client`
- 队列发布失败时使用相同幂等键做一次短重试，减少高峰期偶发 `500`

## 线上回归建议

发版后建议至少回归这些链路：

- 首页与登录页可访问
- 教师登录、学生登录、退出
- 学生创建账号、重置密码、启停用
- 学生 `自己提交`
- 学生 `提交给老师`
- 学生提交详情页右侧追问抽屉开关、多轮追问、跑题拒答
- 教师列表筛选、详情查看、删除记录
- 教师学生视角预览中的追问记录只读抽屉
- 异步抓题与 AI 状态流转

## 当前已知边界

- 学生端 AI 是提示链路，不是实际编译执行判题。
- OpenJudge 抓题依赖目标站点可访问性。
- 线上稳定性仍然依赖队列、外部抓题和模型接口。
- 当前真站已经验证到 `8` 并发 self-check 稳定；若目标是约 `100` 名学生集中提交，下一步应继续从数据库连接数、worker 横向扩展和队列吞吐做容量规划，而不是只提高 AI 并发。

## 补充

如果你想看更细的实现状态、字段设计和业务流转，直接看 [PROJECT_STATUS.md](./PROJECT_STATUS.md)。
