# Task Queue

- [待确认] 实现 NOI 错题诊断系统 v1：Flask + Vercel + 本地 SQLite / 线上 Zeabur Postgres + OpenJudge 抓题 + DeepSeek 诊断 + 教师后台登录
- [待确认] 调研免费可部署多个 Python 项目的平台，关注免费额度、休眠策略、自定义域名与多服务支持
- [进行中] 改回同步流程：学生提交时同步抓题，教师在后台点击后再进行 AI 分析
- [进行中] 落地 Vercel Queues 异步方案：Flask 负责落库与排队，Node consumer 触发后台抓题和 AI 诊断
- [进行中] 补充 .env.example：生成可直接复制到 Vercel 的生产环境变量模板
- [进行中] 修复 Vercel 部署冲突：移除 builds 与 functions 混用，切换到单一 functions 配置
- [进行中] 修复 Vercel runtime 报错：移除 functions 中无效的官方 Node runtime 字段
- [进行中] 修复 Vercel unmatched function pattern：移除对 Flask 框架入口 `src/index.py` 的 functions 显式匹配
- [进行中] 修复线上 CSS 404：统一样式资源路径为 `/styles.css`，兼容 Vercel `public/` 根路径静态资源
- [进行中] 调整异步流程：学生提交后自动排队抓题并继续 AI 诊断，老师仅在失败时重试
