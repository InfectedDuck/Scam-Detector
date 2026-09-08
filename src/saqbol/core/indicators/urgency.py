"""Family B — urgency and fear.

Weak individually and deliberately so. Real institutions do send time-sensitive
alerts, and B4 in particular overlaps heavily with genuine fraud warnings from
banks. These rules matter through the combination bonuses in `fuse.py`, not on
their own.
"""

from __future__ import annotations

from saqbol.core.indicators.registry import keyword_indicator
from saqbol.core.types import Severity

keyword_indicator(
    "B1.urgency",
    Severity.MEDIUM,
    "Artificial time pressure",
    phrases=[
        "срочно",
        "немедленно",
        "незамедлительно",
        "прямо сейчас",
        "как можно быстрее",
        "иначе будет поздно",
        "время ограничен*",
        "истекает через",
        "у вас есть несколько минут",
        # kk — TODO-kk
        "жедел",
        "шұғыл",
        "дереу",
        # en
        "urgently",
        "immediately",
        "right now",
        # zh
        "马上",
        "立即",
        "尽快",
    ],
)

keyword_indicator(
    "B2.account_block_threat",
    Severity.MEDIUM,
    "Threatens to block or close the account",
    phrases=[
        "будет заблокирован*",
        "счет заблокир*",
        "карта заблокир*",
        "блокировка счет*",
        "блокировка карт*",
        "доступ будет закрыт",
        "аккаунт будет удален",
        "will be blocked",
        "account suspended",
        # kk — TODO-kk
        "бұғатталады",
    ],
)

keyword_indicator(
    "B3.criminal_threat",
    Severity.HIGH,
    "Threatens prosecution, arrest or a criminal case",
    phrases=[
        "уголовн* дел*",
        "уголовн* ответственност*",
        "статья ук",
        "объявлен в розыск",
        "вас арестуют",
        "следовател*",
        "прокурор",
        "судебн* пристав*",
        "criminal case",
        "arrest warrant",
        # kk — TODO-kk
        "қылмыстық іс",
        # zh
        "涉嫌洗钱",
        "涉嫌犯罪",
        "刑事案件",
        "通缉",
        "逮捕",
    ],
)

keyword_indicator(
    "B4.money_at_risk",
    Severity.MEDIUM,
    "Claims funds are being taken right now",
    phrases=[
        "пытаются списать",
        "попытка списани*",
        "подозрительн* операци*",
        "несанкционированн* вход",
        "несанкционированн* операци*",
        "зафиксирована попытка",
        "с вашего счета пытаются",
        "suspicious transaction",
        "unauthorised transaction",
        "unauthorized transaction",
        # kk — TODO-kk
        "күдікті операция",
    ],
)
