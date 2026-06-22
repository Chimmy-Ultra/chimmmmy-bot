FROM node:20-slim

# 安裝 Python 與 gosu（用來在 entrypoint 內降權到 node）
RUN apt-get update && apt-get install -y python3 python3-pip gosu && rm -rf /var/lib/apt/lists/*

# 安裝 Claude CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY requirements.txt .
RUN pip3 install -r requirements.txt --break-system-packages

COPY . .

# node image 內建 node 用戶（uid 1000）；Claude CLI 拒絕在 root 下使用 bypassPermissions
RUN mkdir -p /home/node/.claude \
    && chown -R node:node /app /home/node/.claude \
    && chmod +x /app/entrypoint.sh

# 以 root 啟動，entrypoint 修正持久卷權限後降權到 node 執行 bot
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "bot.py"]
