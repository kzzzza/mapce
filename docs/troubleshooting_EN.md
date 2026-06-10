[中文](troubleshooting.md)<br>[← Back](../README_EN.md)

# Troubleshooting

## `MINERU_API_TOKEN is not set`

Set the token in `.env` and ensure the MCP Server launch command includes `--env-file`.

## `ModuleNotFoundError: No module named 'mapce'`

Run with `uv run` from the `mapce/` directory, or use `--directory` to point to the project path.

## `ImportError: Using SOCKS proxy, but 'socksio' package is not installed`

The system proxy requires the `socksio` package. It's already in project dependencies — run `uv sync`.

## `ConnectError: SSL UNEXPECTED_EOF_WHILE_READING`

The proxy is interfering with TLS connections to `cdn-mineru.openxlab.org.cn`. MinerU CDN downloads have built-in proxy-bypass logic.

## Git Clone Timeout

Verify proxy settings in `.env` (`http_proxy`, `https_proxy`). `git clone` inherits these as a subprocess.

## Embedding Model Download Stuck or Slow

First run downloads ~2 GB from HuggingFace. Users in mainland China must configure a proxy. Subsequent runs load from local cache in seconds.

## High Memory Usage During Batch Embedding

macOS may show swap even with free memory available — this is normal pre-paging behavior, not a sign of memory shortage. Embedding is optimized to batches of 32 to reduce peak usage.

## MinerU API Hangs in Standalone Scripts

The `all_proxy=socks5://` setting in `.env` causes httpx to hang (httpx does not support SOCKS proxies). The MCP Server is unaffected (HTTP proxy set explicitly via settings). Standalone scripts should filter this variable:

```python
# Skip SOCKS proxy when loading .env in standalone scripts
if key not in ("all_proxy", "ALL_PROXY"):
    os.environ[key] = value
```

## fastembed Model Warning

```
UserWarning: The model intfloat/multilingual-e5-large now uses mean pooling
instead of CLS embedding.
```

This is a normal model version change notice. Current functionality is unaffected. To exactly reproduce old behavior, install `fastembed==0.5.1`.
