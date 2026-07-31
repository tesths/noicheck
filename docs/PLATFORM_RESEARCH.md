# 免费部署多个 Python 项目的平台调研

更新时间：2026-07-31

## 结论

当前 `noicheck` 不建议迁移。继续使用 Vercel + 外部 Postgres + Vercel Queues 最符合现有实现，因为项目已经依赖 Vercel 的 Python Runtime、Queue consumer、GitHub 自动部署和生产迁移流程。

如果目标是“零成本部署多个小型 Python 项目”，没有一个平台同时满足长期免费、多个常驻服务、数据库、后台任务、自定义域名和无休眠。可按用途选择：

| 平台 | 适合用途 | 主要限制 | 当前建议 |
| --- | --- | --- | --- |
| Vercel Hobby | 多个 serverless / Flask 小项目、自动 HTTPS、GitHub 部署 | 免费层面向个人非商业用途；Python Runtime 是 Vercel Functions；Hobby 有资源和函数时长限制 | `noicheck` 继续保留在 Vercel |
| Render Free | Python Web Service 预览、低频工具站 | 免费 Web Service 闲置 15 分钟会休眠，冷启动约 1 分钟；官方明确不建议生产使用 | 可用于演示或备用小项目 |
| Koyeb Free Instance | 单个或少量容器化 Web Service 预览 | 免费资源适合预览平台，不适合承载多个常驻生产服务 | 可作为小型 Python 服务试用 |
| Railway Free / Trial | 快速试用数据库和代码部署 | 新用户试用 $5 / 30 天，之后 Free 仅每月 $1 credit；验证状态会影响网络能力 | 不作为长期免费多项目平台 |
| Fly.io | 全球边缘部署、容器和机器级控制 | 官方说明没有真正 free account/free tier；多数账号部署多个 app 需要有效信用卡 | 不适合作为“免费部署多个项目”方案 |

## 官方来源

- Vercel Python Runtime：`https://vercel.com/docs/functions/runtimes/python`
- Vercel Hobby Plan：`https://vercel.com/docs/plans/hobby`
- Vercel Limits：`https://vercel.com/docs/limits`
- Render Free：`https://render.com/docs/free`
- Koyeb Instances：`https://www.koyeb.com/docs/reference/instances`
- Koyeb Deploy：`https://www.koyeb.com/docs/deploy`
- Railway Free Trial：`https://docs.railway.com/pricing/free-trial`
- Fly.io Billing：`https://fly.io/docs/about/billing/`
- Fly.io Cost Management：`https://fly.io/docs/about/cost-management/`

## 对 noicheck 的影响

- 不迁移主站。迁移不会减少主要复杂度，反而会重做 Queue、内部任务入口、生产环境变量和部署手册。
- 若需要更多 Python 项目，优先在 Vercel 拆项目或复用当前 GitHub/Vercel 流程；当项目需要常驻进程、SSH、长期后台 worker 或持久磁盘时，再考虑 Render / Koyeb / 付费容器平台。
- 数据库继续使用独立公网 Postgres，避免平台免费实例休眠或过期影响学生提交记录。
