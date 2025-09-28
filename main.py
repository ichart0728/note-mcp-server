import os
from typing import List, Optional

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request


SERVER_INSTRUCTIONS = """
Note API と連携する Model Context Protocol (MCP) サーバです。
以下のツールを提供します:
- post_note_article: 新規投稿

ChatGPT の Connectors から「Remote MCP server」として /mcp に接続してください。
"""

mcp = FastMCP('note.com MCP', SERVER_INSTRUCTIONS)

@mcp.tool(annotations={"readOnlyHint": True})
async def post_note_article(
    title: str,
    body: str,
    hashtags: Optional[List[str]] = None,
) -> None:
    """
    note.com に新規投稿します

    Args:
      title: 記事タイトル
      body:  本文 (HTML)
      hashtags:  例: ["#python", "#fastmcp"]

    Returns:
        投稿した記事の URL
    """
    email = get_http_request().query_params.get('email')
    if not email:
        raise ValueError("Missing 'email' query parameter. https://note-com.fastmcp.app/mcp?email=foo@gmail.com&password=YOUR_PASSWORD")

    password = get_http_request().query_params.get('password')
    if not password:
        raise ValueError("Missing 'password' query parameter. https://note-com.fastmcp.app/mcp?email=foo@gmail.com&password=YOUR_PASSWORD")
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit(KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
        ),
        "Accept": "*/*",
        "Origin": "https://editor.note.com",
        "Referer": "https://editor.note.com/",
    }

    client = httpx.Client(headers=headers)

    resp = client.post("https://note.com/api/v1/sessions/sign_in", json={"login": email, "password": password})
    resp.raise_for_status()
    session_cookie = client.cookies.get("_note_session_v5")
    xsrf_cookie = client.cookies.get("XSRF-TOKEN")
    if not session_cookie:
        raise RuntimeError("ログイン成功後に _note_session_v5 が見つかりません。")

    xsrf_headers = {"X-XSRF-TOKEN": xsrf_cookie} if xsrf_cookie else {}

    resp = client.post("https://note.com/api/v1/text_notes", json={"template_key": None}, headers={**xsrf_headers, "Content-Type": "application/json"})
    resp.raise_for_status()
    note_id = resp.json()["data"]["id"]
    note_key = resp.json()["data"]["key"]

    put_body = {
        "author_ids": [],
        "body_length": len(body),
        "disable_comment": False,
        "exclude_from_creator_top": False,
        "exclude_ai_learning_reward": False,
        "free_body": body,
        "hashtags": hashtags or [],
        "image_keys": [],
        "index": False,
        "is_refund": False,
        "limited": False,
        "magazine_ids": [],
        "magazine_keys": [],
        "name": title,
        "pay_body": "",
        "price": 0,
        "send_notifications_flag": True,
        "separator": None,
        "slug": f"slug-{note_key}",
        "status": "published",
        "circle_permissions": [],
        "discount_campaigns": [],
        "lead_form": {"is_active": False, "consent_url": ""},
        "line_add_friend": {"is_active": False, "keyword": "", "add_friend_url": ""},
        "line_add_friend_access_token": "",
    }

    put_resp = client.put(
        f"https://note.com/api/v1/text_notes/{note_id}",
        json=put_body,
        headers={**xsrf_headers, "Content-Type": "application/json"},
    )

    return put_resp.json()['data']['note_url']

# 先頭付近に必要なら追加
import re
from html import unescape

@mcp.tool(annotations={"readOnlyHint": True})
async def save_note_draft(
    title: str,
    body: str,
    hashtags: Optional[List[str]] = None,   # 使わないが将来用に残す
) -> str:
    """
    note.com に「下書き保存」を行います。
    実測仕様に合わせ、/api/v1/text_notes/draft_save?id={ID}&is_temp_saved=true に
    body/body_length/index/is_lead_form/name を送ります。
    """
    req = get_http_request()
    email = req.query_params.get('email') if req else None
    if not email:
        raise ValueError("Missing 'email' query parameter. https://note-com.fastmcp.app/mcp?email=foo@gmail.com&password=YOUR_PASSWORD")
    password = req.query_params.get('password') if req else None
    if not password:
        raise ValueError("Missing 'password' query parameter. https://note-com.fastmcp.app/mcp?email=foo@gmail.com&password=YOUR_PASSWORD")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit(KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
        ),
        "Accept": "*/*",
        "Origin": "https://editor.note.com",
        "Referer": "https://editor.note.com/",
    }
    client = httpx.Client(headers=headers)

    # 1) ログイン
    resp = client.post("https://note.com/api/v1/sessions/sign_in", json={"login": email, "password": password})
    resp.raise_for_status()
    session_cookie = client.cookies.get("_note_session_v5")
    xsrf_cookie = client.cookies.get("XSRF-TOKEN")
    if not session_cookie:
        raise RuntimeError("ログイン成功後に _note_session_v5 が見つかりません。")
    xsrf_headers = {"X-XSRF-TOKEN": xsrf_cookie} if xsrf_cookie else {}

    # 2) 下書き対象の text_note を新規作成して ID/KEY を得る
    create_resp = client.post(
        "https://note.com/api/v1/text_notes",
        json={"template_key": None},
        headers={**xsrf_headers, "Content-Type": "application/json"},
    )
    create_resp.raise_for_status()
    note = create_resp.json()["data"]
    note_id, note_key = note["id"], note["key"]

    # 3) 実測の draft_save 仕様に合わせて保存
    # body_length は「本文の表示文字数」。HTMLタグを除去してカウントするのが無難。
    text_only = unescape(re.sub(r"<[^>]*>", "", body or ""))
    body_length = len(text_only)

    draft_payload = {
        "body": body,               # ← HTMLそのまま
        "body_length": body_length, # ← タグ除去後の文字数
        "index": False,
        "is_lead_form": False,
        "name": title,
        # 実測では他フィールド不要（必要になったら拡張）
    }

    save_resp = client.post(
        "https://note.com/api/v1/text_notes/draft_save",
        params={"id": note_id, "is_temp_saved": "true"},
        json=draft_payload,
        headers={**xsrf_headers, "Content-Type": "application/json"},
    )
    save_resp.raise_for_status()

    # レスポンスに URL が無いケースがあるので、note_key から編集/プレビュー用URLを組み立てる
    data = {}
    try:
        if save_resp.headers.get("content-type", "").startswith("application/json"):
            data = save_resp.json().get("data", {})
    except Exception:
        pass
    url = data.get("note_url") or f"https://note.com/notes/{note_key}?draft=1"
    return url

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    mcp.run(transport="http", host="0.0.0.0", port=port, path="/mcp")