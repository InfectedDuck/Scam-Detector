"""Family H — offers that are too good to be true."""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import keyword_indicator
from saqbol.core.types import Severity

keyword_indicator(
    "H1.guaranteed_returns",
    Severity.HIGH,
    "Promises returns without risk",
    phrases=[
        "гарантированн* доход",
        "гарантирую прибыль",
        "гарантированн* прибыл*",
        "без риска",
        "доход в месяц",
        "пассивн* доход",
        "guaranteed return",
        "risk-free",
        # kk
        *kk("H1.guaranteed_returns"),
        # zh
        "零风险",
        "稳赚不亏",
        "稳赚",
        "保证收益",
        "稳定收益",
        "无风险",
        "包赚",
    ],
)

keyword_indicator(
    "H2.celebrity_investment",
    Severity.HIGH,
    "Endorsement-led investment funnel, the deepfake advertisement pattern",
    phrases=[
        "инвестиционн* платформ*",
        "торгов* платформ*",
        "личный менеджер",
        "персональн* менеджер",
        "рекомендует инвестировать",
        "закрыт* инвестиционн* клуб",
        "investment platform",
        "personal manager",
        # kk
        *kk("H2.celebrity_investment"),
    ],
)

keyword_indicator(
    "H3.unsolicited_prize",
    Severity.MEDIUM,
    "Unsolicited win, payout or compensation",
    phrases=[
        "вы выиграли",
        "вы стали победителем",
        "вам положена выплата",
        "вам положена компенсац*",
        "получите компенсац*",
        "ваш приз",
        "you have won",
        "you are entitled to",
        # kk
        *kk("H3.unsolicited_prize"),
    ],
)

keyword_indicator(
    "H4.easy_job",
    Severity.MEDIUM,
    "High pay, no experience, work from a phone",
    phrases=[
        "работа в телеграм",
        "удаленн* подработк*",
        "подработка без опыта",
        "без опыта работы",
        "заработок от",
        "доход от",
        "простая работа в интернете",
        "easy money",
        # zh
        "刷单",
        "日结",
        "兼职招聘",
        # kk
        *kk("H4.easy_job"),
        # zh
        "轻松赚钱",
        "无需经验",
        "手机操作即可",
        "每单佣金",
    ],
)

keyword_indicator(
    "H5.romance_to_investment",
    Severity.HIGH,
    "Rapport pivoting into a trading platform",
    phrases=[
        "научу зарабатывать",
        "инвестируем вместе",
        "мой брокер",
        "мой наставник",
        "я тебе помогу заработать",
        "let me teach you to trade",
        # kk
        *kk("H5.romance_to_investment"),
    ],
)
