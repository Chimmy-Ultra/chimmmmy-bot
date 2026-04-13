FROM node:20-slim

# 安裝 Python
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# 安裝 Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# 建立非 root 用戶（Claude CLI 拒絕在 root 下使用 bypassPermissions）
RUN useradd -m -u 1000 botuser

WORKDIR /app

COPY requirements.txt .
RUN pip3 install -r requirements.txt --break-system-packages

COPY . .
RUN chown -R botuser:botuser /app

USER botuser

CMD ["python3", "bot.py"]
