# 开发与验证

最低支持版本为 **Home Assistant 2025.9.0**。兼容性矩阵固定最低版本、之后每三个月一个稳定版本，以及核验时的最新稳定版。2026-10-23 核验的最新稳定版为 **2026.10.2**（[官方安装页](https://www.home-assistant.io/installation/)）。采样不代表已逐一测试区间内每个补丁版本。

## 兼容性矩阵

版本与测试插件的对应关系来自 [PyPI 插件元数据](https://pypi.org/project/pytest-homeassistant-custom-component/)，以 `scripts/ha-test-matrix.json` 为唯一配置来源；CI 和本地运行器都读取该文件。每个环境运行完整 `tests/core` 与 `tests/ha`，不按版本跳过失败用例。

| Home Assistant | Python | pytest-homeassistant-custom-component | 2026-10-23 实测 |
| --- | --- | --- | --- |
| 2025.9.0（最低） | 3.13.15 | 0.13.277 | 410 passed |
| 2025.12.4 | 3.13.15 | 0.13.301 | 410 passed，1333 subtests passed |
| 2026.3.4 | 3.14.4 | 0.13.320 | 410 passed，1333 subtests passed |
| 2026.6.4 | 3.14.4 | 0.13.340 | 410 passed，1333 subtests passed |
| 2026.9.4 | 3.14.4 | 0.13.367 | 410 passed，1333 subtests passed |
| 2026.10.2（最新稳定） | 3.14.4 | 0.13.373 | 410 passed，1333 subtests passed |

2025.9 的旧 pytest 不单列 unittest subtests 数量，运行的测试文件和断言相同。2025.12 选择与插件原生固定依赖一致的 2025.12.4，而不覆盖插件依赖强行替换成 2025.12.5。只有 2025.9 环境额外固定 `pycares==4.11.0`：它的 `aiodns==3.5.0` 使用 pycares 5 已移除的类型，直接解析到新版会在测试收集前失败。其它环境不施加该约束。

本次发现并修复旧 HA 子条目改名后实体注册表 `original_name` 不自动刷新的兼容问题，同时保留用户自定义名称。测试适配旧插件的配置目录隔离、旧 HA 存储故障注入接口，以及原生 NFC 事件和积分传感器首次基线通知的异步等待；故障、路由、归属与金额断言均保留。

## 运行矩阵

在 Linux 或 WSL 中安装 uv，然后运行：

```sh
python3 -m pip install uv==0.12.5
python3 scripts/test_ha.py
# 只运行一个指定版本
python3 scripts/test_ha.py --version 2025.9.0
```

运行器为每个版本创建独立 `~/.cache/charge-tally-ha-<版本>` 环境，按矩阵选择 Python 3.13 或 3.14，并核验实际安装的 HA 与测试插件版本。任何安装或测试失败均返回非零状态；多版本运行会继续执行其余环境，最后汇总失败项。可用 `UV` 指定 uv 可执行文件，`HA_TEST_CACHE` 修改缓存目录。网络较慢时可设置 `UV_HTTP_TIMEOUT=180`。固定的 HA/插件组合便于重复验证，未固定的传递依赖仍可能随包索引更新。

本次完整测试日志及实际依赖清单保存在本地 `.superpowers/ha-compat-2026-10-23/`，该目录不提交。测试使用临时配置目录，不连接电表或项目测试服务器；自动化测试通过不等于在每个版本的实际部署中完成长期运行验证。

## 单一开发环境与日常检查

`requirements-dev.txt` 默认固定最新受测版本的插件，要求 Linux/WSL 和 Python 3.14：

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
ruff check custom_components tests scripts
ruff format --check custom_components tests scripts
python -m pytest -q
node --test tests/frontend/*.test.mjs
```

纯业务核心也可在 Windows Python 3.13+ 中直接运行：

```sh
python -m unittest discover -s tests/core -p 'test_*.py'
```

需要修正格式时运行 `ruff check --fix custom_components tests scripts` 和 `ruff format custom_components tests scripts`，随后检查差异并重新测试。所有文本文件使用 LF。Ruff 检查包括基础 Python 错误、导入顺序和现代 Python 语法；它不等同于严格类型检查或完整 HA 质量等级认证。

浏览器测试另需 Playwright 与浏览器运行时：通过 `PLAYWRIGHT_MODULE` 指定本机 Playwright 模块，必要时使用 `BROWSER_CHANNEL=msedge`，再执行 `node --test tests/browser/*.test.mjs`。
