# NOI 错题诊断系统项目说明

更新时间：2026-04-27

## 1. 项目目标

这个项目用于收集学生的 OpenJudge 代码提交，并自动给老师生成可参考的 AI 诊断结果。

当前目标是先把 v1 跑通，重点覆盖下面几件事：

- 学生无需登录，直接提交姓名、题目链接和 C++ 代码。
- 系统自动抓取 OpenJudge 题面。
- 系统自动调用 DeepSeek 生成诊断结果和参考程序。
- 老师通过后台查看所有提交、题面快照和诊断结果。
- 如果某次后台任务失败，老师可以手动重试。

## 2. 当前实现状态

当前主流程已经不是“老师点击后再分析”，而是：

- 学生提交后，系统立即落库。
- 提交记录会自动进入后台队列。
- 后台任务会先抓题，再继续 AI 诊断。
- 老师进入后台时，正常情况下应该直接看到已经生成好的结果。
- 只有失败场景下，老师才需要手动点击“重新生成 AI 诊断”。

这套流程已经在代码里落地，并有测试覆盖。

## 3. 当前架构

### 3.1 Web 主站

- 主站框架：Flask
- 学生入口：`/submit`
- 教师后台：`/admin/*`
- 内部任务入口：`/internal/jobs/process`

主站负责：

- 表单校验
- 提交记录落库
- 展示后台页面
- 接收内部任务请求
- 执行抓题和 AI 诊断的 Python 逻辑

### 3.2 异步任务

- 线上队列：Vercel Queues
- Queue consumer：`api/queues/process-submission.js`
- Python 任务处理：`src/app/services/jobs.py`

设计上采用了“Node 只负责接队列，Python 继续做业务”的方式。

这样做的原因是：

- Flask 里的抓题和 AI 逻辑已经存在，没必要复制一份到 Node。
- Node consumer 只负责把队列消息转发到 Flask 的内部任务接口。
- 真正的题面抓取、状态回写、AI 诊断仍然由 Python 统一处理。

### 3.3 数据存储

- 本地开发：SQLite
- 线上部署：Postgres

生产环境要求使用公网 Postgres，不能继续使用 SQLite。

## 4. 当前业务流程

### 4.1 学生提交

1. 学生访问 `/submit`。
2. 提交姓名、OpenJudge 题目链接和代码。
3. Flask 校验参数并写入 `submissions`。
4. 系统自动把任务入队为 `fetch-and-diagnose`。
5. 页面跳转到成功页，提示“已进入后台排队”。

### 4.2 队列消费

1. Vercel Queue 触发 `api/queues/process-submission.js`。
2. 这个 Node 函数把消息转发到 `/internal/jobs/process`。
3. Flask 内部接口校验 `INTERNAL_JOB_TOKEN`。
4. Python 根据任务类型执行：
   - 抓题
   - 状态更新
   - AI 诊断
   - 诊断结果入库

### 4.3 教师后台

老师后台用于：

- 查看提交列表
- 查看抓题状态
- 查看诊断状态
- 查看题面快照
- 查看 AI 诊断与参考程序
- 在失败时重新触发诊断

## 5. 当前状态字段

`Submission.fetch_status` 当前使用这些状态：

- `pending`
- `queued`
- `running`
- `success`
- `failed`

`Submission.diagnosis_status` 当前也使用这些状态：

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

## 6. 关键文件

下面这些文件是当前系统的核心入口：

- `src/app/routes/public.py`
  - 学生提交入口
- `src/app/routes/admin.py`
  - 教师后台和失败重试入口
- `src/app/routes/internal.py`
  - 内部任务接口
- `src/app/services/jobs.py`
  - 抓题、诊断、状态流转
- `src/app/services/job_queue.py`
  - 队列发消息封装
- `api/queues/process-submission.js`
  - Vercel Queue consumer
- `src/app/config.py`
  - 环境变量与运行配置
- `vercel.json`
  - Vercel 部署配置
- `.env.example`
  - 生产环境变量模板

## 7. 本轮已完成事项

本轮对话里已经完成的主要工作如下：

- 接入 Vercel Queues 异步方案。
- 新增内部任务接口，保护后台任务调用。
- 新增 Node consumer，把队列消息转发给 Flask。
- 学生提交后自动触发抓题和 AI 诊断。
- 教师后台改成以“查看结果和失败重试”为主。
- 补充 `.env.example`，方便直接复制到 Vercel。
- 修复 Vercel 部署中的 `builds/functions` 冲突。
- 修复无效 `runtime` 配置导致的部署报错。
- 修复 Flask 入口在 `functions` 里的匹配报错。
- 修复线上 CSS 404，统一改为 `/styles.css`。

## 8. 部署说明

当前 Vercel 配置基于：

- `framework: "flask"`
- `functions` 里只配置 `api/queues/process-submission.js`
- 不再混用 `builds`

当前样式资源路径为：

- `/styles.css`

不要再使用：

- `/public/styles.css`

## 9. 环境变量说明

建议直接参考根目录的 `.env.example`。

部署到 Vercel 时，至少需要确认下面这些变量已经正确设置：

- `SECRET_KEY`
- `DATABASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `ADMIN_INIT_USERNAME`
- `ADMIN_INIT_PASSWORD`
- `JOB_QUEUE_BACKEND=vercel`
- `VERCEL_QUEUE_REGION`
- `VERCEL_QUEUE_TOPIC=noi_submission_jobs`
- `INTERNAL_JOB_TOKEN`
- `APP_BASE_URL`

补充说明：

- `DATABASE_URL` 线上必须是 Postgres。
- `APP_BASE_URL` 应该填正式站点地址。
- `.env.example` 里已经生成了一组可直接复制的密钥，但如果仓库后续公开，建议重新轮换。

## 10. 当前已知风险与后续建议

目前还需要留意这些点：

- 线上要继续观察 Queue trigger 是否稳定触发。
- AI 诊断如果经常接近 60 秒，可能还要继续优化超时策略。
- 现在的任务状态已经够用，但还没有做更细的失败分类。
- `TASK_QUEUE.md` 里保留了部分历史任务记录，阅读时要以本文件描述的“当前状态”为准。

建议下一步优先做：

- 在 Vercel 线上完整走一遍真实提交流程。
- 核对抓题成功率和 AI 成功率。
- 如果需要，再补一个面向交付的 `README.md`。
