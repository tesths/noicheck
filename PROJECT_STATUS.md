# NOI 错题诊断系统项目说明

更新时间：2026-05-08

## 1. 项目目标

这个项目用于收集学生的 OpenJudge 代码提交，并分别服务两类使用者：

- 学生端：登录后提交代码，获得只给提示、不直接给答案的 AI 引导。
- 教师端：查看所有提交、题面快照、学生提示，并在需要时生成完整诊断和参考程序。

当前阶段已经进入“统一登录入口 + 学生双提交流程 + 多轮追问 + 教师分流查看”的阶段。

若要快速上手运行、测试或部署，优先看根目录 `README.md`。

## 2. 当前实现状态

当前系统已经落地这些能力：

- 首页改成统一登录入口 `/`。
- 匿名提交入口 `/submit` 已下线，只保留重定向和提示。
- 新增学生登录入口 `/student/*`。
- 新增教师后台学生管理页 `/admin/students`。
- 学生提交已拆成两种模式：`自己提交`、`提交给老师`。
- 自己提交会进入“学生版 AI 提示”链路。
- 提交给老师会自动进入“老师版完整诊断”链路。
- 学生版 AI 只做引导，不返回正确答案，不返回参考程序。
- 学生在 `self_check` 提交详情页可以从右侧抽屉继续追问，原始代码和首轮提示会保留在主内容区。
- 学生追问按聊天记录持续保存，只允许围绕当前题目的编程问题继续提问；跑题内容会直接拒答并引导回代码、输入输出和调试。
- 教师查看学生视角预览时，使用同一套追问抽屉，但表单为只读。
- 教师后台可以看到学生提示，也可以看到老师版完整诊断和参考程序。
- 学生账号已区分“登录用户名”和“真实姓名”。
- 教师后台支持切换 DeepSeek `v4 flash / v4 pro`，并对后续全部 AI 任务生效。
- 教师后台支持分别配置老师版和学生版 DeepSeek 系统提示词，并对后续 AI 任务生效。
- 教师后台支持按学生筛选提交、查看某个学生的全部提交记录。
- 教师后台从筛选列表进入提交详情后，返回列表会保留当前筛选或分页上下文。
- 教师后台支持软删除提交记录，删除后学生端、教师端和后台任务都会忽略该记录。
- 抓题和 AI 任务继续走异步队列。
- AI 配置已兼容 `AI_*` 与旧 `DEEPSEEK_*` 变量，可切换 OpenRouter。
- 当前稳定策略以“正常使用优先”为主：先保证模型按 JSON 契约输出，并在解析层兼容少量脏格式返回。
- 生产迁移已补齐旧库幂等处理：`request_token` 列、追问表结构、Alembic 基线补写和历史追问清洗都能重复执行。

目前学生端和教师端的 AI 能力已经分流：

- 学生端：只能看到提示结果。
- 教师端：可以看到完整诊断与参考程序。

## 3. 当前架构

### 3.1 Web 主站

- 主站框架：Flask
- 统一登录入口：`/`
- 匿名提交兼容跳转：`/submit`
- 学生端入口：`/student/*`
- 教师后台：`/admin/*`
- 内部任务入口：`/internal/jobs/process`

主站负责：

- 表单校验
- 账号登录态处理
- 提交记录落库
- 教师和学生页面展示
- 接收内部任务请求
- 执行抓题和 AI 处理逻辑

### 3.2 异步任务

- 线上队列：Vercel Queues
- Queue consumer：`api/queues/process-submission.js`
- Python 任务处理：`src/app/services/jobs.py`

当前存在两类主要 AI 任务链路：

- 教师完整诊断：`fetch-and-diagnose` / `diagnose-submission`
- 学生提示链路：`fetch-and-student-diagnose`

### 3.3 数据存储

- 本地开发：SQLite
- 线上部署：Postgres

生产环境仍然要求使用公网 Postgres。
生产数据库迁移支持通过 GitHub Actions 自动执行，适配 Vercel 直接连接 GitHub 仓库的部署方式。

## 4. 当前业务流程

### 4.1 登录入口

1. 用户访问 `/`。
2. 根据身份进入学生登录或教师登录。
3. 未登录访问旧 `/submit` 时，会被重定向回统一入口。

### 4.2 学生端链路

1. 老师在 `/admin/students` 创建学生账号。
2. 学生访问 `/student/login` 登录。
3. 学生在 `/student/submissions/new` 选择提交方式。
4. 若选择 `自己提交`：
   - 落库时绑定 `student_user_id`
   - 自动入队 `fetch-and-student-diagnose`
   - 学生只看到提示结果
   - 学生提示成功后，可在详情页右上角打开追问抽屉继续追问
5. 若选择 `提交给老师`：
   - 落库时绑定 `student_user_id`
   - 自动入队 `fetch-and-diagnose`
   - 学生只能看到老师处理状态，看不到正确程序
6. 学生继续追问时：
   - 默认沿用题面、学生代码、首轮提示和历史追问上下文
   - 页面保持原始代码和学生提示可见，追问区从右侧抽屉展开
   - 仅允许题目相关的编程问题；非编程内容直接返回统一拒答文案

学生端结果只允许展示：

- 可能出错的方向
- 建议检查的位置
- 自查步骤
- 提示策略

学生端不允许展示：

- 正确答案
- 参考程序
- `correct_program`

### 4.3 教师后台链路

老师后台当前用于：

- 查看所有提交
- 按学生筛选提交
- 查看单个学生的全部提交记录
- 查看提交类型
- 查看抓题状态
- 查看学生提示状态
- 查看学生追问记录
- 查看教师诊断状态
- 查看题面快照
- 查看教师版 AI 诊断与参考程序
- 从学生视角只读预览同一套追问抽屉
- 切换当前 AI 模型（`deepseek-v4-flash` / `deepseek-v4-pro`）
- 创建学生账号
- 重置学生密码
- 禁用 / 启用学生账号
- 删除提交记录（软删除）
- 在需要时手动触发教师完整诊断

## 5. 当前数据模型与状态字段

### 5.1 提交状态

`Submission.fetch_status` 使用：

- `pending`
- `queued`
- `running`
- `success`
- `failed`

`Submission.student_hint_status` 使用：

- `pending`
- `queued`
- `running`
- `success`
- `failed`

`Submission.diagnosis_status` 使用：

- `pending`
- `queued`
- `running`
- `success`
- `failed`

页面展示时会转换成中文：

- 待处理
- 排队中
- 处理中
- 成功
- 失败

### 5.2 提交模式

`Submission.submission_mode` 当前区分两类提交：

- `self_check`
- `teacher_review`

含义如下：

- `self_check`：学生自己排查，学生端可见 AI 提示。
- `teacher_review`：学生提交给老师，老师端可见完整诊断与参考程序。

### 5.3 诊断结果分流

`DiagnosisRun.audience` 当前区分两类结果：

- `student`
- `teacher`

含义如下：

- `student`：学生端提示结果，不含正确程序。
- `teacher`：教师端完整诊断，可含参考程序。

### 5.4 学生账号

新增 `student_users` 表，核心字段包括：

- `nickname`
- `real_name`
- `password_hash`
- `is_active`
- `created_at`
- `last_login_at`

`submissions.student_user_id` 用于绑定学生和提交记录。

### 5.5 模型设置与软删除

新增 `system_settings` 表，当前用于保存：

- `active_ai_model`
- `teacher_system_prompt`
- `student_system_prompt`

`submissions.deleted_at` 用于软删除提交记录：

- 为 `NULL`：正常可见
- 非 `NULL`：前后台和异步任务都忽略

### 5.6 学生继续追问

新增两张追问相关表：

- `submission_followup_sessions`
  - 与 `submissions` 一对一绑定
  - 保存某次学生提交的追问会话时间轴
- `submission_followup_messages`
  - 保存 `student / assistant` 两类消息
  - 可附带 `context_label`、`context_text`、`model_name`、`latency_ms`

当前追问记录会按消息顺序长期保存，学生和教师预览看到的是同一份历史。

### 5.7 提交防重

`Submission.request_token` 用于防止学生在提交表单页重复点击后生成多条记录。

## 6. 关键文件

下面这些文件是当前系统的核心入口：

- `src/app/routes/public.py`
  - 统一登录入口与旧匿名入口重定向
- `src/app/routes/student.py`
  - 学生登录、列表、提交方式选择、两类提交、详情
- `src/app/routes/admin.py`
  - 教师后台、学生管理、模型切换、提交筛选、软删除、教师诊断触发
- `src/app/routes/internal.py`
  - 内部任务接口
- `src/app/services/jobs.py`
  - 抓题、学生提示、教师诊断、状态流转，以及软删除记录跳过逻辑
- `src/app/services/ai.py`
  - 教师版 AI、学生版 AI 提示，以及 JSON 输出契约与解析容错
- `src/app/services/student_followups.py`
  - 学生继续追问、编程问题限制、会话上下文准备与消息落库
- `src/app/services/followup_cleanup.py`
  - 历史追问消息清洗 CLI，修正旧版 assistant JSON 文本
- `src/app/services/settings.py`
  - 当前生效 AI 模型的持久化读取与写入
- `src/app/services/auth.py`
  - 教师认证、学生认证
- `src/app/schemas/diagnosis.py`
  - 教师版结构化诊断 schema
- `src/app/schemas/student_hint.py`
  - 学生版提示 schema
- `src/app/models/student_user.py`
  - 学生账号模型
- `src/app/models/submission.py`
  - 提交模型、提交类型与状态字段
- `src/app/models/submission_followup.py`
  - 学生追问会话与消息模型
- `src/app/models/diagnosis_run.py`
  - AI 结果记录与 audience 分流
- `api/queues/process-submission.js`
  - Vercel Queue consumer
- `scripts/prod-db-migrate.sh`
  - 生产迁移入口，包含旧库基线补写、`db upgrade` 与历史追问清洗
- `.env.example`
  - 环境变量模板

## 7. 当前阶段已完成事项

当前阶段已经完成这些工作：

- 新增学生账号体系。
- 新增学生登录、退出、提交列表、新建提交、提交详情页面。
- 新增教师后台学生管理页面。
- 学生账号支持创建、重置密码、禁用 / 启用。
- 学生提交会绑定学生账号。
- 新增学生版 AI 提示 schema 和 prompt。
- 学生版 AI 明确禁止输出正确答案和参考程序。
- 教师版完整诊断能力保留。
- 新增 `DiagnosisRun.audience`，区分学生结果和教师结果。
- 新增 `Submission.student_hint_status`。
- 修复学生提交在显式主键兜底保存时可能丢失学生归属的问题。
- 修复学生提示处理中教师仍可重复发起教师诊断的并发冲突问题。
- 教师后台补上“学生管理”可见入口。
- 学生账号新增真实姓名字段，教师后台用“真实姓名（用户名）”识别学生。
- 教师后台新增 AI 模型切换，并持久化到数据库。
- 教师后台新增老师版 / 学生版 DeepSeek 系统提示词设置，并持久化到数据库。
- 教师后台新增按学生筛选提交和学生专属提交页。
- 修复教师端从筛选后的提交列表进入详情页时，“返回列表”会丢失筛选条件的问题；现在返回、生成诊断后刷新详情、删除后跳回都保留原上下文。
- 提交记录新增软删除，删除后列表、详情、学生端和后台任务统一忽略。
- 补充 favicon，避免浏览器继续请求缺失的 `/favicon.ico`。
- 首页改成统一登录入口，旧匿名提交改为重定向提示。
- 新增 `Submission.submission_mode`，明确区分 `self_check` 和 `teacher_review`。
- 学生端拆成“自己提交”和“提交给老师”两套表单与处理链路。
- 教师后台列表和详情页补充提交类型、学生提示结果和老师版结果分流展示。
- AI 配置兼容 `AI_*` 与旧 `DEEPSEEK_*`，`.env.example` 默认示例改为 OpenRouter。
- 教师 prompt 升级到 `v2`、学生 prompt 升级到 `student-v5`，明确要求只输出单个 JSON 对象；学生程序即使只有空壳或简单定义，也要继续用孩子能听懂的话解释输入输出、变量接收和起步写法。
- 解析层增加 JSON 容错：当模型偶发返回代码块或前后缀说明文字时，系统会先提取首个完整 JSON 对象再继续校验。
- 新增学生继续追问能力，追问记录按聊天消息持久化保存。
- 学生提交详情改成右侧抽屉式追问交互：桌面端推开主内容，移动端从右侧覆盖滑出。
- 教师学生视角预览复用同一套追问抽屉，但不允许老师代学生发问。
- 追问链路新增编程问题限制，非题目相关内容直接返回统一拒答文案。
- 修复生产迁移中 `request_token` 重复补列问题，并让追问相关迁移支持旧库幂等执行。
- 生产迁移脚本增加 `clean-followup-history`，用于把旧版 assistant JSON 历史清洗成可直接展示的聊天文本。
- 已完成本地 `pytest -q` 116 项通过、`ruff check` 通过，并完成 2026-05-08 线上学生端抽屉追问回归。

## 8. 部署与环境变量说明

建议直接参考根目录 `.env.example`。

部署到 Vercel 时，至少需要确认这些变量：

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

补充说明：

- 当前学生账号由教师后台创建，不依赖额外环境变量。
- 线上数据库仍然必须使用 Postgres。
- `APP_BASE_URL` 需要指向正式站点地址。
- 若线上仍保留旧变量名，系统会继续兼容读取 `DEEPSEEK_*`。
- 当前默认不启用额外的 OpenRouter 速度调优参数，优先保证返回内容稳定可解析。
- `scripts/prod-db-migrate.sh` 在 `db upgrade` 后会自动执行 `uv run flask clean-followup-history`。
- 如需先观察影响范围，可单独执行 `uv run flask clean-followup-history --dry-run`。

## 9. 当前已知风险

目前还需要继续留意这些点：

- 线上 Queue trigger 仍需继续观察稳定性。
- OpenJudge 抓题稳定性仍依赖站点可访问性。
- 学生版 AI 目前是静态代码提示，不是真实编译执行判题。
- 模型即使已被要求只输出 JSON，仍可能偶发偏离格式；当前系统已做解析容错，但仍应继续观察线上日志。
- 追问的“只限编程相关”约束目前采用策略文案 + 关键词护栏，仍应继续观察误判和漏判。
- 还没有做学生名单批量导入。
- 还没有做更细的失败分类和后台监控。

## 10. 下一步建议

建议下一步优先做：

- 评估是否需要引入真实代码执行沙箱。
- 评估是否需要做学生批量导入。
