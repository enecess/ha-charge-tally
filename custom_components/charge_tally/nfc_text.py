"""Localized copy for HA-managed automation names and descriptions."""

AUTOMATION_TEXT = {
    "en": (
        "[Charge Tally managed] {point} · {tag} · Identity selection",
        "Created and maintained by Charge Tally. Edit tag, device and identity mappings in Charge Tally > Configure > NFC identity links. Do not edit triggers or actions directly.",
    ),
    "zh": (
        "[Charge Tally 托管] {point} · {tag} · 身份切换",
        "此自动化由 Charge Tally 创建和维护。请前往“Charge Tally → 配置 → NFC 身份联动”修改标签、设备和身份映射。请勿直接修改触发条件或动作，以免与集成配置不一致。",
    ),
    "de": (
        "[Charge Tally verwaltet] {point} · {tag} · Identitätsauswahl",
        "Diese Automation wird von Charge Tally erstellt und verwaltet. Bearbeiten Sie Tags, Geräte und Identitäten unter Charge Tally > Konfigurieren > NFC-Identitätsverknüpfungen. Ändern Sie Auslöser oder Aktionen nicht direkt.",
    ),
    "fr": (
        "[Gérée par Charge Tally] {point} · {tag} · Choix d’identité",
        "Cette automatisation est créée et gérée par Charge Tally. Modifiez les tags, appareils et identités dans Charge Tally > Configurer > Associations d’identité NFC. Ne modifiez pas directement les déclencheurs ou les actions.",
    ),
    "pl": (
        "[Zarządza Charge Tally] {point} · {tag} · Wybór tożsamości",
        "Ta automatyzacja jest tworzona i zarządzana przez Charge Tally. Zmieniaj znaczniki, urządzenia i tożsamości w Charge Tally > Konfiguruj > Powiązania tożsamości NFC. Nie zmieniaj bezpośrednio wyzwalaczy ani działań.",
    ),
    "it": (
        "[Gestita da Charge Tally] {point} · {tag} · Scelta identità",
        "Questa automazione è creata e gestita da Charge Tally. Modifica tag, dispositivi e identità in Charge Tally > Configura > Collegamenti identità NFC. Non modificare direttamente trigger o azioni.",
    ),
}


def automation_copy(language, point, tag):
    """Use the configured HA language, independently of the current browser."""
    base = str(language).replace("_", "-").split("-")[0].lower()
    name, description = AUTOMATION_TEXT.get(base, AUTOMATION_TEXT["en"])
    return {"name": name.format(point=point, tag=tag), "description": description}
