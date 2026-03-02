FROM ghcr.io/openclaw/openclaw:latest

# Прокидываем порт
EXPOSE 8080

# Запускаем OpenClaw
CMD ["/app/openclaw"]
