"""Every string the bot itself says.

This is bot chrome — consent, commands, refusals, the section headers around a
verdict. The *content* of a verdict is localized by the renderer in
`src/saqbol/i18n/*.yaml`; nothing here duplicates it.

Two rules for the text below.

**The consent block is a safety control, not boilerplate.** Someone reading it
may be on the phone to a fraudster right now. So it leads with the three
promises that matter — the bot never asks for a code, a card number or a phone
number; screenshots are not stored; the message stays private unless you
explicitly donate it — and it states them in the plainest words available in
each language, before any description of features. The line "if someone is
asking you for a code, they are a scammer, whoever they claim to be" is the one
sentence that can still help a reader who never sends a message at all.

**Anti-impersonation is part of consent.** A trusted anti-fraud bot is itself a
thing worth impersonating, so every consent block ends by saying what the bot
never does: message first, call, or claim to be a bank.
"""

from __future__ import annotations

from saqbol.core.types import Lang

#: Offered on `/start`. Kept to the four the pipeline and the renderer support.
SUPPORTED_LOCALES: tuple[Lang, ...] = (Lang.RU, Lang.KK, Lang.EN, Lang.ZH)

LANGUAGE_NAMES: dict[Lang, str] = {
    Lang.RU: "Русский",
    Lang.KK: "Қазақша",
    Lang.EN: "English",
    Lang.ZH: "中文",
}

_RU = {
    "consent": """SaqBol — бот, который проверяет сообщения на мошенничество.

Пришлите текст, перешлите подозрительное сообщение или отправьте скриншот. В ответ придёт: похоже ли это на мошенничество, по какой схеме работают и что сделать прямо сейчас.

Прежде чем вы что-то отправите — три вещи:

1. Я никогда не спрошу у вас код из СМС, номер карты, PIN или номер телефона. Никогда, ни в каком сообщении, ни под каким предлогом. Если у вас прямо сейчас кто-то просит код — это мошенники, кем бы они ни представлялись.

2. Скриншоты не сохраняются. Я читаю текст с картинки и сразу удаляю само изображение: оно не попадает ни на диск, ни в базу.

3. Текст проверки хранится {retention_days} дней, чтобы бот работал лучше. Номера карт, коды и телефоны вырезаются автоматически. В открытый набор данных сообщение попадёт только если вы сами нажмёте «Добавить» под ответом.

Я не банк, не полиция и не служба безопасности. Я никогда не пишу и не звоню первым. Если вам написали «из SaqBol» — это не я.

Если деньги уже ушли: позвоните в свой банк и в полицию по номеру 102.""",
    "choose_language": "Выберите язык ответов:",
    "language_set": "Готово, отвечаю на русском. Присылайте сообщение, которое нужно проверить.",
    "help": """Что я умею:

• Пришлите текст сообщения — проверю его.
• Перешлите сообщение — учту ещё и то, откуда оно пришло.
• Пришлите скриншот переписки — прочитаю текст с картинки.

Если переписка длинная, присылайте сообщения подряд: я разберу их как один разговор и скажу, на каком шаге схемы вы находитесь.

Команды:
/start — согласие и выбор языка
/help — эта справка
/privacy — что хранится и сколько
/forget — удалить всё, что я о вас помню

Ограничение: {limit} проверок в сутки.

Я не банк и не полиция. Ответ бота — это подсказка, а не официальное заключение. Если деньги уже ушли, звоните в банк и в полицию, 102.""",
    "privacy": """Коротко о данных.

Что я не храню: скриншоты (удаляются сразу после распознавания текста), ваш номер телефона, ваше имя и ваш Telegram ID в открытом виде — вместо него хранится необратимый хеш.

Что я храню: текст проверки {retention_days} дней, с автоматически вырезанными номерами карт, кодами, телефонами и адресами почты. Дальше остаётся только хеш текста — для того, чтобы не считать одно и то же дважды.

Что попадает в открытый набор данных: только те сообщения, для которых вы сами нажали «Добавить». Никогда — автоматически.

/forget удаляет язык, историю разговора и счётчик проверок для этого чата.

Подробнее — PRIVACY.md в репозитории проекта.""",
    "send_something": "Пришлите текст, перешлите сообщение или отправьте скриншот — проверю.",
    "consent_required": "Прежде чем начать, прочитайте, пожалуйста, вот это и выберите язык:",
    "rate_limited": """На сегодня лимит исчерпан: {limit} проверок в сутки. Счётчик обнулится после полуночи.

Если ситуация срочная, не ждите бота: позвоните в свой банк по номеру на обратной стороне карты и в полицию, 102. И правило, которое работает без меня: код из СМС не сообщают никому, включая тех, кто звонит «из банка».""",
    "text_too_long": """Сообщение слишком длинное: {actual} символов при пределе {limit}.

Пришлите ту часть переписки, которая вас настораживает — обычно этого достаточно.""",
    "image_too_large": """Картинка слишком большая: {actual} МБ при пределе {limit} МБ.

Пришлите скриншот вместо фотографии экрана или уменьшите качество.""",
    "photo_not_supported": """Распознавание скриншотов ещё не включено в этой сборке.

Пока перешлите само сообщение или скопируйте текст — так я тоже увижу отправителя.""",
    "photo_unreadable": """Не смог разобрать этот скриншот.

Пришлите более чёткий снимок или скопируйте текст сообщения — так надёжнее.""",
    "photo_no_text": """На скриншоте не нашёл текста сообщений.

Пришлите снимок самой переписки или скопируйте текст.""",
    "unsupported": """Я разбираю текст, пересланные сообщения и скриншоты.

Голосовые, файлы и видео пока не умею. Если сообщение пришло голосом, напишите своими словами, что вам сказали.""",
    "error": """Что-то сломалось на моей стороне, и я не смог проверить это сообщение. Попробуйте ещё раз.

Не ждите ответа бота, если на вас давят прямо сейчас: положите трубку и перезвоните в банк сами, по номеру с обратной стороны карты.""",
    "forgotten": "Удалил язык, историю разговора и счётчик для этого чата.",
    "stub_notice": "⚠️ Тестовая сборка: ответ ниже — заглушка, а не настоящая проверка.",
    "card_evidence": "Что меня насторожило:",
    "card_stage": "Шаг схемы:",
    "card_stage_next": "Дальше обычно:",
    "card_action": "Что делать:",
    "card_hotlines": "Куда звонить:",
    "btn_vote_yes": "👍 Да, верно",
    "btn_vote_no": "👎 Нет, неверно",
    "btn_voted": "✅ Спасибо, ответ учтён",
    "btn_share": "📤 Переслать близким",
    "btn_dataset": "➕ Добавить в набор данных",
    "btn_dataset_confirm": "Да, добавить",
    "btn_dataset_cancel": "Отмена",
    "vote_thanks": "Спасибо! Ваш ответ поможет боту ошибаться реже.",
    "vote_already": "Ответ уже учтён.",
    "share_hint": "Перешлите это сообщение близким.",
    "share_warning": "⚠️ Проверьте, прежде чем отвечать. Код из СМС, номер карты и PIN не сообщают никому — даже тем, кто звонит «из банка» или «из полиции».",
    "share_verdict": "Проверка SaqBol: {band}.",
    "share_playbook": "Схема: {name}.",
    "share_hotline": "Если деньги уже ушли — звоните в банк и в полицию: {hotlines}.",
    "dataset_confirm": """Добавить это сообщение в открытый набор данных?

Что сохранится: текст сообщения — уже без номеров карт, кодов, телефонов и адресов почты — и вердикт бота. Ваше имя, номер и Telegram ID туда не попадают.

Перед публикацией запись посмотрит человек. Пока вы не нажмёте «Да, добавить», ничего не сохраняется.""",
    "dataset_added": "Спасибо! Сообщение в очереди на проверку. В набор данных оно попадёт только после того, как его посмотрит человек.",
    "dataset_already": "Это сообщение уже в очереди на проверку.",
    "dataset_cancelled": "Отменено. Ничего не сохранено.",
    "check_unknown": "Эту проверку я уже не помню: она была давно или бот перезапускался. Если нужно, пришлите сообщение ещё раз.",
    "feedback_unavailable": "Сейчас это недоступно. Попробуйте позже.",
    "cmd_start": "Согласие и выбор языка",
    "cmd_help": "Что я умею",
    "cmd_privacy": "Что хранится и сколько",
    "cmd_forget": "Удалить мои данные",
}

_KK = {
    "consent": """SaqBol — хабарламаны алаяқтыққа тексеретін бот.

Мәтін жіберіңіз, күдікті хабарламаны қайта жіберіңіз немесе скриншот салыңыз. Жауабында: бұл алаяқтыққа ұқсай ма, қандай схема қолданылып жатыр және дәл қазір не істеу керек.

Бірдеңе жібермес бұрын — үш нәрсе:

1. Мен сізден ешқашан SMS кодын, карта нөмірін, PIN-кодты немесе телефон нөмірін сұрамаймын. Ешқашан, ешқандай хабарламада, ешқандай сылтаумен. Егер дәл қазір біреу сізден код сұрап отырса — ол алаяқ, кім болып таныссын да.

2. Скриншоттар сақталмайды. Мен суреттегі мәтінді оқып, суреттің өзін бірден жоямын: ол дискіге де, дерекқорға да түспейді.

3. Тексерілген мәтін бот жақсырақ жұмыс істеуі үшін {retention_days} күн сақталады. Карта нөмірлері, кодтар мен телефондар автоматты түрде кесіліп тасталады. Ашық деректер жинағына хабарлама тек өзіңіз жауаптың астындағы «Қосу» түймесін бассаңыз ғана түседі.

Мен банк те, полиция да, қауіпсіздік қызметі де емеспін. Мен ешқашан бірінші болып жазбаймын, қоңырау шалмаймын. Егер сізге «SaqBol-дан» деп жазса — бұл мен емеспін.

Ақша кетіп қалған болса: банкіңізге және полицияға 102 нөміріне қоңырау шалыңыз.""",
    "choose_language": "Жауап тілін таңдаңыз:",
    "language_set": "Дайын, қазақша жауап беремін. Тексеру керек хабарламаны жіберіңіз.",
    "help": """Не істей аламын:

• Хабарлама мәтінін жіберіңіз — тексеремін.
• Хабарламаны қайта жіберіңіз — оның қайдан келгенін де ескеремін.
• Жазысудың скриншотын жіберіңіз — суреттегі мәтінді оқимын.

Жазысу ұзақ болса, хабарламаларды қатарынан жіберіңіз: оларды бір әңгіме ретінде қарап, схеманың қай қадамында тұрғаныңызды айтамын.

Командалар:
/start — келісім және тіл таңдау
/help — осы анықтама
/privacy — не сақталады және қанша уақыт
/forget — сіз туралы есімде бар нәрсенің бәрін өшіру

Шектеу: тәулігіне {limit} тексеру.

Мен банк те, полиция да емеспін. Боттың жауабы — кеңес, ресми қорытынды емес. Ақша кетіп қалса, банкке және полицияға, 102-ге қоңырау шалыңыз.""",
    "privacy": """Деректер туралы қысқаша.

Не сақтамаймын: скриншоттарды (мәтін танылған соң бірден жойылады), сіздің телефон нөміріңізді, атыңызды және Telegram ID-іңізді ашық түрде — оның орнына қайтымсыз хеш сақталады.

Не сақтаймын: тексерілген мәтінді {retention_days} күн, карта нөмірлері, кодтар, телефондар мен пошта адрестері автоматты түрде кесілген күйде. Одан кейін тек мәтіннің хеші қалады — бір нәрсені екі рет есептемеу үшін.

Ашық деректер жинағына не түседі: тек өзіңіз «Қосу» түймесін басқан хабарламалар. Ешқашан автоматты түрде емес.

/forget осы чаттың тілін, әңгіме тарихын және тексеру санағышын өшіреді.

Толығырақ — жобаның репозиторийіндегі PRIVACY.md.""",
    "send_something": "Мәтін жіберіңіз, хабарламаны қайта жіберіңіз немесе скриншот салыңыз — тексеремін.",
    "consent_required": "Бастамас бұрын, мынаны оқып шығып, тіл таңдаңыз:",
    "rate_limited": """Бүгінгі лимит бітті: тәулігіне {limit} тексеру. Санағыш түн ортасынан кейін жаңарады.

Жағдай шұғыл болса, ботты күтпеңіз: картаңыздың артқы жағындағы нөмір бойынша банкіңізге және полицияға, 102-ге қоңырау шалыңыз. Менсіз де жұмыс істейтін ереже: SMS кодын ешкімге айтпайды, «банктен» деп қоңырау шалғандарға да.""",
    "text_too_long": """Хабарлама тым ұзын: {actual} таңба, шегі {limit}.

Жазысудың сізді күмәндандырған бөлігін жіберіңіз — әдетте сол жеткілікті.""",
    "image_too_large": """Сурет тым үлкен: {actual} МБ, шегі {limit} МБ.

Экранның фотосының орнына скриншот жіберіңіз немесе сапасын төмендетіңіз.""",
    "photo_not_supported": """Скриншот тану бұл құрастырымда әлі қосылмаған.

Әзірге хабарламаның өзін қайта жіберіңіз немесе мәтінін көшіріп салыңыз — сонда жіберушіні де көремін.""",
    "photo_unreadable": """Бұл скриншотты оқи алмадым.

Анығырақ сурет жіберіңіз немесе хабарламаның мәтінін көшіріп салыңыз — солай сенімдірек.""",
    "photo_no_text": """Скриншоттан хабарлама мәтінін таппадым.

Жазысудың өзін түсіріп жіберіңіз немесе мәтінін көшіріңіз.""",
    "unsupported": """Мен мәтінді, қайта жіберілген хабарламаларды және скриншоттарды қараймын.

Дауыстық хабарлама, файл және бейнені әзірге танымаймын. Егер хабарлама дауыспен келсе, сізге не айтқанын өз сөзіңізбен жазыңыз.""",
    "error": """Менің жағымда бірдеңе сынды, хабарламаны тексере алмадым. Қайталап көріңіз.

Дәл қазір сізге қысым көрсетіп жатса, боттың жауабын күтпеңіз: тұтқаны қойып, картаңыздың артындағы нөмір бойынша банкке өзіңіз қоңырау шалыңыз.""",
    "forgotten": "Осы чаттың тілін, әңгіме тарихын және санағышын өшірдім.",
    "stub_notice": "⚠️ Сынақ құрастырымы: төмендегі жауап — уақытша үлгі, нағыз тексеру емес.",
    "card_evidence": "Мені күмәндандырғаны:",
    "card_stage": "Схеманың қадамы:",
    "card_stage_next": "Әдетте одан кейін:",
    "card_action": "Не істеу керек:",
    "card_hotlines": "Қайда қоңырау шалу керек:",
    "btn_vote_yes": "👍 Иә, дұрыс",
    "btn_vote_no": "👎 Жоқ, қате",
    "btn_voted": "✅ Рақмет, жауап есепке алынды",
    "btn_share": "📤 Жақындарға жіберу",
    "btn_dataset": "➕ Деректер жинағына қосу",
    "btn_dataset_confirm": "Иә, қосу",
    "btn_dataset_cancel": "Болдырмау",
    "vote_thanks": "Рақмет! Жауабыңыз ботқа сирек қателесуге көмектеседі.",
    "vote_already": "Жауап есепке алынып қойған.",
    "share_hint": "Осы хабарламаны жақындарыңызға жіберіңіз.",
    "share_warning": "⚠️ Жауап бермес бұрын тексеріңіз. SMS кодын, карта нөмірін және PIN-кодты ешкімге айтпайды — «банктен» немесе «полициядан» деп қоңырау шалғандарға да.",
    "share_verdict": "SaqBol тексеруі: {band}.",
    "share_playbook": "Схема: {name}.",
    "share_hotline": "Ақша кетіп қалған болса — банкке және полицияға қоңырау шалыңыз: {hotlines}.",
    "dataset_confirm": """Осы хабарламаны ашық деректер жинағына қосу керек пе?

Не сақталады: хабарламаның мәтіні — карта нөмірлері, кодтар, телефондар мен пошта адрестері кесілген күйде — және боттың қорытындысы. Атыңыз, нөміріңіз және Telegram ID-іңіз оған түспейді.

Жарияламас бұрын жазбаны адам қарайды. «Иә, қосу» түймесін баспайынша ештеңе сақталмайды.""",
    "dataset_added": "Рақмет! Хабарлама тексеру кезегінде. Деректер жинағына ол адам қарағаннан кейін ғана түседі.",
    "dataset_already": "Бұл хабарлама тексеру кезегінде тұр.",
    "dataset_cancelled": "Болдырылмады. Ештеңе сақталмады.",
    "check_unknown": "Бұл тексеру есімде жоқ: ол әлдеқашан болған немесе бот қайта іске қосылған. Қажет болса, хабарламаны қайта жіберіңіз.",
    "feedback_unavailable": "Қазір бұл қолжетімсіз. Кейінірек көріңіз.",
    "cmd_start": "Келісім және тіл таңдау",
    "cmd_help": "Не істей аламын",
    "cmd_privacy": "Не сақталады және қанша уақыт",
    "cmd_forget": "Деректерімді өшіру",
}

_EN = {
    "consent": """SaqBol checks messages for scams.

Send me the text, forward the suspicious message, or send a screenshot. You get back: whether this looks like a scam, which script is being run on you, and what to do right now.

Before you send anything — three things:

1. I will never ask you for an SMS code, a card number, a PIN or a phone number. Never, in any message, for any reason. If someone is asking you for a code right now, they are a scammer, whoever they say they are.

2. Screenshots are not stored. I read the text off the image and delete the image itself immediately: it never reaches a disk or a database.

3. The text of a check is kept for {retention_days} days so the bot can get better. Card numbers, codes and phone numbers are stripped automatically. A message enters the public dataset only if you press "Add" under the answer yourself.

I am not a bank, not the police, not a security department. I never message or call you first. If something claims to be "from SaqBol", it is not me.

If the money is already gone: call your bank, and the police on 102.""",
    "choose_language": "Choose a language for replies:",
    "language_set": "Done, I will reply in English. Send me the message you want checked.",
    "help": """What I can do:

• Send the text of a message — I will check it.
• Forward a message — I will also use where it came from.
• Send a screenshot of a chat — I will read the text off the image.

If the conversation is long, send the messages one after another: I read them as a single conversation and tell you which step of the script you are at.

Commands:
/start — consent and language
/help — this help
/privacy — what is kept, and for how long
/forget — delete everything I remember about you

Limit: {limit} checks per day.

I am not a bank or the police. My answer is a hint, not an official finding. If the money is already gone, call your bank and the police on 102.""",
    "privacy": """Data, briefly.

What I do not keep: screenshots (deleted as soon as the text is read), your phone number, your name, or your Telegram ID in the clear — an irreversible hash is stored instead.

What I keep: the text of a check for {retention_days} days, with card numbers, codes, phone numbers and email addresses stripped automatically. After that only a hash of the text remains, so the same message is not analysed twice.

What enters the public dataset: only messages you pressed "Add" on yourself. Never automatically.

/forget deletes the language, the conversation history and the check counter for this chat.

More detail: PRIVACY.md in the project repository.""",
    "send_something": "Send text, forward a message, or send a screenshot — I will check it.",
    "consent_required": "Before we start, please read this and choose a language:",
    "rate_limited": """Today's limit is used up: {limit} checks per day. The counter resets after midnight.

If this is urgent, do not wait for a bot: call your bank on the number printed on the back of your card, and the police on 102. And the rule that works without me: you never read an SMS code out to anyone, including people calling "from your bank".""",
    "text_too_long": """That message is too long: {actual} characters against a limit of {limit}.

Send the part of the conversation that worries you — that is usually enough.""",
    "image_too_large": """That image is too large: {actual} MB against a limit of {limit} MB.

Send a screenshot rather than a photo of a screen, or reduce the quality.""",
    "photo_not_supported": """Screenshot reading is not enabled in this build yet.

For now, forward the message itself or paste the text — that way I see the sender too.""",
    "photo_unreadable": """I could not read that screenshot.

Send a sharper one, or paste the message text — that is more reliable.""",
    "photo_no_text": """I found no message text in that screenshot.

Send a shot of the conversation itself, or paste the text.""",
    "unsupported": """I read text, forwarded messages and screenshots.

Voice messages, files and video are not supported yet. If it came as a voice message, write down in your own words what you were told.""",
    "error": """Something broke on my side and I could not check that message. Please try again.

Do not wait for a bot if someone is pressuring you right now: hang up and call your bank yourself, on the number on the back of your card.""",
    "forgotten": "Deleted the language, conversation history and counter for this chat.",
    "stub_notice": "⚠️ Test build: the answer below is a fixture, not a real check.",
    "card_evidence": "What looks wrong:",
    "card_stage": "Step of the script:",
    "card_stage_next": "Usually next:",
    "card_action": "What to do:",
    "card_hotlines": "Who to call:",
    "btn_vote_yes": "👍 Yes, right",
    "btn_vote_no": "👎 No, wrong",
    "btn_voted": "✅ Thanks, vote recorded",
    "btn_share": "📤 Forward to family",
    "btn_dataset": "➕ Add to the dataset",
    "btn_dataset_confirm": "Yes, add it",
    "btn_dataset_cancel": "Cancel",
    "vote_thanks": "Thank you! Your answer helps the bot make fewer mistakes.",
    "vote_already": "Already recorded.",
    "share_hint": "Forward this message to your family.",
    "share_warning": '⚠️ Check before you reply. An SMS code, a card number or a PIN is never given to anyone — not even someone calling "from the bank" or "from the police".',
    "share_verdict": "SaqBol check: {band}.",
    "share_playbook": "Script: {name}.",
    "share_hotline": "If the money is already gone — call your bank and the police: {hotlines}.",
    "dataset_confirm": """Add this message to the public dataset?

What is kept: the text of the message — with card numbers, codes, phone numbers and email addresses already removed — and the bot's verdict. Your name, number and Telegram ID do not go in.

A person reviews the record before anything is published. Nothing is saved until you press "Yes, add it".""",
    "dataset_added": "Thank you! The message is queued for review. It enters the dataset only after a person has looked at it.",
    "dataset_already": "This message is already queued for review.",
    "dataset_cancelled": "Cancelled. Nothing was saved.",
    "check_unknown": "I no longer have that check: it was a while ago, or the bot has restarted. Send the message again if you need to.",
    "feedback_unavailable": "That is not available right now. Please try again later.",
    "cmd_start": "Consent and language",
    "cmd_help": "What I can do",
    "cmd_privacy": "What is kept, and for how long",
    "cmd_forget": "Delete my data",
}

_ZH = {
    "consent": """SaqBol 帮你判断一条消息是不是诈骗。

把文字发给我、转发可疑消息，或者发一张截图。我会回答：这是否像诈骗、对方在用哪一套话术，以及你现在该做什么。

在你发送之前，有三件事：

1. 我永远不会向你索要短信验证码、银行卡号、支付密码或手机号。任何消息、任何理由都不会。如果现在有人向你要验证码，对方就是骗子，不管他自称是谁。

2. 截图不会被保存。我读取图片上的文字后立刻删除图片本身：它不会写入磁盘，也不会进入数据库。

3. 检查过的文字会保留 {retention_days} 天，用于改进这个工具。卡号、验证码和电话号码会被自动去除。只有你自己点击回复下方的"添加"，消息才会进入公开数据集。

我不是银行，不是警察，也不是安全部门。我从不主动给你发消息或打电话。如果有人自称"来自 SaqBol"，那不是我。

如果钱已经转出去了：立刻联系你的银行，并拨打反诈专线 96110。""",
    "choose_language": "选择回复语言：",
    "language_set": "好了，我会用中文回复。把需要检查的消息发给我。",
    "help": """我能做什么：

• 发送消息文字 — 我来检查。
• 转发消息 — 我还会参考它的来源。
• 发送聊天截图 — 我会读取图片上的文字。

如果对话很长，可以连续发送多条：我会当作一段完整对话来读，并告诉你现在处在骗局的哪一步。

命令：
/start — 知情同意与语言选择
/help — 本帮助
/privacy — 保存什么、保存多久
/forget — 删除我记住的关于你的一切

限制：每天 {limit} 次检查。

我不是银行也不是警察。我的回答是提示，不是正式结论。如果钱已经转出，请联系银行并拨打 96110。""",
    "privacy": """关于数据，简短说明。

不保存：截图（读取文字后立即删除）、你的手机号、你的姓名，以及明文的 Telegram ID — 只保存不可逆的哈希值。

保存：检查过的文字保留 {retention_days} 天，其中卡号、验证码、电话和邮箱地址已被自动去除。之后只留下文字的哈希值，用于避免重复分析同一条消息。

进入公开数据集的内容：只有你亲自点击"添加"的消息，绝不会自动收录。

/forget 会删除本对话的语言设置、对话记录和检查计数。

详见项目仓库中的 PRIVACY.md。""",
    "send_something": "发送文字、转发消息或发送截图 — 我来检查。",
    "consent_required": "开始之前，请先阅读以下内容并选择语言：",
    "rate_limited": """今天的额度已用完：每天 {limit} 次。计数在午夜后重置。

如果情况紧急，不要等机器人：按银行卡背面的号码联系你的银行，并拨打 96110。还有一条不需要我也成立的规则：短信验证码绝不告诉任何人，包括自称"银行客服"的来电。""",
    "text_too_long": """消息太长了：{actual} 个字符，上限是 {limit}。

把让你觉得不对劲的那部分发过来就够了。""",
    "image_too_large": """图片太大了：{actual} MB，上限是 {limit} MB。

请发送截图而不是屏幕的翻拍照片，或者降低画质。""",
    "photo_not_supported": """这个版本还没有启用截图识别。

暂时请直接转发原消息或粘贴文字 — 这样我也能看到发送方。""",
    "photo_unreadable": """这张截图我没能识别。

请发一张更清晰的，或者直接粘贴消息文字 — 这样更可靠。""",
    "photo_no_text": """截图里没有找到消息文字。

请发送对话本身的截图，或者粘贴文字。""",
    "unsupported": """我可以看文字、转发的消息和截图。

暂时不支持语音、文件和视频。如果是语音消息，请用自己的话写下对方说了什么。""",
    "error": """我这边出了问题，没能检查这条消息。请再试一次。

如果现在有人正在向你施压，不要等机器人：挂断电话，按银行卡背面的号码自己打给银行。""",
    "forgotten": "已删除本对话的语言设置、对话记录和计数。",
    "stub_notice": "⚠️ 测试版本：下面的回答是占位示例，不是真实检查结果。",
    "card_evidence": "可疑之处：",
    "card_stage": "骗局阶段：",
    "card_stage_next": "通常接下来：",
    "card_action": "该怎么做：",
    "card_hotlines": "拨打：",
    "btn_vote_yes": "👍 对，判断正确",
    "btn_vote_no": "👎 不对，判断错误",
    "btn_voted": "✅ 谢谢，已记录",
    "btn_share": "📤 转发给家人",
    "btn_dataset": "➕ 加入数据集",
    "btn_dataset_confirm": "是，加入",
    "btn_dataset_cancel": "取消",
    "vote_thanks": "谢谢！你的反馈会让判断更准确。",
    "vote_already": "已经记录过了。",
    "share_hint": "把这条消息转发给家人。",
    "share_warning": '⚠️ 回复之前先核实。短信验证码、银行卡号和密码不能告诉任何人——包括自称"银行"或"警方"的来电。',
    "share_verdict": "SaqBol 检查结果：{band}。",
    "share_playbook": "话术：{name}。",
    "share_hotline": "如果钱已经转出——请联系银行并拨打：{hotlines}。",
    "dataset_confirm": """把这条消息加入公开数据集吗？

会保存的内容：消息文字（卡号、验证码、电话和邮箱已被去除）以及机器人的判断。你的姓名、电话和 Telegram ID 不会进入数据集。

发布之前会由人工审核。在你点击"是，加入"之前，什么都不会保存。""",
    "dataset_added": "谢谢！消息已进入审核队列。只有经过人工审核后才会进入数据集。",
    "dataset_already": "这条消息已经在审核队列中了。",
    "dataset_cancelled": "已取消。没有保存任何内容。",
    "check_unknown": "我已经没有这次检查的记录了：可能时间太久，或者机器人重启过。需要的话请重新发送消息。",
    "feedback_unavailable": "暂时无法使用，请稍后再试。",
    "cmd_start": "知情同意与语言",
    "cmd_help": "我能做什么",
    "cmd_privacy": "保存什么、保存多久",
    "cmd_forget": "删除我的数据",
}

TEXTS: dict[Lang, dict[str, str]] = {
    Lang.RU: _RU,
    Lang.KK: _KK,
    Lang.EN: _EN,
    Lang.ZH: _ZH,
}

#: Fallback for any locale without its own table, including `mixed`/`unknown`
#: coming back from language identification.
FALLBACK_LOCALE = Lang.RU


def resolve_locale(value: str | Lang | None) -> Lang:
    """Coerce a stored value or a Telegram `language_code` to a supported locale."""
    if value is None:
        return FALLBACK_LOCALE
    if isinstance(value, Lang):
        return value if value in TEXTS else FALLBACK_LOCALE
    code = value.strip().lower().replace("_", "-").split("-")[0]
    try:
        lang = Lang(code)
    except ValueError:
        return FALLBACK_LOCALE
    return lang if lang in TEXTS else FALLBACK_LOCALE


def t(locale: Lang | str | None, key: str, **kwargs: object) -> str:
    """Look up a string, falling back to Russian for a missing translation."""
    lang = resolve_locale(locale)
    table = TEXTS[lang]
    template = table.get(key) or TEXTS[FALLBACK_LOCALE][key]
    return template.format(**kwargs) if kwargs else template


def consent_block(retention_days: int) -> str:
    """The `/start` text, Russian and Kazakh together.

    Both are shown before any language has been chosen, rather than guessing
    from the Telegram client language. Most Kazakhstani phones report `ru`
    regardless of what their owner reads most comfortably, and consent that the
    reader cannot read is not consent.
    """
    return "\n\n———\n\n".join(
        t(lang, "consent", retention_days=retention_days) for lang in (Lang.RU, Lang.KK)
    )
