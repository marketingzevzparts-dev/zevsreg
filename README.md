# Zeus Parts — Telegram-бот для приёма заявок

Бот принимает контакт клиента, пишет его в Google Таблицу
и присылает клиенту 4 кнопки для связи с менеджерами напрямую — Telegram и Viber
для каждого из двух менеджеров (Володимир и Олександр).

## 1. Установка

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Создание бота в Telegram

1. Напишите [@BotFather](https://t.me/BotFather) → `/newbot`
2. Задайте имя и username (например, `zeus_parts_bot`)
3. Скопируйте токен — вставьте в `.env` как `BOT_TOKEN`

## 3. Настройка Google Sheets (доступ через Service Account)

1. Зайдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект → включите **Google Sheets API** и **Google Drive API**
3. Создайте Service Account: *IAM & Admin → Service Accounts → Create Service Account*
4. В созданном аккаунте: *Keys → Add Key → Create new key → JSON* — скачается файл,
   переименуйте его в `credentials.json` и положите в папку проекта
5. Откройте JSON-файл, скопируйте поле `client_email`
   (выглядит как `xxxxx@xxxxx.iam.gserviceaccount.com`)
6. Создайте Google Таблицу, нажмите «Настройки доступа» → «Добавить пользователя» →
   вставьте этот email, дайте права **Редактор**
7. Скопируйте ID таблицы из URL:
   `https://docs.google.com/spreadsheets/d/ЭТОТ_ID/edit` → вставьте в `.env` как `GOOGLE_SHEET_ID`

## 4. Настройка .env

```bash
cp .env.example .env
```

Заполните `BOT_TOKEN` и `GOOGLE_SHEET_ID`. Ссылки на менеджеров
(`MANAGER_1_TELEGRAM_URL`, `MANAGER_1_VIBER_URL`, `MANAGER_2_TELEGRAM_URL`,
`MANAGER_2_VIBER_URL`) уже заполнены реальными данными Володимира и Олександра —
менять не обязательно, если контакты не изменятся.

### Как устроены ссылки на Telegram и Viber

- **Telegram** — просто ссылка на юзернейм менеджера: `https://t.me/username`.
  Открывается напрямую в приложении Telegram — тут всё просто.

- **Viber** — используется схема `viber://chat?number=НОМЕР`, где номер —
  международный формат **с** `+`, но символ `+` в ссылке нужно закодировать как `%2B`.
  Например, для `+380671234567` пишем: `viber://chat?number=%2B380671234567`.
  При нажатии такая ссылка открывает приложение Viber (если оно установлено)
  сразу с чатом на этот номер. Если Viber не установлен — ссылка не сработает,
  это ограничение самого Viber (у него нет универсальной веб-ссылки как у WhatsApp).

## 5. Запуск

```bash
python bot.py
```

## Как это работает

1. `/start` → приветствие "Zeus Parts" + сразу кнопка «Отправить мой контакт»
2. Клиент нажимает кнопку — Telegram сам отправляет его контакт (имя и телефон)
3. Данные (дата, имя, телефон, username, Telegram ID) добавляются новой строкой в Google Таблицу
4. Клиенту приходит подтверждение + 4 кнопки (Telegram/Viber × 2 менеджера), если не хочет ждать

## Ссылки для 10 групп (чтобы знать, откуда пришла заявка)

Бот поддерживает Telegram deep-linking через параметр `?start=`. Для каждой группы
сделайте свою ссылку с уникальным коротким кодом (латиница/цифры/подчёркивание, без пробелов):

```
https://t.me/zeus_partsreg_bot?start=group1
https://t.me/zeus_partsreg_bot?start=group2
https://t.me/zeus_partsreg_bot?start=group3
...
https://t.me/zeus_partsreg_bot?start=group10
```

Лучше сразу давать осмысленные коды вместо `group1`, `group2` — например:
`odesa_chat`, `avto_kiev`, `chery_club`, `instagram_bio` и т.д. — так в таблице сразу видно, что за источник.

Когда клиент переходит по такой ссылке и жмёт «Старт», бот запоминает этот код и записывает
его в колонку **«Источник (группа)»** вместе с остальными данными заявки. Если человек просто
написал боту напрямую (без ссылки) — в этой колонке будет `direct`.

## Деплой на Railway

Бот работает через polling (без вебхука и домена), поэтому на Railway достаточно
просто держать процесс запущенным как **Worker**.

1. **Залейте проект в GitHub** (обычный `git init` → `git add .` → `git commit` → `git push`).
   `.env` и `credentials.json` в репозиторий не попадут — они в `.gitignore`.

2. **Создайте проект на [railway.app](https://railway.app)**:
   *New Project → Deploy from GitHub repo* → выберите этот репозиторий.

3. **Задайте переменные окружения** — *Variables* в настройках сервиса, добавьте те же
   ключи, что и в `.env.example`:
   - `BOT_TOKEN`
   - `COMPANY_NAME`
   - `GOOGLE_SHEET_ID`, `GOOGLE_SHEET_TAB`
   - `MANAGER_1_TELEGRAM_URL`, `MANAGER_1_VIBER_URL`, `MANAGER_2_TELEGRAM_URL`, `MANAGER_2_VIBER_URL`

4. **Ключ Google передайте через переменную, а не файл.** Откройте скачанный
   `credentials.json`, скопируйте всё содержимое (это JSON в одну структуру) и вставьте
   как значение переменной `GOOGLE_CREDENTIALS_JSON` — целиком, одной строкой.
   Код уже умеет читать credentials из этой переменной (приоритет выше, чем у файла).

5. **Start command**: Railway сам подхватит `Procfile` (`worker: python bot.py`).
   Если попросит выбрать тип процесса — выбирайте **Worker**, не Web (боту не нужен
   открытый порт/HTTP).

6. Нажмите **Deploy** — в логах должно появиться, что бот запущен (без ошибок токена/таблицы).
   Дальше бот работает 24/7, Railway сам перезапускает процесс при падении.

> Важно: если раньше запускали бота локально — остановите его там, иначе Telegram
> будет ругаться на два одновременных polling-подключения (ошибка `Conflict`).

## Деплой на обычный сервер (альтернатива Railway)

Если вместо Railway хотите свой VPS — любой дешёвый Ubuntu-сервер + `systemd` или `pm2`/`screen`.
Просто держите процесс `python bot.py` постоянно запущенным.
