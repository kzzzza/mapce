[English](troubleshooting_EN.md)<br>[← Back](../README.md)

# 常见问题

## `MINERU_API_TOKEN is not set`

在 `.env` 中设置密钥，确保 MCP Server 启动命令包含 `--env-file` 参数。

## `ModuleNotFoundError: No module named 'mapce'`

在 `mapce/` 目录下用 `uv run` 执行，或使用 `--directory` 参数指定项目路径。

## `ImportError: Using SOCKS proxy, but 'socksio' package is not installed`

系统代理需要 `socksio` 包。已在项目依赖中，执行 `uv sync` 即可。

## `ConnectError: SSL UNEXPECTED_EOF_WHILE_READING`

代理干扰了 `cdn-mineru.openxlab.org.cn` 的 TLS 连接。MinerU CDN 下载已内建绕过代理的逻辑。

## Git clone 超时

确认 `.env` 中配置了正确的代理地址（`http_proxy`、`https_proxy`、`all_proxy`）。git clone 作为子进程继承这些环境变量。

## 嵌入模型下载卡住或缓慢

首次运行从 HuggingFace 下载约 2.1 GB。中国大陆用户需配置代理。之后从本地缓存加载，秒级完成。

## 批量嵌入时内存占用高

即使有空闲内存，macOS 也可能显示 swap——这是正常的预换页行为，不代表内存不足。嵌入已优化为每批 32 条，降低峰值占用。

## 独立脚本运行时 MinerU API 挂起

`.env` 中的 `all_proxy=socks5://` 会导致 httpx 挂起（httpx 不支持 SOCKS 代理）。MCP Server 不受影响（通过 settings 显式设置 HTTP 代理）。独立脚本需过滤此变量：

```python
# 在独立脚本中加载 .env 时跳过 SOCKS 代理
if key not in ("all_proxy", "ALL_PROXY"):
    os.environ[key] = value
```

## fastembed 模型警告

```
UserWarning: The model intfloat/multilingual-e5-large now uses mean pooling
instead of CLS embedding.
```

这是正常的模型版本变更提示。当前功能不受影响。如需精确复现旧行为，可安装 `fastembed==0.5.1`。

## `service_port_in_use`

默认端口 `127.0.0.1:8765` 被其他进程占用。先运行 `uv run mapce serve-status`；如果没有可验证的 MAPCE 服务，检查占用端口的进程，或通过 `MAPCE_SERVICE_PORT` 选择其他端口。MAPCE 不会终止无法验证身份的进程。

## 服务元数据残留

服务被强制终止后可能短暂留下 `service.json`，但进程退出时内核会释放 `flock`。下一次 `mapce serve` 会在获得锁后重新写入运行信息。不要根据残留 PID 手动结束同 PID 的其他进程。

## TUI 显示终端过小

TUI 需要至少 76 列、22 行。放大终端窗口后界面会自动恢复，不需要重启。小窗口保护用于避免数据表和确认框错位。

## TUI 无法连接或后台刚被重启

进入“系统”页选择“重新连接”，或退出后重新运行 `uv run mapce`。重启后台会使已有 HTTP/MCP 连接失效；新连接会自动读取新的服务地址和本地令牌。退出 TUI 本身不会停止后台。
