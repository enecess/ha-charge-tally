# 开发与验证

运行时最低版本仍为 Home Assistant 2025.3.4。完整测试环境固定为 Linux/WSL、Python 3.14、Home Assistant 2026.9.1；后者由 `pytest-homeassistant-custom-component==0.13.364` 提供。当前测试环境通过不代表最低版本已经实测通过。

## 安装测试依赖

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Windows 可在 WSL 中运行完整 HA 测试。纯业务核心也可在 Windows Python 3.13+ 中直接运行：

```sh
python -m unittest discover -s tests/core -p 'test_*.py'
```

## 日常检查

```sh
ruff check custom_components tests
ruff format --check custom_components tests
python -m pytest -q
node --test tests/frontend/*.test.mjs
```

需要修正格式时运行 `ruff check --fix custom_components tests` 和 `ruff format custom_components tests`，随后检查差异并重新测试。所有文本文件使用 LF。Ruff 检查包括基础 Python 错误、导入顺序和现代 Python 语法；它不等同于严格类型检查或完整 HA 质量等级认证。

HA 测试使用临时配置目录，不连接项目测试服务器。浏览器测试另需 Playwright 与浏览器运行时：通过 `PLAYWRIGHT_MODULE` 指定本机 Playwright 模块，必要时使用 `BROWSER_CHANNEL=msedge`，再执行 `node --test tests/browser/*.test.mjs`。
