"""发现与生成共用的端点鉴权 Header 构造。"""


def auth_headers(auth_field: str, api_key: str) -> dict[str, str]:
    if auth_field.lower() == "authorization" and not api_key.lower().startswith("bearer "):
        api_key = f"Bearer {api_key}"
    return {auth_field: api_key}
