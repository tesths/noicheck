# Task Queue

- [待确认] 实现 NOI 错题诊断系统 v1：Flask + Vercel + 本地 SQLite / 线上 Zeabur Postgres + OpenJudge 抓题 + DeepSeek 诊断 + 教师后台登录
- [待确认] 调研免费可部署多个 Python 项目的平台，关注免费额度、休眠策略、自定义域名与多服务支持
- [进行中] 改回同步流程：学生提交时同步抓题，教师在后台点击后再进行 AI 分析
- [进行中] 落地 Vercel Queues 异步方案：Flask 负责落库与排队，Node consumer 触发后台抓题和 AI 诊断
