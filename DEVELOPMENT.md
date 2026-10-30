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
# Install the PDF runtime dependency declared by the integration.
python -m pip install reportlab==5.1.0
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

The card browser regression also runs a real Accounting preview. Set `PYTHON` to
a Python 3.13+ interpreter when it is not available as `python3` on the test PATH.

## PDF 报表验证

运行依赖由 `manifest.json` 固定为 `reportlab==5.1.0`；PDF 解析测试依赖
`pypdf==6.21.2` 独立保存在 `requirements-test.txt`，开发依赖引用该文件。
矩阵运行器同时安装对应版本的 HA 测试插件、集成运行依赖和测试依赖；
不会读取默认最新插件的 `requirements-dev.txt` 去覆盖旧版本环境。

`python -m pytest tests/ha/test_pdf_report.py -q` 使用实际 Regular 字体生成并
解析六语 PDF，覆盖分页、长文本、缺字提示、Decimal 舍入与本期贡献语义。
字体来源、版本、SHA256 和许可位于集成的私有 `fonts/` 目录；不依赖系统字体。
PDF 排版采用串行锁保护字体注册和 ReportLab 生成，调用方必须在后台线程执行，
不能放在 HA 事件循环或账本 worker。
视觉样稿与渲染截图只保存在本地 `.superpowers/`，不提交。

## Offline accounting verification

Run tests only from an rsynced WSL `/dev-tmp` copy. The offline regression files
cover recovered cumulative-meter deltas, the 299/300-second boundary, backdating
timeout ends to the outage start, persisted deadlines, post-timeout baseline
gating, frozen bills, numeric partial costs, latest-record retention, and actual
Recorder statistics. Power-only missing samples remain incomplete; dynamic-price
gaps are not replaced with a current price. The timeout is fixed at 300 seconds.

```sh
python -m pytest -q tests/core/test_offline_accounting.py tests/core/test_offline_store.py tests/ha/test_offline_runtime.py tests/ha/test_record_cost_retention.py tests/ha/test_entity_statistics.py
```

Also run the full Python suite, frontend/browser suites, Ruff, and the six-version
matrix before release. Validate raw HA cost states and Recorder numeric points;
a correct-looking dashboard alone does not prove native entity publication.
Design documents, local diagnostic fixtures, browser assets and test logs remain
under ignored `docs/superpowers/` or `.superpowers/` directories.

## Manual end during live sampling

The card ends an active record by its fixed `record_id` and reuses its
`request_id` for retries. Meter samples can change the accounting revision
between a snapshot and the end request. `charge_tally.end` therefore accepts an
optional `expected_revision`: omit it to end the targeted active record using
the latest accounting data, or supply it for strict optimistic concurrency.
Reassign, void, and historical edits still require their revision guards.
Ending a record does not switch off a physical charger.

`tests/ha/test_manual_end.py` covers the real WebSocket service with manual and
automatic records, intervening measurements, explicit revision conflicts,
idempotent retries, and protection of a newer record from an old end request.

## Restart and sampling performance

Cold snapshots share decoded segments across their statistics queries, up to
10,000 segment entries per snapshot. The cache is discarded after the snapshot;
larger histories remain readable without retaining the entire ledger in memory.
Legacy known-cost flags use an existence query and a record-revision cache.
Non-hourly summaries reuse complete calendar windows while keeping the original
sample order and Decimal arithmetic.

Contiguous measurements after a historical gap append only the new segments.
Existing quality spans and incomplete-cost flags remain until actual historical
evidence resolves them. Late history still uses the full rebuild path.
Cold PDF imports use Home Assistant's import executor; HTTP registration stays
on the event loop.

Run `tests/ha/test_performance.py`, `tests/core/test_query_performance.py`,
`tests/core/test_incremental_gaps.py`, and `tests/ha/test_startup_import.py` for
work-count, accounting-equivalence, bounded-cache, and real cold-import checks.
Timing comparisons use synthetic local ledgers and do not establish device-side
latency.

## Record detail and export regressions

The card requests record details with `include_history=false` to avoid decoding
audit snapshots. The `records` command still includes revisions by default for
existing clients. Revision evidence and optimistic concurrency remain internal
ledger contracts; there is no separate record change-history command or card UI.

Run all checks from an rsynced WSL `/dev-tmp` checkout, including focused Python,
frontend, browser, formatting, and performance checks. Before reusing cached HA
environments, verify the installed HA and test-plugin versions against
`scripts/ha-test-matrix.json`.

```sh
python -m pytest -q tests/ha/test_export_api.py tests/core/test_nfc_rules.py tests/ha/test_nfc_manager.py tests/ha/test_config_flow.py
node --test --test-name-pattern='billing details render exponent fallback' tests/browser/card.test.mjs
```

The export regressions require a controlled HTTP error and exactly one integration
traceback for unexpected renderer failures, including a renderer that finishes
after its HTTP handler is cancelled. Expected PDF size, glyph, and content errors
keep their existing client responses. Access is rechecked after rendering.

The browser regression uses real billing details with finite decimal strings such
as `1e309`. If Intl returns the original exponent text, the amount remains visible
and only that optional rounding-note comparison is skipped. Ordinary displayed
amounts still use exact integer comparisons for rounding explanations.

HA tests set only the `sqlalchemy.engine` logger to WARNING to avoid the test
plugin's SQL INFO chatter; warnings, errors, tracebacks, and test failures remain
available. Final delivery checks include the full Python suite on all six pinned
HA versions, full frontend/browser suites, Ruff, and LF/staging checks. Keep
designs and local verification evidence in ignored Superpowers directories.
