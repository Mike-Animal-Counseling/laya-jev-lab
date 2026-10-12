# 接入分类引擎

分类模块是 `ticket_engine`。它可以单独安装到已有 Python 项目，不需要 Node.js、网页、Waitress 或演示数据库。

## 安装

在下载的源码目录中，用目标项目的 Python 3.12 环境执行：

```sh
python -m pip install .
```

基础安装仅使用 Python 标准库即可调用 Jev。需要本地 Laya 时，再安装本地推理依赖：

```sh
python -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install ".[laya]"
```

这是从本仓库安装的包，不表示同名包已发布到 PyPI。权重不装进 Python 包，需要按 README 导入单独提供的权重归档，然后显式传入其目录。

## 本地 Laya

```python
from ticket_engine import LayaEngine

# 路径由你的应用明确提供；不会自动查找其他项目的模型。
engine = LayaEngine(model_path="models/ticket-finetuned-v5")
result = engine.classify(
    "本月订阅被扣了两次，请帮我退回多扣的款项。",
    subject="重复扣费",
)
print(result.category)
print(result.to_dict())
```

一个工作进程复用一个实例；第一次调用校验并加载模型，后续调用复用。单个实例内部串行执行，避免同一模型并发状态问题。多进程会各自占用模型内存，调用方应设置队列、并发和超时上限。

模块不修改调用进程的环境变量、`sys.path` 或 PyTorch 全局线程数。若需要限制 CPU 线程，由你的应用显式配置，例如加载模型前使用 `torch.set_num_threads(4)`。当前公开适配器使用 CPU。

## Adapted Laya

For a workspace-trained Laya adapter, pass an explicit private directory:

```python
from ticket_engine import LayaEngine

engine = LayaEngine("models/ticket-finetuned-v5", adapter_path="private-models/my-team")
engine.prepare()
```

The original V5 remains required and hash-verified. Only labelled fields use adapted decision weights; all other fields keep V5. The SDK needs no Kaggle or service dependency. See [training and adapter deployment](docs/TRAINING.md). Jev cannot load Laya adapters.

## Jev

```python
import getpass
from ticket_engine import JevEngine

engine = JevEngine(api_key=getpass.getpass("Jev API key: "))
result = engine.classify("请介绍一下团队套餐的价格。", subject="采购咨询")
print(result.to_dict())
```

后端应用中可从自己的密钥管理服务取得 Key，再传入 `api_key`。SDK 不自行读取 `.env`、系统环境中的 Key 或父目录配置。网页演示的 `.env.local` 读取逻辑只存在于演示适配器中。

构造对象不会调用 API；`classify()` 才会发送标题、正文和固定规则至 TypeSafe。传输使用固定 HTTPS 地址，拒绝重定向，不继承系统代理。可显式设置 `timeout`（1–120 秒）和服务商支持的 `model` 标识。

## 对比两个引擎

```python
from ticket_engine import compare

# local_engine 与 jev_engine 分别按上面的方式创建。
comparison = compare(
    local_engine, jev_engine,
    "本月被重复扣款，请退款。", subject="账单问题",
)
print(comparison.to_dict())
```

这会先调用本地引擎，再调用 Jev；不会后台自动调用或自动重试。差异按类别、优先级和三项信号的 0.5 阈值比较，结果一致不代表正确。

任一侧失败时抛出 `EngineError`。若需保留另一侧成功结果，应分别调用并由应用处理部分成功；不要对整个对比操作无条件重试，以免重复产生 API 费用。

## 统一输出

`classify(message, *, subject="")` 返回 `ClassificationResult`；`.to_dict()` 可直接 JSON 序列化。

| 字段 | 含义 |
| --- | --- |
| `provider` | `laya` 或 `jev` |
| `category` / `category_label` | 五选一分类标识及显示名称 |
| `suggested_team` | 默认中文团队名称，业务系统可自行映射内部队列 ID |
| `confidence` / `probabilities` | 分类置信度及五类分布，不是实测准确率 |
| `urgency` / `priority` | 0–3 分；≥1.7 为 P1、≥0.9 为 P2，其余 P3 |
| `complaint` / `churn` / `refund` | 0–1 信号分数；演示使用 0.5 作为判断阈值 |
| `needs_review` / `review_reasons` | 分类置信度 <0.65 或流失分数 ≥0.5 时建议复核；原因是 `low_confidence` / `churn_risk` |
| `model` / `checkpoint_sha256` | 模型标识；本地模型提供权重哈希，Jev 为 null |
| `rubric_id` / `input_id` | 规则与输入的短摘要，用于结果关联，不是授权凭证或匿名化保证 |
| `elapsed_ms` | 调用耗时，不含等待本实例锁的时间；首次本地调用包含加载耗时 |
| `input_tokens` | 引擎返回的输入 token 用量 |
| `analyzed_at` / `schema_version` | UTC 时间及输出格式版本，用于集成兼容 |

返回值不包含工单正文、标题或 API Key。SDK 不存储请求、结果或工单历史；调用方负责自己的持久化、日志与隐私策略。不要把模型结果直接当作身份、权限或执行财务动作的依据。

## 错误处理

```python
from ticket_engine import EngineError

try:
    result = engine.classify("合成示例工单")
except EngineError as error:
    # 用稳定错误码分支；不记录用户正文或凭据。
    print(error.code, error.retryable)
```

错误码包括 `invalid_config`、`invalid_input`、`invalid_checkpoint`、`missing_dependency`、`model_load_failed`、`inference_failed`、`invalid_response` 和 `provider_error`。异常对外只暴露安全提示，不返回上游响应正文、Key 或本机路径。

`retryable` 只表示调用方可以考虑重试，不代表自动重试安全或免费。本地不会自动改用 Jev；Jev 失败也不会生成占位结果。

## 命令行示例

安装包后可在源码目录运行：

```sh
python examples/classify.py --engine laya
python examples/classify.py --engine jev
python examples/classify.py --engine compare
```

Jev Key 在终端隐藏输入，不放入命令行历史。默认工单是合成内容。接入边界与类别定义见 [SCOPE.md](SCOPE.md)。

## 接入已有工单系统

`LayaEngine` 和 `JevEngine` 可以独立使用；只装基础包调用 Jev 时不需要 Torch。原来的 `TicketEngine` 接口保持兼容。调用方保留自己的账号、工单数据库和队列映射，参考 [helpdesk_adapter.py](examples/helpdesk_adapter.py)。

网络接入时，部署可选认证服务，用 `ServiceClient` 或其他语言调用 `/v1/classify`。工作区 API Key 只放在后端，读写权限分别授权；每个逻辑操作传入稳定 UUID。详见 [REST API](docs/API.md) 和 [部署文档](docs/DEPLOYMENT.md)。

安装 SDK 后，`ticket-classify --engine laya --model-path models/ticket-finetuned-v5` 从标准输入读取 `{"subject":"Billing","message":"Please refund the duplicate charge."}` JSON，向标准输出写入结果。Jev 选择 `--engine jev`，CLI 显式读取 `TYPESAFE_API_KEY`；SDK 本身不读取环境凭据。`--key-env` 可指定自己的变量名，避免把密钥写入命令行参数。
