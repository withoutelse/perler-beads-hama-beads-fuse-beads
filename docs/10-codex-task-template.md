# Codex 任务模板

后续每个里程碑任务都按本模板提交，避免“看起来做完了”但不可验收。

## 1. 任务标题

`M1-T1 图片上传校验`

## 2. 目标

一句话说明用户/系统获得什么能力。

## 3. 背景与约束

- 关联文档：`docs/03-algorithm-spec.md` 的哪一节。
- 路线守卫：必须通过 `RouteGuard`。
- 不允许的退化：胶水、连接棒、水平实心切片、真曲面。
- 单位/坐标：mm、整数格、`x` 右 `y` 深 `z` 上。

## 4. 范围

### 要做

- 具体文件/模块/接口。
- 输入、输出、错误码。

### 不要做

- 不在本任务内的算法或 UI。
- 不引入新的外部服务。

## 5. 验收标准

- [ ] 领域/契约测试覆盖。
- [ ] 错误码稳定。
- [ ] 文档/API 契约同步。
- [ ] 路线守卫通过。
- [ ] 本地命令通过：

```powershell
$env:PYTHONPATH = "apps/api"
python -m unittest discover -s apps/api/tests -v
python -m compileall apps/api/app
```

## 6. 交付物

- 代码文件列表。
- 测试文件列表。
- 文档更新。
- 已知限制/下一步。

## 7. 推荐实现顺序

1. 先写失败测试。
2. 实现领域逻辑。
3. 接入 API/服务。
4. 接前端。
5. 跑全量门禁。
6. 更新任务清单。

## 8. 示例提示词

```text
实现 M1-T1 图片上传校验。先阅读 AGENTS.md、docs/00-product-brief.md、
docs/03-algorithm-spec.md 和 docs/05-implementation-plan.md。
只做 M1-T1，不实现 Tripo 调用。要求：
- 校验 JPG/PNG/WebP 魔数、数量 1–12、单张和总大小上限；
- 错误码 INVALID_IMAGE_TYPE / TOO_MANY_IMAGES / IMAGE_TOO_LARGE；
- 领域测试不依赖网络；
- 更新 API 契约和任务清单；
- 运行 unittest 和 compileall。
```
