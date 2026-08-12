FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

# 时区 + cron（容器内定时任务）
RUN apt-get update && apt-get install -y --no-install-recommends tzdata cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# 定时任务：工作日 16:35 全链路 / 周日 20:00 周报+推送 / 月末 17:30 月报+推送
COPY docker/crontab /etc/cron.d/xingchen
RUN chmod 0644 /etc/cron.d/xingchen \
    && mkdir -p /var/log && touch /var/log/xingchen.log

CMD ["cron", "-f", "-L", "2"]
