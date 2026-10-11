"""人民法院案例库 API 客户端"""

from __future__ import annotations

import base64
import errno
from io import StringIO
import json
import os
import re
import stat
import time
from typing import Any

import httpx
from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

# Windows migration copy: resolve this installation before any startup read.
from windows_case_access import access_path
DEFAULT_CREDENTIAL_PATH = access_path()
_WINDOWS = os.name == "nt"
MAX_CREDENTIAL_BYTES = 64 * 1024


class CredentialError(Exception):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__({
            "missing": "本地凭据文件不存在。",
            "empty": "本地凭据为空。",
            "unreadable": "本地凭据文件不可读。",
            "unsafe": "本地凭据文件安全属性不符合要求。",
            "oversize": "本地凭据文件超过大小限制。",
            "malformed": "本地凭据格式不正确。",
            "duplicate": "本地凭据包含重复配置。",
            "changed": "验证期间本地凭据已变化。",
        }.get(kind, "本地凭据不可用。"))


class TokenExpiredError(Exception):
    def __init__(self, message: str = "") -> None:
        super().__init__("认证已失效，需要重新登录官网。")


class ApiError(Exception):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__({
            "timeout": "官网请求超时。",
            "network": "官网网络连接失败。",
            "forbidden": "官网拒绝访问。",
            "http": "官网 HTTP 请求失败。",
            "response": "官网响应格式不正确。",
            "business": "官网未完成请求。",
        }.get(kind, "官网请求失败。"))


def _read_bindings(
    path: str | os.PathLike[str], *, validate_token_binding: bool = True,
) -> list[tuple[str, str | None]]:
    """Read a bounded ordinary file; python-dotenv parsing has no interpolation."""
    try:
        if _WINDOWS:
            from windows_private import open_file
            fd = open_file(path, private=True)
        else:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise CredentialError("missing") from None
    except ValueError:
        raise CredentialError("unsafe") from None
    except OSError as error:
        kind = "unsafe" if error.errno == errno.ELOOP else "unreadable"
        raise CredentialError(kind) from None
    except Exception:
        if _WINDOWS:
            raise CredentialError("unreadable") from None
        raise
    try:
        info = os.fstat(fd)
        if not _WINDOWS:
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CredentialError("unsafe")
            if not info.st_mode & stat.S_IRUSR:
                raise CredentialError("unreadable")
        if info.st_size > MAX_CREDENTIAL_BYTES:
            raise CredentialError("oversize")
        chunks = []
        remaining = MAX_CREDENTIAL_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
    except OSError:
        raise CredentialError("unreadable") from None
    finally:
        os.close(fd)
    if len(content) > MAX_CREDENTIAL_BYTES:
        raise CredentialError("oversize")
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        raise CredentialError("malformed") from None
    settings = []
    token_count = 0
    for binding in parse_stream(StringIO(text)):
        is_target = re.match(
            r"\s*(?:export\s+)?['\"]?RMFYALK_TOKEN(?=[\s'\"=:]|$)",
            binding.original.string,
        )
        if validate_token_binding and is_target and (binding.error or binding.key != "RMFYALK_TOKEN"):
            raise CredentialError("malformed")
        if validate_token_binding and binding.key == "RMFYALK_TOKEN":
            token_count += 1
            if token_count > 1:
                raise CredentialError("duplicate")
            if binding.value is None:
                raise CredentialError("malformed")
        if not binding.error and binding.key is not None:
            # parse_stream returns literal values and never resolves ${variables}.
            settings.append((binding.key, binding.value))
    return settings


def _validate_token(token: str | None) -> str:
    if token is None or token == "":
        raise CredentialError("empty")
    if not isinstance(token, str) or not token.isascii() or any(
        ord(char) < 32 or ord(char) == 127 for char in token
    ) or token.strip() != token or " " in token:
        raise CredentialError("malformed")
    return token


def _is_expired(token: str) -> bool:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = payload.get("exp")
        if isinstance(exp, bool):
            return False
        if isinstance(exp, str) and exp.isascii() and exp.isdigit():
            exp = int(exp)
        return isinstance(exp, (int, float)) and exp <= time.time()
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


def _startup_export_dir() -> str:
    if "EXPORT_DIR" in os.environ:
        return os.environ["EXPORT_DIR"]
    try:
        settings = _read_bindings(
            DEFAULT_CREDENTIAL_PATH, validate_token_binding=False,
        )
    except CredentialError:
        return ""
    # Preserve ordered path expansion locally, returning only the export setting.
    resolved = {}
    for key, value in settings:
        if key == "RMFYALK_TOKEN":
            continue
        values = {**resolved, **os.environ}
        values.pop("RMFYALK_TOKEN", None)
        resolved[key] = "".join(atom.resolve(values) for atom in parse_variables(value or ""))
    return resolved.get("EXPORT_DIR", "")


DEFAULT_EXPORT_DIR = _startup_export_dir()

BASE_URL = "https://rmfyalk.court.gov.cn/cpws_al_api/api/"

CASE_TYPE_MAP = {
    "all": "cpwsAl_qb",
    "guiding": "cpwsAl_01",
    "reference": "cpwsAl_02",
}

SEARCH_FIELD_MAP = {
    "qw": "全文",
    "title": "标题",
    "albh": "案例编号",
    "cprq": "裁判日期",
    "keyword": "关键词",
    "jbaq": "基本案情",
    "cply": "裁判理由",
}


class RmfyalkClient:
    def __init__(self, credential_path: str | os.PathLike[str] | None = None) -> None:
        self.credential_path = credential_path if credential_path is not None else DEFAULT_CREDENTIAL_PATH
        self._rejected_tokens: set[str] = set()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Content-Type": "application/json",
                "Referer": "https://rmfyalk.court.gov.cn/view/list.html",
                "Origin": "https://rmfyalk.court.gov.cn",
            }
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=30.0,
                verify=True,
                headers=headers,
            )
        return self._client

    @property
    def token(self) -> str:
        token = _validate_token(dict(_read_bindings(self.credential_path)).get("RMFYALK_TOKEN"))
        if token in self._rejected_tokens or _is_expired(token):
            self._rejected_tokens.add(token)
            raise TokenExpiredError()
        return token

    async def post(
        self, path: str, body: dict | None = None, *, expected_token: str | None = None,
    ) -> dict[str, Any]:
        token = self.token
        if expected_token is not None and token != expected_token:
            raise CredentialError("changed")
        return await self._request(self._get_client(), "POST", path, token, json=body or {})

    async def get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        token = self.token
        return await self._request(self._get_client(), "GET", path, token, params=params)

    async def _request(
        self, session: httpx.AsyncClient, method: str, path: str, token: str,
        *, block_generation: bool = True, **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            resp = await session.request(method, path, headers={"faxin-cpws-al-token": token}, **kwargs)
        except httpx.TimeoutException:
            raise ApiError("timeout") from None
        except httpx.RequestError:
            raise ApiError("network") from None
        if resp.status_code == 401:
            if block_generation:
                self._rejected_tokens.add(token)
            raise TokenExpiredError()
        if resp.status_code == 403:
            raise ApiError("forbidden")
        if not 200 <= resp.status_code < 300:
            raise ApiError("http")
        try:
            data = resp.json()
        except (ValueError, UnicodeError):
            raise ApiError("response") from None
        if not isinstance(data, dict) or type(data.get("code")) is not int:
            raise ApiError("response")
        if data["code"] == 401:
            if block_generation:
                self._rejected_tokens.add(token)
            raise TokenExpiredError()
        if data["code"] != 0:
            raise ApiError("business")
        return data

    async def verify_token(self, token: str) -> dict[str, Any]:
        """Compatibility check of an explicit value; never changes the local source."""
        token = _validate_token(token)
        if _is_expired(token):
            raise TokenExpiredError()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Content-Type": "application/json",
            "Referer": "https://rmfyalk.court.gov.cn/view/list.html",
            "Origin": "https://rmfyalk.court.gov.cn",
        }
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0, verify=True, headers=headers) as session:
            return await self._request(
                session, "POST", "user/getUserInfo", token,
                block_generation=False, json={"state": ""},
            )

    def build_search_body(
        self,
        keyword: str = "",
        search_field: str = "qw",
        case_type: str = "all",
        match_type: str = "fuzzy",
        page: int = 1,
        page_size: int = 10,
        sort_field: str = "",
        # 高级检索：文本字段
        key_title: str | None = None,
        key_content: str | None = None,
        case_number: str | None = None,
        case_ref: str | None = None,
        keyword_tag: str | None = None,
        # 高级检索：下拉字段
        sort_id: str | None = None,
        case_sort: str | None = None,
        court_level: str | None = None,
        trial_procedure: str | None = None,
        court: str | None = None,
        doc_type: str | None = None,
    ) -> dict:
        lib_code = CASE_TYPE_MAP.get(case_type, "cpwsAl_qb")
        adv_fields = [
            key_title, key_content, case_number, case_ref, keyword_tag,
            sort_id, case_sort, court_level, trial_procedure, court, doc_type,
        ]
        is_advanced = any(v is not None for v in adv_fields)
        user_search_type = 2 if match_type == "fuzzy" else 1

        search_params: dict[str, Any] = {
            "userSearchType": user_search_type,
            "isAdvSearch": "1" if is_advanced else "0",
            "selectValue": [search_field],
            "lib": lib_code,
            "sort_field": sort_field,
        }

        # 一般检索关键词
        if keyword:
            search_params["keyTitle"] = [keyword]

        # 高级检索字段（AND 组合）
        if is_advanced:
            if key_title:
                search_params["keyTitle"] = [key_title]
            if key_content:
                search_params["keyContent"] = [key_content]
            if case_number:
                search_params["cpws_al_no"] = case_number
            if case_ref:
                search_params["cpws_al_ajzh"] = case_ref
            if keyword_tag:
                search_params["keyword_cpwsAl"] = [keyword_tag]
            if sort_id:
                search_params["sort_id_cpwsAl"] = sort_id
            if case_sort:
                search_params["case_sort_id_cpwsAl"] = case_sort
            if court_level:
                search_params["fyjb_id_cpwsAl"] = court_level
            if trial_procedure:
                search_params["slcx_id_cpwsAl"] = trial_procedure
            if court:
                search_params["slfy_id_cpwsAl"] = court
            if doc_type:
                search_params["wslx_id_cpwsAl"] = doc_type

        return {
            "page": page,
            "size": page_size,
            "lib": "qb",
            "searchParams": search_params,
        }


client = RmfyalkClient()
