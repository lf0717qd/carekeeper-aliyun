# CareKeeper · 阿里云函数计算 FC 部署包

这是「乡音健康管家」的后端，适配 **阿里云函数计算 FC 3.0 Web 函数**。

## 特点

- 纯 Python 标准库，无第三方依赖；
- 提供：
  - GET /api/health
  - POST /api/chat
  - POST /api/chat_stream（FC 版用非流式包装成 SSE）
  - POST /api/asr（GLM-ASR-2512）
- CORS 已开启；
- API Key 只放函数环境变量。

## 部署步骤（控制台）

1. 登录阿里云函数计算 FC 控制台；
2. 函数管理 → 函数列表 → 创建函数；
3. 选择 **Web 函数**；
4. 运行环境选 **Python 3.12**（或 Python 3.10+）；
5. 代码上传：选择本仓库的 carekeeper-fc.zip；
6. 启动命令：

   python server.py

7. 监听端口：9000；
8. 规格：512MB / 0.1 CPU 起步，超时 60 秒；
9. 环境变量：

   API_KEY=你的智谱 Key
   BASE_URL=https://open.bigmodel.cn/api/paas/v4
   MODEL=glm-4-flash
   ASR_MODEL=glm-asr-2512

10. HTTP 触发器：匿名，允许 GET / POST / OPTIONS；
11. 创建并等待部署；
12. 打开：

    https://你的函数地址/api/health

返回 {"ok": true, ...} 即成功。

## 注意

- FC Web 函数默认给 HTTPS 地址；
- 自定义域名需要 ICP 备案；
- 免费额度/计费以阿里云控制台为准；
- Demo 不诊断、不开方；所有人物/读数均为合成数据。
