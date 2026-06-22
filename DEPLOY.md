# 部署指南（使用 Claude Max plan quota）

這個 bot 透過 Claude CLI 以 **OAuth token（Max plan 訂閱額度）** 運行，不需要 API key、不會額外計費。

## 你需要準備兩個秘密金鑰

| 變數 | 來源 |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | 跟 Telegram 的 [@BotFather](https://t.me/BotFather) 申請 |
| `CLAUDE_REFRESH_TOKEN` | 在已登入 Claude CLI 的機器上，取 `~/.claude/.credentials.json` 裡 `claudeAiOauth.refreshToken` 的值 |

> ⚠️ 這兩個值等同你的帳號權限，**不要 commit 進 repo、不要貼到聊天或 issue**。一律設到平台的 secrets 欄位。

取得 refresh token（在你登入 Claude Code 的電腦上）：

```bash
# macOS / Linux
cat ~/.claude/.credentials.json
# 找到 "refreshToken": "..." 複製那串值
```

---

## 方案 A：Fly.io（推薦，常駐容器）

1. 安裝並登入 flyctl：
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```
2. 在專案根目錄（含 `fly.toml`）建立 app（首次）：
   ```bash
   fly apps create chimmmmy-bot   # 或改成你自己的唯一名稱，並同步改 fly.toml 的 app =
   ```
3. 建立持久卷（保存記憶 / session / credentials）：
   ```bash
   fly volumes create chimmmmy_data --size 1 --region nrt
   ```
   region 要跟 `fly.toml` 的 `primary_region` 一致。
4. 設定金鑰（不會進版控）：
   ```bash
   fly secrets set TELEGRAM_BOT_TOKEN=xxxxx CLAUDE_REFRESH_TOKEN=yyyyy
   ```
5. 部署：
   ```bash
   fly deploy
   ```
6. 看 log 確認上線：
   ```bash
   fly logs
   ```
   看到 `Chimmmmy bot 啟動中...` 和 `上線！` 就成功了，去 Telegram 跟 bot 說句話試試。

---

## 方案 B：自架 / VPS（docker compose）

1. 複製環境變數樣板並填值：
   ```bash
   cp .env.example .env
   # 編輯 .env，填入 TELEGRAM_BOT_TOKEN 和 CLAUDE_REFRESH_TOKEN
   ```
2. 啟動：
   ```bash
   docker compose up -d --build
   ```
3. 看 log：
   ```bash
   docker compose logs -f
   ```
   記憶等資料存在 `bot-data` volume，重啟不會掉。

---

## 持久化說明

容器檔案系統是暫時的，所以下列資料都寫到持久卷（由 `DATA_DIR` 與 `CLAUDE_CONFIG_DIR` 指定）：

- `memory.json` — bot 記住的事
- `sessions.json` / `personas.json` / `thinking.json` — 每個聊天的狀態
- `.claude/.credentials.json` — OAuth token（含自動刷新後輪替的 refresh token）

本地直接 `python3 bot.py` 跑時不設這兩個變數，行為跟以前一樣（檔案寫在腳本目錄）。

## 常用指令（Telegram 內）

`/start` 重置並打招呼 · `/clear` 重置對話 · `/memory` 看記憶 · `/model sonnet|opus|haiku` 切模型 · `/luna` 切到 Luna 人格 · `/think on|off` 最大化思考
