# PinDou Studio Web

React + TypeScript + Vite 工作台。M1 已接入真实项目创建、多视角上传、编译、作业轮询、失败重试和 GLB 产物下载；M2-T4 设计审阅页已接入真实 GLB 体素切片、切片导航、色号图例和采样参数。没有项目或 GLB 时显示可操作空状态，不使用演示板件冒充真实结果。

```powershell
cd apps/web
pnpm install
pnpm run dev
```

Vite 默认把 `/api` 代理到 `http://127.0.0.1:8000`。

构建与类型检查：

```powershell
pnpm run build
```
