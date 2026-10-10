"""Official TypeSafe HTTP adapter. Credentials never cross the local backend."""
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .errors import EngineError

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"


class ProviderError(EngineError):
    def __init__(self, message, status=502, code="provider_error"):
        self.status = status
        super().__init__(code, message, retryable=status in (429, 502, 503, 504))


def validate_config(api_key, model, timeout):
    if not isinstance(api_key, str) or not 1 <= len(api_key) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
        raise EngineError("invalid_config", "An explicit valid Jev API key is required")
    if not isinstance(model, str) or not 1 <= len(model) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in model):
        raise EngineError("invalid_config", "Invalid Jev model identifier")
    if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
        raise EngineError("invalid_config", "timeout must be between 1 and 120 seconds")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_jev(state, questions, *, api_key, model=DEFAULT_MODEL, timeout=30):
    validate_config(api_key, model, timeout)
    payload = {"model": model, "state": state, "questions": questions}
    request = Request(ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ProviderError("Jev 返回内容过大。")
            result = json.loads(raw)
            if not isinstance(result, dict) or not isinstance(result.get("model"), str):
                raise ProviderError("Jev 返回格式无效。")
            return result
    except HTTPError as exc:
        message = {401: "Jev API Key 无效，请检查本地配置。", 403: "Jev 账户没有调用权限。",
                   429: "Jev 请求达到限额，请稍后重试。", 422: "Jev 拒绝了请求格式，请检查模型版本。",
                   529: "Jev 暂时繁忙，请稍后重试。"}.get(exc.code, "Jev 服务暂时不可用，请稍后重试。")
        status = 429 if exc.code == 429 else 401 if exc.code in (401, 403) else 502
        exc.close()
        raise ProviderError(message, status) from None
    except (URLError, TimeoutError, socket.timeout):
        raise ProviderError("无法连接 Jev，请检查网络后重试。", 504) from None
    except (ValueError, UnicodeError):
        raise ProviderError("Jev 返回格式无效。") from None
