import requests
from requests.exceptions import RequestException

TAVILY_API_ENDPOINT = "https://api.tavily.com"


def check_api_key(api_key: str) -> bool:
    """
    检查 API 密钥是否被授权用于给定的用例

    Args:
        api_key: 要检查的 API 密钥

    Returns:
        bool: 如果被授权则返回 True

    Raises:
        requests.exceptions.HTTPError: 如果授权失败
        RequestException: 如果请求失败
    """
    try:
        payload = {"api_key": api_key, "use_case": "chat"}

        response = requests.post(f"{TAVILY_API_ENDPOINT}/authorize-use-case", json=payload)

        response.raise_for_status()

        result = response.json()

        if not result.get("success"):
            raise requests.exceptions.HTTPError("授权失败")

        return True

    except requests.exceptions.HTTPError:
        raise
    except RequestException:
        raise
