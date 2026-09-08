"""Family D — channel migration.

Moving the conversation is how a scammer escapes a platform's protections and,
in D3, how they stop the victim from getting a second opinion. D3 carries the
highest weight in the family for that reason: "do not hang up" has no
legitimate use in an unsolicited call.
"""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import keyword_indicator
from saqbol.core.types import Severity

keyword_indicator(
    "D1.move_to_messenger",
    Severity.MEDIUM,
    "Pushes the conversation into WhatsApp or Telegram",
    phrases=[
        "напишите в whatsapp",
        "напишите в ватсап",
        "напишите мне в",
        "перейдите в телеграм",
        "перейдем в телеграм",
        "продолжим в whatsapp",
        "свяжитесь со мной в",
        "мой ватсап",
        "мой telegram",
        "write me on whatsapp",
        "message me on telegram",
        # zh
        "加我微信",
        "私聊",
    ],
)

keyword_indicator(
    "D2.leave_platform",
    Severity.MEDIUM,
    "Proposes finishing a marketplace deal outside the platform",
    phrases=[
        "не через сайт",
        "вне сайта",
        "мимо площадки",
        "напрямую без посредник*",
        "оплатим напрямую",
        "переведем без олх",
        "outside the platform",
    ],
)

keyword_indicator(
    "D3.dont_hang_up",
    Severity.HIGH,
    "Instructs the recipient to stay on the line",
    phrases=[
        "не кладите трубку",
        "не вешайте трубку",
        "оставайтесь на линии",
        "не отключайтесь",
        "не прерывайте разговор",
        "не завершайте звонок",
        "do not hang up",
        "stay on the line",
        # kk. Unlike family A, the prohibitive suffix is the signal here.
        *kk("D3.dont_hang_up"),
        # zh
        "不要挂电话",
        "保持通话",
    ],
)
