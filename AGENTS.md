# Codex 工作约定

本文件适用于整个仓库。开始任何实现前，先阅读：

1. `docs/00-product-brief.md`
2. `docs/01-architecture.md`
3. `docs/03-algorithm-spec.md`
4. `docs/05-implementation-plan.md`
5. `docs/12-requirements-traceability.md`

## 不可违反的路线

产品唯一路线是 **按造型分件 + 双面有孔 + 免胶拼插**。

禁止引入或静默回退到：

- 水平实心切片
- 胶水、连接棒、亚克力杆、金属杆
- 真曲面网格直接作为拼豆板件
- 未经显式标注和用户确认的“局部点胶”

任何设计输出都必须经过 `apps/api/app/domain/route.py` 的 `RouteGuard`。不要通过删除测试、放宽枚举或吞掉错误来绕过路线校验。

## 架构边界

- `apps/api/app/domain/` 只允许标准库和领域内模块，不导入 FastAPI、数据库或网络客户端。
- `apps/api/app/pipeline/` 负责编排和外部适配器，不把网络/存储细节泄漏到领域模型。
- `apps/api/app/api/` 只做 HTTP 映射、输入校验和错误转换。
- `apps/web/` 通过 `docs/04-api-contract.md` 与后端交互；演示数据只能用于 UI 壳层，不能冒充真实结果。
- 所有物理尺寸使用毫米，所有体素/板件坐标使用整数格；不要混用单位。

## 坐标与确定性

- 世界坐标：`x` 向右、`y` 向深度、`z` 向上。
- 体素索引：`(x, y, z)`，闭区间边界为 `0 <= x < width` 等。
- 板件局部坐标：`(u, v)`，`u` 沿边/弧长方向，`v` 沿高度或板件第二轴。
- 所有算法输出必须可复现：排序稳定、随机种子显式、浮点容差写入配置。

## 开发流程

1. 从 `docs/05-implementation-plan.md` 选择一个未完成任务，优先按依赖顺序推进。
2. 先补领域测试，再实现算法；不要用 UI 掩盖领域错误。
3. 保持 API 契约同步更新；破坏性变更必须写 ADR。
4. 完成后运行：

```powershell
$env:PYTHONPATH = "apps/api"
python -m unittest discover -s apps/api/tests -v
python -m compileall apps/api/app
```

5. 更新任务清单、相关文档和 `README.md` 的当前状态。

## 完成定义

- 领域规则有测试覆盖，且测试不依赖网络、GPU 或真实 Tripo 账号。
- 新输出通过路线守卫和 `DesignValidator`。
- 错误有稳定错误码，前端能展示可操作的信息。
- 文档中的算法描述与代码一致。
- 不提交 `.env`、生成的 `storage/`、`work/` 或 `outputs/` 内容。

## 需要先问用户的情况

- 要改变产品路线或允许胶水/连接棒。
- 要引入付费外部服务、账号或部署资源。
- 物理尺寸、板件最大尺寸、色卡标准存在多种互相冲突的选择。
- 需要删除已有数据或执行不可逆迁移。
