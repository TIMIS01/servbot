FROM python:3.11-slim

WORKDIR /app

# Устанавливаем build-essential (на случай если понадобится)
RUN apt-get update && apt-get install -y build-essential

# Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]
