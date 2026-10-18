# Contributing

SaqBol needs two kinds of help, and they are equally load-bearing.

One is code. The other is people who actually speak Kazakh and Russian and can tell a real scam message from a synthetic imitation of one — a judgement no amount of engineering substitutes for. If you are in the second group, skip to [Contributing without writing code](#contributing-without-writing-code). You do not need to install anything.

---

## Running the tests offline

The core suite requires **no network and no API keys**. That is a property worth protecting, not an accident: it is what keeps CI free, keeps the `rules_only` leaderboard baseline honest, and lets anyone verify the deterministic half of the system without spending a cent.

```bash
git clone <repo> && cd scam_detector

python -m venv .venv
.venv/Scripts/activate          # Windows
source .venv/bin/activate       # macOS, Linux

pip install -e ".[dev]"

pytest                          # no .env, no keys, no network
ruff check src tests
```

If `pytest` passes with no `.env` file present and your network unplugged, your environment is correct. If it fails without one, that is a bug in the test, not in your setup — please report it.

**The rule this implies.** Everything under `src/saqbol/core/` is offline by construction. A test in the core suite may not open a socket, call a model provider, read a clock it did not control, or need a database. Anything that genuinely requires the network belongs outside the core suite and must be skipped by default, so that a fresh clone on a plane still goes green.

The one network path in the whole core package is redirect resolution in `url_analyzer.py`, and it is opt-in per call precisely so that this guarantee holds. Do not add a second one without saying so in your pull request.

---

## Contracts change in the document before the code

This project is being built in parallel lanes against written contracts. If the schema in your head and the schema in the document disagree, someone else is already building against the document, and your code is the thing that is wrong.

So, in this order:

1. **Edit the document first.** Schemas and types live in [docs/02_DATA_CONTRACTS.md](docs/02_DATA_CONTRACTS.md). Indicator definitions live in [docs/03_INDICATORS.md](docs/03_INDICATORS.md). Playbooks in [docs/04_PLAYBOOKS.md](docs/04_PLAYBOOKS.md). Metrics and dataset rules in [docs/05_EVAL_PROTOCOL.md](docs/05_EVAL_PROTOCOL.md).
2. **Then change the code** to match what the document now says.
3. **Ship both in the same pull request**, with the document edit as its own commit, first in the branch.

A pull request that changes a dataclass field, a database column, an indicator id, a verdict band, or a JSON key without a matching document change will be asked to add one — even when the code is obviously better. "Obviously better" is exactly the case worth writing down, because it is the case other people will otherwise keep re-deriving.

This applies to contracts, not to everything. A bug fix, a faster implementation, a clearer error message, or a new test needs no document change.

### Pull requests

- One task or one idea per pull request. The roadmap in [docs/10_REMAINING_ROADMAP.md](docs/10_REMAINING_ROADMAP.md) refers to numbered tasks (`T113`, `T602`, …); if your work matches one, use that id in the commit subject.
- New behaviour arrives with a test. New *detection* behaviour arrives with both a positive and a negative case — a rule that fires on nothing is useless, and a rule that fires on everything is worse than useless.
- Run `ruff check src tests` before pushing.
- Say in the description what a reviewer should be suspicious of. A pull request that claims to be perfect is slower to review than one that points at its own soft spot.
- Found a security problem instead? Do not open a pull request. See [SECURITY.md](SECURITY.md).

---

## Contributing without writing code

### По-русски

Самая нужная помощь проекту — не программирование. Нужны люди, которые действительно говорят по-казахски и по-русски и понимают, как звучит настоящее мошенническое сообщение.

Что можно сделать:

1. **Разметка сообщений.** Главная задача. Открываете [инструмент разметки KazScam](https://claude.ai/code/artifact/4f3be71c-4a63-4adc-9ba2-33eb1565b196), читаете сообщение, отвечаете: мошенничество или нет, и если да — по какому сценарию. Ничего устанавливать не нужно, работает в браузере. Пачка из 40 сообщений занимает 20–30 минут. Персональные данные из текстов уже удалены до того, как вы их увидите.
2. **Проверка сценариев.** В [docs/04_PLAYBOOKS.md](docs/04_PLAYBOOKS.md) описаны тринадцать мошеннических сценариев. Скажите, где формулировка звучит неестественно, где сценарий устарел, и какого сценария не хватает. Достаточно написать это своими словами в issue.
3. **Казахский язык.** Самое ценное и самое редкое. Много текста в проекте написано по-русски и переведено на казахский. Переведённый казахский слышно сразу. Скажите, где именно — этого достаточно, править самому не обязательно.
4. **Тексты бота.** Сообщения бота должны быть понятны человеку, который прямо сейчас напуган и торопится. Если формулировка длинная, канцелярская или непонятная — это ошибка, и о ней стоит сообщить.
5. **Реальные примеры.** Если вам приходило мошенническое сообщение, отправьте его боту и поставьте галочку согласия. Оно попадёт в очередь на проверку человеком, а не сразу в датасет. Условия — в [PRIVACY.md](PRIVACY.md).

Как начать: откройте issue в репозитории и напишите, что хотите помочь и на каких языках говорите. Писать можно по-казахски, по-русски или по-английски. Английский не требуется.

Ваше имя попадёт в [CONTRIBUTORS.md](CONTRIBUTORS.md) — можно под псевдонимом, можно вообще без имени.

### In English

The most valuable contribution to this project is not code. It is people who actually speak Kazakh and Russian and know what a real scam message sounds like.

1. **Annotation.** The main task. Open the [KazScam annotation tool](https://claude.ai/code/artifact/4f3be71c-4a63-4adc-9ba2-33eb1565b196), read a message, and answer: scam or not, and if so, which script. Nothing to install, runs in a browser. A batch of 40 takes 20–30 minutes. Personal data is stripped from every text before you see it.
2. **Playbook review.** [docs/04_PLAYBOOKS.md](docs/04_PLAYBOOKS.md) describes thirteen scam scripts. Tell us where the wording rings false, where a script is out of date, and which script is missing. Plain words in an issue are enough.
3. **Kazakh.** The most valuable and the scarcest. Much of the project's text was written in Russian and translated. Translated Kazakh is audible immediately. Pointing at it is enough — you do not have to fix it yourself.
4. **Bot copy.** The bot's messages have to land with someone who is frightened and in a hurry right now. Wording that is long, bureaucratic, or unclear is a defect worth reporting.
5. **Real examples.** If you received a scam message, send it to the bot and tick the consent box. It enters a human review queue, not the dataset directly. Terms in [PRIVACY.md](PRIVACY.md).

To start, open an issue saying that you want to help and which languages you speak. Write in Kazakh, Russian, or English — English is not required.

Your name goes in [CONTRIBUTORS.md](CONTRIBUTORS.md), under a pseudonym or omitted entirely if you prefer.

---

## Licence

Code contributions are accepted under the [MIT licence](LICENSE). The KazScam dataset carries its own licence and datasheet, released separately; annotation work is credited in [CONTRIBUTORS.md](CONTRIBUTORS.md) and in the dataset's datasheet.
