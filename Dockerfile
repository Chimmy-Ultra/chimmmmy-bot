FROM node:20-slim

# 安裝 Python
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# 安裝 Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# 用 node image 內建的 node 用戶（uid 1000）
# Claude CLI 拒絕在 root 下使用 bypassPermissions
WORKDIR /app

COPY requirements.txt .
RUN pip3 install -r requirements.txt --break-system-packages

COPY . .
RUN mkdir -p /home/node/.claude && chown -R node:node /app /home/node/.claude

USER node

CMD ["python3", "bot.py"]
