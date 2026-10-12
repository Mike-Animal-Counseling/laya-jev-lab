# 从启动到接入：中文使用与测试指南

这个项目把工单的标题、正文转成分类、优先级和投诉/流失/退款信号。你可以直接使用已经训练好的 Laya V5，也可以调用 Jev，或在已有客服系统的后端接入分类能力。网页收件箱用于导入、查看、复核和分配；不会替客户回复、处理退款或修改 Zendesk 工单。

| 你想做什么 | 用哪部分 | 额外需要什么 |
| --- | --- | --- |
| 在电脑上体验所有网页功能 | 认证服务 + 网页 | Python 3.12、Node.js 22.13+、V5 权重 |
| 多人通过网址使用 | Docker 认证服务 | 服务器；远程使用需域名和 HTTPS |
| 在自己的 Python 项目本地分类 | `LayaEngine` SDK | CPU 推理依赖、V5 权重；不用网页或 Kaggle |
| 只使用 Jev | `JevEngine` SDK | 自己的 TypeSafe API Key；不用 Torch 或权重 |
| 从其他语言/客服系统接入 | REST API | 部署认证服务、创建工作区 API Key |
| 用自己的历史工单强化 Laya | Settings → Train | 人工标注的工单、自己的 Kaggle 账号和 GPU 配额 |

**推荐先在本机运行认证服务。** 它包含登录、工作区、API 和 Train；单用户演示后端只有部分功能。原始 V5 下载后就能分类，不需要先训练。以下步骤基于 GitHub 的 `main`；旧版 v0.2.0 源码下载包不包含本次新增的训练功能。

## 1. 本机完整启动（Windows / PowerShell）

首次安装，在你选择的目录运行：

```powershell
git clone https://github.com/Mike-Animal-Counseling/laya-jev-lab.git
cd laya-jev-lab
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
& .\.venv\Scripts\python.exe -m pip install ".[laya]"
& .\.venv\Scripts\python.exe -m pip install --require-hashes --index-url https://pypi.org/simple -r service/requirements.lock
& .\.venv\Scripts\python.exe -m pip install --require-hashes --index-url https://pypi.org/simple -r service/kaggle.lock
npm ci
```

下载约 600 MB 的公开 V5 权重，并导入一次：

```powershell
New-Item -ItemType Directory -Force downloads | Out-Null
Invoke-WebRequest -Uri https://github.com/Mike-Animal-Counseling/laya-jev-lab/releases/download/v0.1.0/laya-v5-inference.zip -OutFile downloads/laya-v5-inference.zip
& .\.venv\Scripts\python.exe projects/laya_ft/import_checkpoint.py downloads/laya-v5-inference.zip
```

导入会校验文件哈希。如果 `models/ticket-finetuned-v5` 已正确导入，就跳过这一步；导入器拒绝覆盖。权重和用户数据分别存储，均不进入源码包。

创建一个工作区，终端会要求你输入并确认自己的密码（至少 12 个字符）：

```powershell
& .\.venv\Scripts\python.exe -m service.manage init --workspace demo --owner admin
```

这条命令只在首次创建工作区时运行；没有默认密码。之后分别打开两个终端，均进入项目目录：

```powershell
# 终端 A：保留运行
& .\.venv\Scripts\python.exe -m service.server
```

```powershell
# 终端 B：保留运行
npm run dev
```

打开 **http://127.0.0.1:5180/laya-ft**，填写工作区 `demo`、用户名 `admin` 和刚设的密码。新工作区为空，首次 Analyze 需要加载模型，可能比较慢。退出时在两个终端各按一次 `Ctrl+C`；下次只需重启服务和网页，数据会保留。

Linux/macOS 用 `python3.12 -m venv .venv`，并把命令中的 `& .\.venv\Scripts\python.exe` 换成 `./.venv/bin/python`。正式运行网页可用 `npm run build` 后接 `npm run start`。本机测试不需要 Docker、GPU、Jev Key 或 Zendesk 账号。

若只想查看带八张合成工单的单用户演示，按 [README 的 Local evaluation](../README.md#local-evaluation) 启动。它使用不同的存储和配置；Train、多用户、完整 OAuth 和工作区 API 请用上述认证服务。两个后端共用默认端口 8780，不要同时运行。

## 2. 先用合成数据测试工单流程

在项目目录生成示例文件：

```powershell
& .\.venv\Scripts\python.exe scripts/make_demo_data.py
```

文件生成在 `var/demo-data/`，不上传 Git。重复运行时拒绝覆盖；需要新副本可加 `--output var/demo-data-second`。这些都是合成内容，训练样例只用于检查流程，不能证明模型效果。

| 文件 | 在哪里用 |
| --- | --- |
| `tickets.csv` | Inbox → Import → Excel / CSV；含五种类型的普通工单 |
| `demo-email.eml` | Import → Email；单封邮件文件 |
| `api-tickets.json` | 第 5 节的 API 导入例子 |
| `training.csv` | Settings → Train；50 张带分类标签的样例 |

先导入 `tickets.csv`，预览无错误后点 **Import**。导入只保存工单。选一张点 **Analyze** 才会调用当前页面的模型。Laya 应显示分类、建议团队、P1/P2/P3 优先级，以及 Complaint、Churn、Refund 信号。

| 操作 | 怎样判断流程正常 |
| --- | --- |
| 再次导入同一个 CSV 或邮件 | 识别重复，工单数不再增长 |
| Analyze / Analyze all | 保存结果；再次打开页面仍能看到 |
| Flag | 显示需要复核的结果；低置信度或流失信号会触发，样例未必触发 |
| 复核、选择团队并 Assign | 保存分配，进入 Assigned；分配仅影响本工作区 |
| Done，然后 Reopen | 状态可完成、重新打开；不发送任何客户回复 |
| Export | 下载当前工单数据；导入真实工单后导出也会含其内容 |
| 打开对比 | 显示已有结果；缺失一侧时要明确点击 Analyze 才运行该模型 |

界面的 Billing、Technical、Sales、Accounts、General 对应 SDK 分类 `refund`、`technical`、`sales`、`account`、`other`。置信度不是实测准确率；要判断业务效果，用未参与训练、人工标注过的真实工单逐条核对。

**普通导入与训练导入是两个入口。** 普通 CSV 需要 `Subject,Message`，每次最多 100 行；训练 CSV 必须有 `message,category`，20–2,000 行。两者均限 2 MB。Excel 可以从界面下载模板填写，再导入 `.xlsx`；不接受公式、宏和外部链接。

## 3. Jev 与双模型对比

在 **Settings → Connections** 填自己的 TypeSafe/Jev API Key 并保存，然后进入 **Jev** 页面对同一张工单点 Analyze。对比页显示两侧已有的分类、优先级和信号差异，适合检查哪个引擎更适合你的工单。

只有明确运行 Jev 或双模型 API 时才向 TypeSafe 发送标题、正文；费用和使用条件由服务商决定。没有 Key 时仍能使用本地 Laya。双方结果一致也不代表一定正确，判断时以人工标签为准。

## 4. 邮件、通用 API 与 Zendesk 导入

文件导入不需要连接账号。其他来源先由 Owner 在 **Settings → Connections** 配置：

| 来源 | 使用方法 | 本版范围 |
| --- | --- | --- |
| 邮件文件 | Import → Email，上传 `.eml` | 提取正文，不导入附件 |
| 邮箱 IMAP | 保存主机、用户、邮箱专用凭据，再 Import → Email → Sync | TLS 只读读取最近 20 封；预览后确认 Import |
| 通用 REST 源 | 保存公开 HTTPS URL 和可选 Bearer Token，再 Import → API → Sync | GET JSON 数组或 `tickets` 数组，最多 100 张；预览后确认 Import |
| Zendesk | 注册自己的 OAuth 客户端，保存租户和客户端信息，点 Connect 授权 | Settings → Sync 手动运行或开启定时增量同步，可暂停 |

普通来源的 JSON 使用 `subject,message`，可带 `customer,company,channel,id`。通用 REST/IMAP 目前是手动拉取；Zendesk 支持增量更新和定时同步。同步、导入和修改模型都不会自动调用 AI。

Zendesk 回调地址必须与部署地址匹配，例如本机服务的 `http://127.0.0.1:5180/api/oauth/zendesk/callback`（须由你的客户端注册接受），远程则使用实际 HTTPS 域名。增量导出需要 Zendesk 管理员权限；首次默认读取工作区创建前一小时起的数据。它不把分类或状态写回 Zendesk。完整客户端、历史迁移和部署要求见 [DEPLOYMENT.md](DEPLOYMENT.md#zendesk)。

## 5. 从自己的工单系统通过 API 接入

在 **Settings → API** 创建工作区 Key。分类用 `classify`，导入用 `tickets:write`，读取用 `tickets:read`。把 Key 保存在你系统的后端。

本机服务运行期间，保存下列代码为你自己的测试脚本后，用虚拟环境 Python 执行：

```python
import getpass
import json
from pathlib import Path
from uuid import uuid4
from ticket_engine import ServiceClient

client = ServiceClient(
    "http://127.0.0.1:5180",
    api_key=getpass.getpass("Workspace API key: "),
)
request_id = str(uuid4())
response = client.classify(
    "Please refund the extra payment.", subject="Duplicate charge",
    engine="laya", request_id=request_id,
)
print(response["result"])

# 同一逻辑操作重试要复用 request_id；相同请求应返回缓存结果。
again = client.classify(
    "Please refund the extra payment.", subject="Duplicate charge",
    engine="laya", request_id=request_id,
)
assert again == response

payload = json.loads(Path("var/demo-data/api-tickets.json").read_text(encoding="utf-8"))
print(client.import_tickets(
    payload["tickets"], update=payload["update"], request_id=str(uuid4()),
))
```

`classify()` 返回分类，不创建收件箱工单；`import_tickets()` 创建/更新工单，不分析。API 导入的稳定身份是 `source + source_id`：用新 UUID 重发相同来源数据不会再建一份，修改正文并 `update=True` 会更新原工单、清除旧分析。同一个 UUID 改发不同内容应返回 409。

远程把 URL 换成自己的 HTTPS 地址。其他语言可直接调用 `/v1/classify`、`/v1/tickets`；[API.md](API.md) 提供权限、限额和保存分析的完整接口，`/v1/openapi.json` 提供机器可读契约。[接入例子](../examples/helpdesk_adapter.py) 展示分类到内部队列的映射。

## 6. 单独使用 Python SDK：抽离 Laya 或 Jev

SDK 不依赖网页、工作区数据库或 Kaggle。如果已有 Python 项目，在源码目录用那个项目的虚拟环境运行 `python -m pip install .`。只用 Jev 到这一步即可；Laya 还需第 1 节的 CPU Torch、`.[laya]` 和公开权重。

```python
from ticket_engine import LayaEngine

laya = LayaEngine(model_path="models/ticket-finetuned-v5")
laya.prepare()  # 校验、预先加载；一个进程复用这个实例
result = laya.classify("Please refund the duplicate charge.", subject="Billing")
print(result.to_dict())
```

```python
import getpass
from ticket_engine import JevEngine, compare

jev = JevEngine(api_key=getpass.getpass("Jev API key: "))
print(jev.classify("Please explain the team plan prices.", subject="Pricing").to_dict())
# 双模型对比需要上一个例子中的 laya，也会明确调用 Jev。
print(compare(laya, jev, "Please refund the duplicate charge.", subject="Billing").to_dict())
```

也可直接运行仓库的交互式合成例子：

```powershell
& .\.venv\Scripts\python.exe examples/classify.py --engine laya
& .\.venv\Scripts\python.exe examples/classify.py --engine jev
& .\.venv\Scripts\python.exe examples/classify.py --engine compare
```

你的系统负责保存结果、映射团队和决定是否让人复核。SDK 输出不带原始正文，也不替调用方保存工单。字段、错误码与命令行 JSON 接口详见 [INTEGRATION.md](../INTEGRATION.md)。

## 7. 用历史工单强化 Laya

在 **Settings → Train** 连接自己的 Kaggle 用户名和现代 API Token，之后正常运行无需编辑 Notebook 或手动 Run All。本机应用负责协调和推理，GPU 训练用这个 Kaggle 账号的配额。

1. 人工核对历史工单标签，映射为 `refund/technical/sales/account/other`。`message` 和 `category` 必填；同一对话的工单填相同 `group_id`。至少两类，每类至少 10 个不同对话组。
2. 先清理真实文本中的私人信息和秘密，再上传 CSV/Excel，检查预览、分类覆盖和训练字段。内置基础脱敏不能保证清除所有隐私。
3. 明确确认上传至自己的私有 Kaggle 数据集，点 Train。后台服务需持续运行；可以离开网页。
4. 查看独立测试集的 V5/候选模型比较。通过改善规则后才能点 **Use model**，没有提升则保留 V5。原模型不会被覆盖；**Restore V5** 可恢复。
5. **Download** 下载适配器。解压到私有目录后，独立 SDK 用 `LayaEngine(model_path="models/ticket-finetuned-v5", adapter_path="private-models/my-team")` 加载，不需要 Kaggle。

目前调整 V5 的决策层，编码器保持冻结；不是重新训练整个模型，也不增加新分类。没标注的字段继续使用 V5。样例 `training.csv` 可测预览和运行链路，但简单合成内容常常没有提升，不能当真实评测数据。

模型切换只影响该工作区以后的 Laya 调用；旧结果保留模型身份，分配前需要重新分析。Jev 和其他工作区不受影响。

**验证边界：** 已验证真实 V5 的本地 CPU 训练、适配器导出和加载，以及模拟的 Kaggle 协调流程；尚未用真实账号完成 Kaggle GPU 全链路验收。首次真实运行可能需要针对账号权限、配额或运行镜像进一步调整。Kaggle 数据和任务留在使用者账号中，取消 GPU、删除远程数据和撤销 Token 需在 Kaggle 处理。细节见 [TRAINING.md](TRAINING.md)。

## 8. 多人部署、权限和日常维护

Docker 完整启动命令见 [README 的 Shared inbox](../README.md#shared-inbox)，HTTPS、备份和更新见 [DEPLOYMENT.md](DEPLOYMENT.md)。Docker 的模型卷、工作区卷与源码分开，重建镜像不应删除数据卷。

Owner 在 **Settings → Team** 邀请成员。Member 可以导入、分析、分配和完成；Viewer 只读工单、已有比较结果和导出。新建第二个工作区要由部署者运行 `service.manage init` 并换一个 slug。测试隔离时分别登录两个工作区：一个工作区导入的数据不应出现在另一个中。

源码模式的工单、账号、加密设置和训练文件在 `var/cloud/`。使用训练后，备份须包含数据库、对应 `master.key` 和 `training/`，不能仅备份 SQLite。退出后台后做一致的私有备份。忘记密码可运行 `python -m service.manage reset-password --workspace demo --username admin` 并交互输入新密码。

更新前保护好运行数据，再审查并 `git pull --ff-only`、更新依赖、重启服务。已存在的工作区不用重新 init，已导入的 V5 不用重复导入。启用过适配器的部署应保留其私有文件。源码仓库不能代替用户数据备份。

## 9. 开发者自动检查

普通使用者完成第 2 节的流程测试即可。修改源码时，在已安装依赖的虚拟环境运行：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s backend -p 'test_*.py'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
npm run test:ui
npm run lint
npm run build
npm run typecheck
& .\.venv\Scripts\python.exe scripts/check_public.py
```

这些检查验证程序行为，不代表已验证你的账号接入或数据质量。真实 Jev、Zendesk OAuth/同步与 Kaggle GPU 要用部署者自己的账号另外验收。公开代码和模型不提供这些账号凭据。
