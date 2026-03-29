import os
import logging
from typing import Optional


logger = logging.getLogger(__name__)


_default_proxy = "http://127.0.0.1:4780"
PROXY_URL = os.environ.get("PROXY_URL", _default_proxy)

_proxy_config = {
    "enabled": True,
    "url": PROXY_URL,
}


def get_proxy_config() -> dict:
    return _proxy_config.copy()


def set_proxy_config(enabled: bool, url: str):
    _proxy_config["enabled"] = enabled
    _proxy_config["url"] = url
    _clear_proxy_env()
    if enabled and url:
        os.environ["HTTP_PROXY"] = url
        os.environ["HTTPS_PROXY"] = url
        os.environ["ALL_PROXY"] = url
        os.environ["http_proxy"] = url
        os.environ["https_proxy"] = url
        os.environ["all_proxy"] = url
        logger.info(f"代理已启用: {url}")
    else:
        logger.info("代理已禁用")


def get_active_proxy() -> Optional[str]:
    if _proxy_config["enabled"] and _proxy_config["url"]:
        return _proxy_config["url"]
    return None


def _clear_proxy_env():
    for key in [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ]:
        os.environ.pop(key, None)
