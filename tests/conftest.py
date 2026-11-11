import pytest


@pytest.fixture(autouse=True)
def _ambiente_isolado(monkeypatch):
    """Nenhum teste depende do ambiente de quem roda a suíte.

    - GITHUB_ACTIONS: o monitor falha de propósito no Actions quando falta
      credencial do Telegram; a suíte roda no próprio Actions e não pode
      herdar esse comportamento sem pedir.
    - credenciais reais exportadas no shell nunca chegam aos testes.
    - as pausas do notifier (limite de taxa do Telegram) viram no-op.
    """
    for variavel in (
        "GITHUB_ACTIONS",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
        "GITHUB_TOKEN",
        "THEMUSE_API_KEY",
    ):
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setattr("monitor.notifier._dormir", lambda segundos: None)
