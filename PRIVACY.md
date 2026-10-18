# Политика конфиденциальности · Privacy Policy

**SaqBol (Сақ бол)** — проверка сообщений на мошенничество.
Эту страницу цитирует команда `/privacy` в боте.

Русская версия — основная, English version follows below.

---

# Русский

## Коротко

Если вы собираетесь переслать сюда сообщение мошенника, вам нужно знать пять вещей.

1. Бот **никогда** не спрашивает код из SMS, номер карты, ИИН или номер телефона. Если что-то от имени SaqBol просит их — это не мы.
2. Картинки **удаляются сразу** после распознавания текста. Файл не попадает ни на диск, ни в базу.
3. Ваш Telegram ID и IP-адрес **не сохраняются**. В базу пишется только их HMAC-хеш.
4. Текст проверки хранится **30 дней**, после чего удаляется автоматически.
5. В открытый датасет KazScam ничего не попадает без вашего **отдельного согласия на каждую отправку**.

## 1. Что сохраняется

Одна проверка — одна строка в таблице `checks`:

| Поле | Что это | Срок хранения |
|---|---|---|
| `created_at` | время проверки | бессрочно |
| `surface` | откуда пришло: `telegram`, `web`, `api` | бессрочно |
| `input_type` | `text`, `image` или `forward` | бессрочно |
| `lang` | автоматически определённый язык | бессрочно |
| `text_scrubbed` | текст сообщения **после маскирования** | **30 дней** |
| `text_sha256` | SHA-256 хеш сообщения | бессрочно |
| `verdict` | вердикт; цитаты из сообщения и детали индикаторов удаляются через 30 дней, остальные поля сохраняются | 30 дней для цитат; остальные поля бессрочно |
| `band`, `risk`, `playbook_id` | полоса риска, оценка, сценарий | бессрочно |
| `model`, `latency_ms`, `cost_usd` | какая модель отвечала, сколько заняла и стоила | бессрочно |
| `consent_dataset` | отдали ли вы эту проверку в датасет | бессрочно |
| `actor_hash` | HMAC от Telegram ID или IP | бессрочно |

Бот также хранит в локальном файле язык, согласие, дневной счётчик и короткую цепочку сообщений. Текст в цепочке маскируется перед записью. После 15 минут без новых сообщений он удаляется при следующей ежечасной проверке или запуске бота.

Маскирование — не постобработка. Персональные данные заменяются типизированными метками в момент разбора, **до** записи в базу ([`src/saqbol/core/privacy.py`](src/saqbol/core/privacy.py)):

| В сообщении | В базе |
|---|---|
| номер карты (прошедший проверку Луна) | `<CARD:16>` — только количество цифр |
| ИИН | `<IIN>` |
| номер телефона | `<PHONE>` |
| email | `<EMAIL>` |
| `@username` | `<HANDLE>` |

Метки типизированные, а не пустые: так текст остаётся пригодным для анализа — видно, что у человека просили *именно номер карты*, но самого номера нигде нет.

Суммы и названия банков **не маскируются** — сознательно. Это смысловое содержание сообщения; без «переведите 250 000 ₸» проверка теряет тот самый сигнал, ради которого она делается.

Про `text_sha256` честно: восстановить текст из хеша нельзя, но если у вас уже есть точная копия текста, по хешу можно подтвердить, что его присылали. Хеш нужен для кеша и дедупликации и остаётся после удаления самого текста.

Файлы кеша ответов модели могут содержать цитаты из сообщения; они удаляются после 30-дневного порога. Очистка выполняется раз в сутки, поэтому удаление может произойти в течение следующих 24 часов. Рабочие логи содержат идентификаторы проверок и метаданные результата, но не отправленный текст. Резервные копии должны удаляться не позднее 30 дней; после восстановления базы очистка запускается до приёма запросов.

## 2. Что не сохраняется никогда

- Ваш номер телефона, номер карты, ИИН и email — маскируются до записи.
- Сырой Telegram user id и сырой IP-адрес.
- Файлы изображений.
- Ваше имя, `@username`, фото профиля, список контактов.
- Любые сообщения, кроме того одного, которое вы прислали на проверку.

## 3. Изображения

Скриншот принимается, из него извлекается текст, после чего файл отбрасывается. Он не пишется ни на диск, ни в базу, ни в логи. Сохраняется только распознанный и уже замаскированный текст — на тех же условиях, что и обычное текстовое сообщение, то есть 30 дней.

Максимальный размер файла — **5 МБ** (5 242 880 байт).

## 4. Идентификаторы

Чтобы держать лимит в 10 проверок в сутки, системе нужно отличать одного пользователя от другого. Для этого достаточно хеша, поэтому Telegram ID и IP-адрес перед записью прогоняются через HMAC с серверным ключом (`ACTOR_HASH_SECRET`), и в базу попадает только результат. Сырое значение не пишется никуда.

Честная оговорка: пространство Telegram ID невелико, и тот, у кого одновременно есть и база, и секретный ключ, может сопоставить хеш с конкретным идентификатором. Защита здесь в том, что ключ хранится отдельно от базы и не попадает в репозиторий. Если ключ скомпрометирован, его ротация обесценивает все ранее записанные хеши.

## 5. Ограничения

| Параметр | Значение |
|---|---|
| Проверок в сутки на пользователя | 10 |
| Максимальная длина текста | 8 000 символов |
| Максимальный размер изображения | 5 МБ |

## 6. Куда уходит текст

Это важно понимать до того, как вы что-то пришлёте.

Детерминированная часть анализа — правила, индикаторы, разбор ссылок — работает **на сервере и без сети**. Дальше замаскированный текст отправляется внешнему провайдеру языковой модели: на основном пути это DeepSeek или Alibaba Cloud International (Qwen). Уходит уже очищенный текст, без карт, ИИН, телефонов и email, но само содержание сообщения покидает наш сервер и обрабатывается по правилам провайдера.

Отдельно: если в сообщении есть сокращённая ссылка или домен, похожий на банковский, анализатор может запросить её, чтобы узнать, куда она ведёт. Запрашивается только сама ссылка, методом `HEAD`, и ничего из вашего сообщения при этом не передаётся. Подробнее — в [SECURITY.md](SECURITY.md).

## 7. Датасет KazScam

KazScam — открытый корпус сообщений на казахском и русском. Он собирается только из того, на что дано явное разрешение.

- Согласие даётся **на каждую отправку отдельно**. Общее «да» при первом запуске бота такого разрешения не даёт.
- Согласованные сообщения попадают в очередь `dataset_candidates` со статусом `pending` — **никогда напрямую в датасет**.
- Заявка `pending`, не рассмотренная за 30 дней после проверки, удаляется. Отклонённая заявка удаляется через 30 дней после решения. Одобренный материал сохраняется для корпуса.
- Каждую строку перед публикацией читает человек и повторно проверяет очистку.
- Строка, не прошедшая проверку, отклоняется и не публикуется.
- Отказ ни на что не влияет: проверка работает точно так же.

## 8. Обратная связь

Текст необязательного комментария удаляется через 30 дней; голос сохраняется.

Голос «верно / неверно» под вердиктом сохраняется вместе с необязательным комментарием и ссылкой на проверку. Он идёт в очередь ручного разбора и никогда не попадает в датасет напрямую. Не пишите в комментарии персональные данные — это поле не маскируется.

## 9. Как запросить удаление

Вы можете потребовать удаления в любой момент, причину объяснять не нужно.

1. Откройте issue в репозитории проекта — **https://github.com/InfectedDuck/Scam-Detector** — или напишите сопровождающему проекта напрямую.
2. Укажите свой **Telegram user id** (его показывают боты вроде `@userinfobot`) либо, если он у вас есть, идентификатор проверки. Не присылайте повторно номер карты, код или скриншот.
3. Оператор заново вычисляет ваш `actor_hash` из этого id и удаляет все связанные строки: проверки, голоса и заявки в датасет со статусом `pending`.

Сроки и границы:

- Ответ — в течение 5 рабочих дней, удаление — в течение 30 дней с момента обращения.
- Текст старше 30 дней уже удалён автоматически, отдельно просить об этом не нужно.
- Строку, **уже опубликованную** в составе датасета KazScam, невозможно отозвать из скачанных копий. Из следующей версии она будет убрана, но выпущенный релиз неизменяем. Именно поэтому согласие спрашивается отдельно каждый раз.

## 10. Изменения

Эта страница живёт в репозитории, и история её изменений — это история версий файла в git. О существенных изменениях бот сообщит до того, как они вступят в силу.

Последнее обновление: 16 сентября 2026 года.

---

# English

## In short

If you are about to forward a scammer's message here, five things are worth knowing.

1. The bot **never** asks for an SMS code, a card number, an IIN, or a phone number. Anything claiming to be SaqBol and asking for those is not us.
2. Images are **discarded immediately** after text extraction. The file never reaches disk or database.
3. Your Telegram ID and IP address are **not stored**. Only an HMAC hash of them is.
4. The text of a check is kept for **30 days**, then deleted automatically.
5. Nothing enters the open KazScam dataset without your **explicit, per-submission** consent.

## 1. What is stored

One check is one row in the `checks` table:

| Field | What it is | Retention |
|---|---|---|
| `created_at` | when the check ran | indefinite |
| `surface` | where it came from: `telegram`, `web`, `api` | indefinite |
| `input_type` | `text`, `image`, or `forward` | indefinite |
| `lang` | automatically detected language | indefinite |
| `text_scrubbed` | the message text **after masking** | **30 days** |
| `text_sha256` | SHA-256 hash of the message | indefinite |
| `verdict` | the verdict; message quotes and indicator details are removed after 30 days, while summary fields remain | 30 days for quotes; summary fields indefinite |
| `band`, `risk`, `playbook_id` | risk band, score, matched script | indefinite |
| `model`, `latency_ms`, `cost_usd` | which model answered, how long it took, what it cost | indefinite |
| `consent_dataset` | whether you donated this check to the dataset | indefinite |
| `actor_hash` | HMAC of your Telegram ID or IP | indefinite |

The bot also keeps language, consent, a daily count, and a short message thread in a local state file. Thread text is masked before writing. After 15 minutes of inactivity it is removed by the next hourly sweep or bot startup.

Masking is not a cleanup pass. Personal data is replaced with typed placeholders at parse time, **before** anything is written ([`src/saqbol/core/privacy.py`](src/saqbol/core/privacy.py)):

| In the message | In the database |
|---|---|
| card number (Luhn-valid) | `<CARD:16>` — the digit count only |
| IIN | `<IIN>` |
| phone number | `<PHONE>` |
| email | `<EMAIL>` |
| `@username` | `<HANDLE>` |

Placeholders are typed rather than blanked so the text stays analysable: it remains visible that someone was asked for *a card number*, while the number itself exists nowhere.

Amounts and institution names are deliberately **not** masked. They are the semantic content of the message; without "transfer 250,000 ₸" the check loses the very signal it exists to find.

About `text_sha256`, plainly: the text cannot be reconstructed from the hash, but if you already hold an exact copy of the text, the hash can confirm it was submitted. It is kept for caching and deduplication, and it survives the deletion of the text itself.

Model-response cache files can contain quoted message text and are deleted after the 30-day cutoff. The purge runs daily, so deletion can take up to another 24 hours. Operational logs contain check IDs and result metadata, not submitted text; access logs must not include request bodies. Backups must expire within 30 days and a restored database must run retention before serving traffic.

## 2. What is never stored

- Your phone number, card number, IIN, or email — masked before the write.
- Your raw Telegram user id or raw IP address.
- Image files.
- Your name, `@username`, profile photo, or contacts.
- Any message other than the single one you submitted.

## 3. Images

A screenshot is accepted, text is extracted from it, and the file is then discarded. It is not written to disk, to the database, or to logs. Only the extracted, already-masked text is retained, under the same terms as a plain text message — that is, 30 days.

Maximum file size: **5 MB** (5,242,880 bytes).

## 4. Identifiers

To enforce a limit of 10 checks per day, the system needs to tell one user from another. A hash is enough for that, so the Telegram ID and the IP address are put through HMAC with a server-side key (`ACTOR_HASH_SECRET`) before the write, and only the result reaches the database. The raw value is stored nowhere.

Stated honestly: the space of Telegram IDs is small, and anyone holding both the database and the secret key could match a hash back to a specific id. The protection here is that the key is kept apart from the database and never enters the repository. If the key is compromised, rotating it renders every previously written hash worthless.

## 5. Limits

| Setting | Value |
|---|---|
| Checks per user per day | 10 |
| Maximum text length | 8,000 characters |
| Maximum image size | 5 MB |

## 6. Where the text goes

Worth understanding before you send anything.

The deterministic half of the analysis — rules, indicators, link parsing — runs **on the server with no network access**. After that, the masked text is sent to an external language model provider: on the hot path, DeepSeek or Alibaba Cloud International (Qwen). What leaves is the scrubbed text, without cards, IINs, phone numbers, or emails — but the content of the message does leave our server and is then handled under that provider's terms.

Separately: if the message contains a shortened link or a domain that resembles a bank's, the analyzer may fetch that link to learn where it leads. Only the link itself is fetched, with a `HEAD` request, and nothing from your message is transmitted. See [SECURITY.md](SECURITY.md).

## 7. The KazScam dataset

KazScam is an open corpus of Kazakh and Russian messages. It is built only from material that was explicitly released for it.

- Consent is given **per submission**. A blanket "yes" when you first start the bot does not grant it.
- Consented messages enter the `dataset_candidates` queue with status `pending` — **never straight into the dataset**.
- A pending donation still awaiting review 30 days after its check is deleted. A rejected donation is deleted 30 days after the decision. Approved material remains in the corpus.
- A human reads every row before publication and re-checks the scrubbing.
- A row that fails that check is rejected and never published.
- Declining changes nothing: the check works exactly the same.

## 8. Feedback

A "correct / incorrect" vote under a verdict is stored with an optional comment and a reference to the check. It goes to a manual review queue and never enters the dataset directly. Do not put personal data in the comment — that field is not masked.

The optional comment text is removed after 30 days; the vote remains.

## 9. How to request deletion

You can request deletion at any time, with no reason given.

1. Open an issue on the project repository — **https://github.com/InfectedDuck/Scam-Detector** — or contact the maintainer directly.
2. Give your **Telegram user id** (bots such as `@userinfobot` will show it) or, if you have it, the check id. Do not re-send a card number, a code, or the screenshot.
3. The operator re-derives your `actor_hash` from that id and deletes every associated row: checks, votes, and any `pending` dataset submissions.

Timing and limits:

- Acknowledgement within 5 working days; deletion within 30 days of the request.
- Text older than 30 days is already gone automatically — you do not need to ask for it.
- A row **already published** as part of a KazScam release cannot be recalled from copies people have downloaded. It will be removed from the next version, but a released version is immutable. This is exactly why consent is asked separately every time.

## 10. Changes

This page lives in the repository, and its change history is the file's git history. Material changes will be announced in the bot before they take effect.

Last updated: 16 September 2026.
