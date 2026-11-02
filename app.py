import os
import threading
from flask import Flask

# Импортируем бота из main.py
# В main.py блок if __name__ == "__main__": ... нужно закомментировать/удалить,
# чтобы polling не запускался дважды.
import main

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running"

@app.route("/health")
def health():
    return "OK", 200

def run_bot():
    # Снимаем вебхук перед polling — иначе Telegram может отдавать
    # обновления на старый URL, и бот будет молчать.
    try:
        main.bot.remove_webhook()
        print("[INFO] Webhook removed")
    except Exception as e:
        print(f"[WARN] Не удалось снять вебхук: {e}")

    # Запускаем long-polling
    main.bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # Бот — в отдельном потоке
    threading.Thread(target=run_bot, daemon=True).start()
    # Flask — на порту, который даёт Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)