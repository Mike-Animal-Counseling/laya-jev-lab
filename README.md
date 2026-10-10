# Laya × Jev · SaaS 工单分类引擎

在同一张工单、同一套规则下，对照 **本地微调 Laya V5** 与 **TypeSafe Jev API** 的五项判断：负责团队、紧急程度、投诉、流失风险、退款诉求。

项目提供可独立集成的 Python 分类模块，以及本机单用户的对比演示界面。Laya 在本机 CPU 上离线推理，不收取 API 调用费；Jev 由体验者配置自己的 API Key，主动分析时按服务商规则计费。它不是自动回复机器人，也不会真的发送退款、邮件或客服分配指令。

## 能力范围与直接集成

我们提供明确范围和边界的 SaaS 工单分类能力：账单退款、技术故障、售前咨询、账号问题和综合请求，附带紧急程度、投诉、流失及退款信号。完整定义见 [SCOPE.md](SCOPE.md)。

只需引擎时不必安装或启动网页。在你的 Python 环境中，从本目录安装：

```sh
python -m pip install .
```

```python
from ticket_engine import TicketEngine

engine = TicketEngine("laya", model_path="models/ticket-finetuned-v5")
result = engine.classify("本月订阅被重复扣款，请退款。", subject="账单问题")
print(result.to_dict())
```

本地推理还需安装权重与 `.[local]` 依赖；Jev 只需显式传入调用方自己的 Key。SDK 不读取演示数据库、不启动服务、不自动查找凭据，也不保存工单。两种引擎共用分类规则和输出格式。完整安装、Jev/双引擎示例、输出字段及错误处理见 **[INTEGRATION.md](INTEGRATION.md)**。

下面的步骤用于运行可选的网页演示。

## 可以体验什么

- 8 条明确标注的合成工单，也可以新建虚构工单。
- 同一输入分别分析、保存各自结果，并排查看差异、耗时和分类分数。
- 分类规则、低置信度人工确认、分配与重新打开、批量分析停止、结果导出。
- 来信、历史和详细分数按需展开；工单详情随页面自然滚动。

分类置信度不是准确率；两模型结果一致也不代表判断正确。本项目没有把混合合成数据的分数包装成真实业务准确率。

## 安装

需要 **Python 3.12、Node.js 22.13+**。先下载源码到一个独立目录，以下命令都在该目录执行。

```sh
python -m venv .venv
```

激活环境：Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`；macOS/Linux 使用 `source .venv/bin/activate`。

```sh
python -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
npm ci
```

CPU 推理支持 Windows 和 Linux；其他平台需要选择兼容的 PyTorch 构建。上述版本为本次验证版本，不意味着永远无需更新安全补丁。

### 安装微调权重

源码仓库不包含大文件或训练数据。需要同一版本随附的 **`laya-v5-inference.zip`**，不要下载上游基础权重冒充本项目微调结果。

```sh
python projects/laya_ft/import_checkpoint.py /path/to/laya-v5-inference.zip
```

把示例参数换成实际 ZIP 路径。导入器只接受固定 V5、固定五项规则和与源码内 `ticket_engine/model-manifest.json` 相符的每个文件哈希，拒绝覆盖已有模型和不安全归档。它安装到 `models/ticket-finetuned-v5/`，不会扫描父目录、个人下载目录或全局模型缓存。

权重未安装时，页面明确显示未就绪，不生成假结果。维护者应将权重 ZIP 作为同版本 GitHub Release 附件单独上传；目前源码中没有凭空编造下载地址。

### 可选：配置 Jev

复制 `.env.example` 为本目录下的 `.env.local`，在本机填入**你自己的** `TYPESAFE_API_KEY`。不要提交或分享这个文件。没有 Key 时仍可使用本地 Laya。

网页演示的 Jev 适配器只读取当前项目的这个文件，不读取父目录配置、系统环境中的 Key、浏览器存储或系统代理。服务地址固定为 `https://api.typesafe.ai/v1/systemone`；Key 仅由 Python 后端发送给 TypeSafe，不返回浏览器。

### 启动

```sh
npm run build
python scripts/start.py
```

打开 **http://127.0.0.1:5180/laya-ft**。后端只绑定 `127.0.0.1:8780`。启动器检查端口占用并拒绝复用其他服务；按 Ctrl+C 停止两个进程。

首次加载比后续分析慢。CPU 吞吐取决于机器和来信长度，不建议在演示服务中执行大规模批量评测。

## 数据与隐私

| 内容 | 保存 / 发送位置 |
| --- | --- |
| 示例工单 | 仓库中的合成 fixture，无真人身份 |
| 新建工单、分析结果、操作历史 | 本目录 `var/tickets.sqlite3` |
| 重置 / 手动备份 | 本目录 `var/`，重置页面不会删除备份 |
| Laya 输入 | 本机内存与当前项目数据库，不发送至模型平台 |
| Jev 输入 | 点击 Jev 分析时发送标题、正文及分类规则至 TypeSafe |
| Jev Key | 本目录 `.env.local`，不写入结果或导出 |
| 导出文件 | 用户通过浏览器选择的下载位置，可能包含自行输入的数据 |

仅用合成内容公开演示。应用不承诺自动识别、遮蔽你后来输入的个人信息，也不控制第三方 API 的保留政策。详见 [PRIVACY.md](PRIVACY.md)。

## 测试与发布检查

以下测试不需要模型权重或 API Key，不会请求 Jev：

```sh
python -m pip install --require-hashes -r backend/requirements.lock
python -m unittest discover -s backend -p "test_*.py"
python -m unittest discover -s tests -p "test_*.py"
npm run test:ui
npm run lint
npm run build
npm run typecheck
python scripts/check_public.py
```

公开仓库必须从这个独立源码目录初始化，不能把原来的个人工作区或旧 Git 历史一起上传。选择 GitHub 提供的隐私邮箱作为提交身份；提交作者与邮箱也是公开信息。

初始化独立仓库后，可启用提交前检查：

```sh
git config core.hooksPath .githooks
git add .
python scripts/check_public.py --staged --identity
```

macOS/Linux 上还需执行 `chmod +x .githooks/pre-commit`；Windows 上 Git 使用该 hook 的 shell 解释器。

检查器读取白名单 `release-files.json`，阻止未审查文件、典型密钥、本机路径、符号链接及误加入 Git 暂存区的运行数据。新增源文件需显式更新白名单并重新审查。它不能代替人工审查或证明绝无隐私问题。

需要重新打包源码时：

```sh
python scripts/export_source.py ../laya-jev-lab-source.zip
```

只打包白名单源码，不附带 Git、Key、数据库、模型、依赖、构建产物或原始文件时间戳。目标 ZIP 已存在时拒绝覆盖。

## 架构与边界

- Next.js / React 提供界面，仅代理固定本地 API，不直接访问 Jev。
- Waitress 提供本地 Python HTTP 服务；两个模型有独立推理锁。
- SQLite 事务确保保存成功后才更新内存；写入有 CSRF 校验、输入限制、频率限制、版本冲突保护和新建幂等键。
- V5 使用固定哈希的 safetensors、离线配置与随仓库保留的 Laya 推理源码；不加载 pickle 权重或远程模型代码。
- 这是**本地单用户**应用，没有账户系统、多租户或公网访问控制。不要直接把服务改为绑定公网；公开源码与公开托管服务是不同的交付形式。

许可、来源与模型局限见 [NOTICE.md](NOTICE.md)、[MODEL_CARD.md](MODEL_CARD.md)；安全维护说明见 [SECURITY.md](SECURITY.md)。
