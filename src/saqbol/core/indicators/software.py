"""Family F — software installation.

Remote-access tooling is the difference between a scam that needs the victim to
type and one where the operator drives the banking app themselves. F1 and F2
are entity-driven, so they catch the Cyrillic spellings a caller dictates aloud
as well as the Latin ones.
"""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import DetectionContext, indicator, keyword_indicator
from saqbol.core.types import IndicatorHit, Severity

keyword_indicator(
    "F3.install_instruction",
    Severity.HIGH,
    "Instructs the recipient to install an application or open a downloaded file",
    phrases=[
        "установите приложение",
        "установить приложение",
        "скачайте приложение",
        "скачайте по ссылке",
        "загрузите файл",
        "откройте вложение",
        "установите программу",
        "install this app",
        "download the app",
        # kk
        *kk("F3.install_instruction"),
    ],
)

keyword_indicator(
    "F4.disable_protection",
    Severity.HIGH,
    "Asks the recipient to disable protections or grant broad permissions",
    phrases=[
        "отключите play protect",
        "отключите защиту",
        "отключите антивирус",
        "разрешите доступ",
        "специальн* возможност*",
        "разрешите установку из неизвестных источников",
        "disable play protect",
        "allow accessibility",
    ],
)


@indicator(
    "F1.remote_access_app",
    Severity.CRITICAL,
    "A remote-access tool is named in an unsolicited context",
)
def remote_access_app(ctx: DetectionContext) -> list[IndicatorHit]:
    if not ctx.entities.app_names:
        return []
    return [
        IndicatorHit(
            indicator_id="F1.remote_access_app",
            severity=Severity.CRITICAL,
            detail={"apps": ctx.entities.app_names},
        )
    ]


@indicator(
    "F2.apk_attachment",
    Severity.CRITICAL,
    "An Android package is attached or linked",
)
def apk_attachment(ctx: DetectionContext) -> list[IndicatorHit]:
    if not ctx.entities.has_apk:
        return []
    return [IndicatorHit(indicator_id="F2.apk_attachment", severity=Severity.CRITICAL)]
