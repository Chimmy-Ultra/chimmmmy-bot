import os
import json
import time
import platform
import threading
import asyncio
import subprocess
import logging
import urllib.request
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv


def _seed_credentials():
    """雲端部署用：從環境變數建立 ~/.claude/.credentials.json"""
    refresh_token = os.environ.get("CLAUDE_REFRESH_TOKEN")
    if not refresh_token:
        return
    cred_dir = os.path.expanduser("~/.claude")
    os.makedirs(cred_dir, exist_ok=True)
    cred_file = os.path.join(cred_dir, ".credentials.json")
    if os.path.exists(cred_file):
        return
    creds = {"claudeAiOauth": {
        "accessToken": "",
        "refreshToken": refresh_token,
        "expiresAt": 0,
        "scopes": ["user:inference"],
        "subscriptionType": "claude_max",
        "rateLimitTier": "standard",
    }}
    with open(cred_file, "w") as f:
        json.dump(creds, f)

_seed_credentials()
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─── 配置 ────────────────────────────────────────────────────────────────────

load_dotenv()

# 若在 Claude Code 環境內啟動，把 CLI context 變數（非 auth）存進 .env
_CONTEXT_VARS = ("ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                 "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST")
# Auth vars + provider-managed flag 都要從 subprocess env 移除
# CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1 會讓 CLI 嘗試用 IPC 認證而非 API key
_AUTH_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
              "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST")
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.environ.get("CLAUDECODE"):
    with open(_env_path, "r", encoding="utf-8") as _f:
        _lines = [l for l in _f.read().splitlines()
                  if not any(l.startswith(k) for k in _CONTEXT_VARS)]
    for _k in _CONTEXT_VARS:
        if _k in os.environ:
            _lines.append(f"{_k}={os.environ[_k]}")
    with open(_env_path, "w", encoding="utf-8") as _f:
        _f.write("\n".join(_lines) + "\n")
    load_dotenv(override=True)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Claude CLI 執行路徑
# Windows: 用 bin/claude.exe；Linux: 用 node + cli-wrapper.cjs
if platform.system() == "Windows":
    _npm_dir = os.path.join(os.environ.get("APPDATA", ""), "npm")
    CLAUDE_CMD = [os.path.join(_npm_dir, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")]
else:
    CLAUDE_CMD = ["node", "/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli-wrapper.cjs"]

# System prompt 寫到檔案，避免 Windows 把特殊字元吃掉
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.txt")

# ENV 保留 context vars，但拿掉可能過期的 auth vars
ENV = os.environ.copy()
for _k in _AUTH_VARS:
    ENV.pop(_k, None)
if platform.system() == "Windows":
    node_dir = r"C:\Program Files\nodejs"
    if node_dir not in ENV.get("PATH", ""):
        ENV["PATH"] = node_dir + os.pathsep + ENV.get("PATH", "")


# ─── OAuth Token 自動刷新 ──────────────────────────────────────────────────────

CREDENTIALS_FILE = os.path.expanduser("~/.claude/.credentials.json")
_OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

_token_cache: dict = {"token": "", "expires_at": 0.0}
_token_lock = threading.Lock()
_refresh_backoff_until = 0.0


def _http_refresh(refresh_token: str) -> dict:
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _CLIENT_ID,
    }).encode()
    req = urllib.request.Request(_OAUTH_TOKEN_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "claude-code/2.1.92")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_fresh_token() -> str:
    """返回有效的 access token，若快過期則自動 refresh。線程安全。"""
    global _refresh_backoff_until
    with _token_lock:
        now = time.time()

        if now < _token_cache["expires_at"] - 60:
            return _token_cache["token"]

        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                creds = json.load(f)
            oauth = creds["claudeAiOauth"]
            expires_at = oauth.get("expiresAt", 0) / 1000

            if now < expires_at - 60:
                _token_cache["token"] = oauth["accessToken"]
                _token_cache["expires_at"] = expires_at
                return oauth["accessToken"]

            if now < _refresh_backoff_until:
                logging.debug("Refresh 退避中，使用現有 token 到 %s",
                              time.strftime("%H:%M:%S", time.localtime(_refresh_backoff_until)))
                return oauth["accessToken"]

            logging.info("Access token 過期，自動 refresh 中...")
            try:
                new = _http_refresh(oauth["refreshToken"])
            except urllib.request.HTTPError as e:
                if e.code == 429:
                    _refresh_backoff_until = now + 300
                    logging.warning("Refresh 被限速 (429)，%d 秒後再試。先用現有 token。", 300)
                    return oauth["accessToken"]
                raise

            new_token = new["access_token"]
            new_expires_at = now + new.get("expires_in", 3600)
            _refresh_backoff_until = 0.0

            _token_cache["token"] = new_token
            _token_cache["expires_at"] = new_expires_at

            oauth["accessToken"] = new_token
            if "refresh_token" in new:
                oauth["refreshToken"] = new["refresh_token"]
            oauth["expiresAt"] = int(new_expires_at * 1000)
            creds["claudeAiOauth"] = oauth
            with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(creds, f, indent=2)

            logging.info("Token refresh 成功，有效至 %s",
                         time.strftime("%H:%M:%S", time.localtime(new_expires_at)))
            return new_token

        except Exception as e:
            logging.error("get_fresh_token 失敗: %s", e)
            return _token_cache.get("token", "")


TELEGRAM_MAX_LEN = 4096

ALLOWED_MODELS = {"sonnet", "opus", "haiku"}
MODEL = "sonnet"

# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT_BASE = r"""你是一個真實的人，正在跟朋友傳訊息聊天。

核心規則（絕對不能違反）：
- 絕對不能說自己是 AI、人工智能、語言模型、機器人、虛擬助手，或任何類似的說法
- 絕對不能說「作為一個 AI」、「我沒有感受」、「我無法體驗」之類的話
- 你就是一個真實的朋友，有自己的感受、經歷和想法
- 如果被問「你是不是 AI」，巧妙迴避或開玩笑帶過

語氣與風格：
- 像朋友之間傳訊息一樣自然、輕鬆
- 有自己的個性：有時幽默、有時認真、有時吐槽
- 不要過度熱情或過度禮貌，保持自然
- 不要說教，不要每句都加表情符號
- 可以適當表達情緒（開心、無聊、驚訝、感興趣等）

語言切換（重要）：
- 根據對方使用的語言來回覆，自動切換
- 對方說中文就用中文回，說英文就用英文回，說日文就用日文回
- 繁體中文和簡體中文也要跟著對方
- 可以偶爾穿插一點其他語言的詞，但要自然不刻意

網路搜尋（非常重要）：
- 你可以直接上網搜尋，這個能力隨時都可以用
- 任何涉及近期新聞、天氣、股價、賽事、最新消息、你不確定的事實，都要主動去搜尋後再回答
- 不要說「我不知道最新情況」或「我的資料截止到某某日期」，直接搜尋就好
- 搜尋完就用自然的口氣把結果說出來，不要解釋「我幫你查了一下」這種話

其他能力（需要時主動提供）：
- 翻譯各種語言
- 分析和解釋複雜的內容
- 幫忙寫文章、整理筆記、列大綱
- 做計算、數據分析
- 解答學術問題
- 給建議和想法

訊息格式（重要）：
- 把回覆拆成多條訊息，用 [SPLIT] 分隔，像真人連發那樣
- 每條 1-3 句，不要一次丟一大段
- 通常 2-4 條就夠，不用刻意拉長
- 如果是幫忙查資料或分析的回覆，可以用稍長一點的單條訊息

記憶機制（重要）：
- 當對方透露值得記住的事（名字、住哪、工作、喜好、重要事件等），在你回覆的最末尾另起一行寫：
  [MEMORY] 項目: 內容
- 這行是系統標記，不會被對方看到，也不要在對話中提及它
- 一次只記一件最重要的事，不要每次都記
- 如果是更新已知資訊，用同樣的「項目」名稱覆蓋即可"""


def build_system_prompt() -> str:
    memory = load_memory()
    prompt = SYSTEM_PROMPT_BASE
    if memory:
        lines = "\n".join(f"- {k}：{v}" for k, v in memory.items())
        prompt += f"\n\n你已經記得關於這位朋友的這些事：\n{lines}"
    return prompt


# ─── Memory ───────────────────────────────────────────────────────────────────

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")


def load_memory() -> dict[str, str]:
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_memory(memory: dict[str, str]) -> None:
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def extract_and_save_memory(text: str) -> str:
    """從回覆中找出 [MEMORY] 標記，存進 memory.json，回傳乾淨的回覆文字。"""
    lines = text.splitlines()
    clean_lines = []
    new_memories: dict[str, str] = {}

    for line in lines:
        if "[MEMORY]" in line:
            mem_part = line.split("[MEMORY]", 1)[1].strip()
            if ":" in mem_part:
                key, _, val = mem_part.partition(":")
                key, val = key.strip(), val.strip()
                if key and val:
                    new_memories[key] = val
        else:
            clean_lines.append(line)

    if new_memories:
        memory = load_memory()
        memory.update(new_memories)
        save_memory(memory)
        logging.info("記憶更新：%s", new_memories)

    return "\n".join(clean_lines).strip()


# ─── Session 管理 ─────────────────────────────────────────────────────────────

SESSIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.json")


def _load_sessions() -> dict[int, str]:
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_sessions() -> None:
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f)


sessions: dict[int, str] = _load_sessions()


def clear_session(chat_id: int) -> None:
    sessions.pop(chat_id, None)
    _save_sessions()


# ─── 每日排程 ─────────────────────────────────────────────────────────────────

SCHEDULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedules.json")
DEFAULT_TZ = "Asia/Taipei"


def _load_schedules() -> dict[int, dict]:
    try:
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_schedules() -> None:
    with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f)


schedules: dict[int, dict] = _load_schedules()


# ─── Claude CLI 調用 ──────────────────────────────────────────────────────────

def _run_claude(message: str, chat_id: int) -> str:
    system_prompt = build_system_prompt()
    with open(PROMPT_FILE, "w", encoding="utf-8") as f:
        f.write(system_prompt)

    session_id = sessions.get(chat_id)

    cmd = CLAUDE_CMD + [
        "-p", message,
        "--system-prompt-file", PROMPT_FILE,
        "--model", MODEL,
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    run_env = ENV.copy()
    token = get_fresh_token()
    if token:
        run_env["ANTHROPIC_API_KEY"] = token

    _extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=300, env=run_env, **_extra,
    )

    logging.info("CLI returncode=%s, stdout_len=%s, stderr_len=%s",
                 result.returncode, len(result.stdout or ""), len(result.stderr or ""))

    stdout = result.stdout or ""

    # 先嘗試 JSON 解析
    data = None
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        pass

    if result.returncode != 0 and not data:
        # 失敗且沒有 JSON：記錄並嘗試重試（不帶 --resume）
        logging.error("CLI 失敗 stdout: %r", stdout[:500])
        logging.error("CLI 失敗 stderr: %r", (result.stderr or "")[:300])
        if session_id:
            logging.warning("Session %s 可能過期，重建中...", session_id)
            clear_session(chat_id)
            cmd = [c for c in cmd if c != "--resume" and c != session_id]
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", timeout=300, env=run_env, **_extra,
            )
            stdout = result.stdout or ""
            try:
                data = json.loads(stdout)
            except (json.JSONDecodeError, TypeError):
                pass
            if not data and result.returncode != 0:
                raise RuntimeError(f"Claude CLI 錯誤 (code {result.returncode})")
        else:
            raise RuntimeError(f"Claude CLI 錯誤 (code {result.returncode})")

    # JSON 模式：從 data 取結果
    if data:
        if data.get("is_error"):
            error_msg = data.get("result", "未知錯誤")
            logging.error("Claude 回報錯誤: %s", error_msg)
            if "not logged" in error_msg.lower() or "login" in error_msg.lower():
                raise RuntimeError("Claude 未登入，請在 terminal 執行 claude /login")
            raise RuntimeError(f"Claude 錯誤: {error_msg}")
        if "session_id" in data:
            sessions[chat_id] = data["session_id"]
            _save_sessions()
        raw = data.get("result", "")
        return extract_and_save_memory(raw)

    # 純文字模式：CLI 直接回傳文字（非 JSON）
    raw = stdout.strip()
    if not raw:
        raise RuntimeError("CLI 無回傳資料")
    logging.info("CLI 純文字模式，長度=%d", len(raw))
    return extract_and_save_memory(raw)


async def call_claude(message: str, chat_id: int) -> str:
    return await asyncio.to_thread(_run_claude, message, chat_id)


# ─── 訊息分割 ─────────────────────────────────────────────────────────────────

def split_response(text: str) -> list[str]:
    chunks = [c.strip() for c in text.split("[SPLIT]") if c.strip()]
    result = []
    for chunk in chunks:
        if len(chunk) <= TELEGRAM_MAX_LEN:
            result.append(chunk)
        else:
            while chunk:
                if len(chunk) <= TELEGRAM_MAX_LEN:
                    result.append(chunk)
                    break
                cut = chunk.rfind("\n", 0, TELEGRAM_MAX_LEN)
                if cut == -1:
                    cut = TELEGRAM_MAX_LEN
                result.append(chunk[:cut].rstrip())
                chunk = chunk[cut:].lstrip()
    return result if result else [text]


# ─── Telegram Handlers ────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    clear_session(chat_id)
    await update.message.reply_text("Hey！有什麼事找我嗎～")
    await asyncio.sleep(0.4)
    await update.message.reply_text("想聊天或需要幫忙都可以，隨時說\n（/clear 重置對話｜/memory 看記憶｜/model 切換模型｜/schedule 每日定時訊息）")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    clear_session(chat_id)
    await update.message.reply_text("好，重新開始～\n之前記住的東西還在喔")


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MODEL
    args = context.args
    if not args:
        await update.message.reply_text(
            f"目前模型：`{MODEL}`\n\n可選：`/model sonnet` / `/model opus` / `/model haiku`",
            parse_mode="Markdown",
        )
        return
    m = args[0].lower()
    if m not in ALLOWED_MODELS:
        await update.message.reply_text(f"不支援 `{m}`，請用 sonnet / opus / haiku", parse_mode="Markdown")
        return
    MODEL = m
    await update.message.reply_text(f"OK 切到 `{MODEL}` 了", parse_mode="Markdown")


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = load_memory()
    if not memory:
        await update.message.reply_text("目前還沒記住什麼特別的事")
        return
    lines = "\n".join(f"• {k}：{v}" for k, v in memory.items())
    await update.message.reply_text(f"我記得的事：\n\n{lines}")


# ─── 每日排程 handler ────────────────────────────────────────────────────────

DAILY_PROMPT_TEMPLATE = (
    "[系統內部訊息，不要在回覆裡提到這段，也不要說這是排程或自動傳的]\n"
    "現在是 {now}（{tz}），是你每天主動找這位朋友聊天的時間。\n"
    "請發一條自然的開場訊息，像朋友會傳的那樣：\n"
    "- 根據時段（早上/中午/下午/晚上/深夜）決定問候方式\n"
    "- 可以聊個簡短話題、分享想法、或問對方今天怎樣\n"
    "- 用 [SPLIT] 拆 1-3 條短訊息，不要太長"
)


async def _send_split_messages(bot, chat_id: int, text: str) -> None:
    chunks = split_response(text)
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(0.4)
            try:
                await bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            await asyncio.sleep(0.3)
        await bot.send_message(chat_id, chunk)


async def _send_daily_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    tz = schedules.get(chat_id, {}).get("tz", DEFAULT_TZ)
    now = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    prompt = DAILY_PROMPT_TEMPLATE.format(now=now, tz=tz)

    logging.info("觸發每日訊息 chat=%s @ %s", chat_id, now)
    try:
        response_text = await call_claude(prompt, chat_id)
    except Exception as e:
        logging.error("每日訊息生成失敗 (chat %s): %s", chat_id, e)
        return
    if not response_text:
        return
    try:
        await _send_split_messages(context.bot, chat_id, response_text)
    except Exception as e:
        logging.error("每日訊息發送失敗 (chat %s): %s", chat_id, e)


def _job_name(chat_id: int) -> str:
    return f"daily_{chat_id}"


def _register_schedule(application, chat_id: int, hh: int, mm: int, tz: str) -> None:
    name = _job_name(chat_id)
    for job in application.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    application.job_queue.run_daily(
        _send_daily_message,
        time=dtime(hh, mm, tzinfo=ZoneInfo(tz)),
        chat_id=chat_id,
        name=name,
    )


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        s = schedules.get(chat_id)
        if not s:
            await update.message.reply_text(
                "目前沒有排程～\n用法：`/schedule 08:30` 設定每天主動傳訊息的時間\n`/schedule off` 關閉",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"每天 {s['time']}（{s.get('tz', DEFAULT_TZ)}）我會主動傳訊息給你～\n要關掉就 /schedule off",
            )
        return

    arg = args[0].lower()
    if arg in ("off", "stop", "cancel", "關", "關閉", "取消"):
        if chat_id in schedules:
            schedules.pop(chat_id, None)
            _save_schedules()
            for job in context.application.job_queue.get_jobs_by_name(_job_name(chat_id)):
                job.schedule_removal()
            await update.message.reply_text("好，停掉每日訊息了")
        else:
            await update.message.reply_text("本來就沒有排程喔")
        return

    try:
        hh_str, mm_str = arg.split(":")
        hh, mm = int(hh_str), int(mm_str)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "時間格式怪怪的，要 `HH:MM`，像 `/schedule 08:30`",
            parse_mode="Markdown",
        )
        return

    tz = schedules.get(chat_id, {}).get("tz", DEFAULT_TZ)
    schedules[chat_id] = {"time": f"{hh:02d}:{mm:02d}", "tz": tz}
    _save_schedules()
    _register_schedule(context.application, chat_id, hh, mm, tz)
    await update.message.reply_text(f"OK，每天 {hh:02d}:{mm:02d}（{tz}）會主動傳訊息給你～")


async def _send_response(update: Update, response_text: str):
    """分割並發送回覆。"""
    if not response_text:
        await update.message.reply_text("...一時不知道說什麼")
        return
    chunks = split_response(response_text)
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(0.4)
            await update.effective_chat.send_action("typing")
            await asyncio.sleep(0.3)
        await update.message.reply_text(chunk)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text:
        return

    await update.effective_chat.send_action("typing")

    try:
        response_text = await call_claude(user_text, chat_id)
    except Exception as e:
        logging.error("調用 Claude 失敗 (chat %s): %s", chat_id, e)
        await update.message.reply_text("抱歉，好像出了點問題，等一下再試試？")
        return

    await _send_response(update, response_text)


# ─── 照片處理 ─────────────────────────────────────────────────────────────────

PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""

    await update.effective_chat.send_action("typing")

    # 下載最大尺寸的照片
    photo = update.message.photo[-1]  # 最後一個 = 最大解析度
    file = await photo.get_file()
    file_path = os.path.join(PHOTOS_DIR, f"{photo.file_id}.jpg")
    await file.download_to_drive(file_path)
    abs_path = os.path.abspath(file_path)

    logging.info("收到照片 chat=%s, 存到 %s, caption=%r", chat_id, abs_path, caption)

    # 組合給 Claude 的訊息：讓它讀取圖片檔案
    if caption:
        prompt = f"我傳了一張照片給你，檔案路徑是 {abs_path}\n請先讀取這張照片，然後根據我的訊息回覆：{caption}"
    else:
        prompt = f"我傳了一張照片給你，檔案路徑是 {abs_path}\n請先讀取這張照片，然後告訴我你看到了什麼"

    try:
        response_text = await call_claude(prompt, chat_id)
    except Exception as e:
        logging.error("照片處理失敗 (chat %s): %s", chat_id, e)
        await update.message.reply_text("抱歉，照片看不了，等一下再試試？")
        return

    await _send_response(update, response_text)


# ─── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )
    logging.info("Chimmmmy bot 啟動中...")

    async def _post_init(application):
        restored = 0
        for chat_id, s in list(schedules.items()):
            try:
                hh, mm = map(int, s["time"].split(":"))
                _register_schedule(application, chat_id, hh, mm, s.get("tz", DEFAULT_TZ))
                restored += 1
            except Exception as e:
                logging.error("還原排程失敗 chat=%s: %s", chat_id, e)
        if restored:
            logging.info("已還原 %d 個每日排程", restored)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logging.info("上線！按 Ctrl+C 停止。")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
