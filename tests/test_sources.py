import pytest
import respx
from httpx import Response

from monitor.sources.adzuna import AdzunaSource
from monitor.sources.arbeitnow import ArbeitnowSource
from monitor.sources.github_repo import GithubRepoSource
from monitor.sources.himalayas import HimalayasSource
from monitor.sources.remoteok import RemoteOKSource
from monitor.sources.remotive import RemotiveSource


@respx.mock
def test_remotive_source_mapeia_vagas():
    respx.get("https://remotive.com/api/remote-jobs").mock(
        return_value=Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Python Dev",
                        "company_name": "Acme",
                        "url": "https://remotive.com/job/123",
                        "candidate_required_location": "Brazil",
                        "publication_date": "2026-07-01T00:00:00",
                        "description": "vaga remota",
                    }
                ]
            },
        )
    )

    vagas = RemotiveSource(categoria="software-dev").fetch()

    assert len(vagas) == 1
    vaga = vagas[0]
    assert vaga.id == "remotive:123"
    assert vaga.titulo == "Python Dev"
    assert vaga.empresa == "Acme"
    assert vaga.remoto is True
    assert vaga.fonte == "remotive"


@respx.mock
def test_github_repo_source_ignora_pull_requests():
    respx.get("https://api.github.com/repos/backend-br/vagas/issues").mock(
        return_value=Response(
            200,
            json=[
                {
                    "number": 1,
                    "title": "[Acme] Backend Jr",
                    "html_url": "https://github.com/backend-br/vagas/issues/1",
                    "body": "descricao da vaga",
                    "created_at": "2026-07-01T00:00:00Z",
                },
                {
                    "number": 2,
                    "title": "PR de exemplo",
                    "html_url": "https://github.com/backend-br/vagas/pull/2",
                    "pull_request": {"url": "https://api.github.com/..."},
                    "body": "",
                    "created_at": "2026-07-01T00:00:00Z",
                },
            ],
        )
    )

    vagas = GithubRepoSource(repo="backend-br/vagas").fetch()

    assert len(vagas) == 1
    assert vagas[0].id == "github:backend-br/vagas:1"
    assert vagas[0].titulo == "[Acme] Backend Jr"


@respx.mock
def test_adzuna_source_mapeia_vagas():
    respx.get("https://api.adzuna.com/v1/api/jobs/br/search/1").mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "id": "999",
                        "title": "Desenvolvedor Python",
                        "company": {"display_name": "Acme"},
                        "location": {"display_name": "Brasília, DF"},
                        "redirect_url": "https://adzuna.com.br/job/999",
                        "created": "2026-07-01T00:00:00Z",
                        "description": "vaga de backend em python",
                    }
                ]
            },
        )
    )

    vagas = AdzunaSource(
        pais="br", where="Brasília", app_id="id-teste", app_key="key-teste"
    ).fetch()

    assert len(vagas) == 1
    vaga = vagas[0]
    assert vaga.id == "adzuna:999"
    assert vaga.titulo == "Desenvolvedor Python"
    assert vaga.empresa == "Acme"
    assert vaga.localizacao == "Brasília, DF"
    assert vaga.remoto is None


def test_adzuna_source_sem_credenciais_da_erro_claro(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ADZUNA_APP_ID"):
        AdzunaSource().fetch()


@respx.mock
def test_remoteok_source_ignora_aviso_legal_e_mapeia_vagas():
    respx.get("https://remoteok.com/api").mock(
        return_value=Response(
            200,
            json=[
                {"legal": "aviso da API, não é vaga"},
                {
                    "id": "555",
                    "position": "Python Backend Engineer",
                    "company": "Acme",
                    "url": "https://remoteok.com/remote-jobs/555",
                    "location": "Worldwide",
                    "date": "2026-07-01T00:00:00",
                    "description": "vaga remota de python",
                },
            ],
        )
    )

    vagas = RemoteOKSource().fetch()

    assert len(vagas) == 1
    vaga = vagas[0]
    assert vaga.id == "remoteok:555"
    assert vaga.titulo == "Python Backend Engineer"
    assert vaga.remoto is True


@respx.mock
def test_arbeitnow_source_mapeia_vagas_e_respeita_flag_remoto():
    respx.get("https://arbeitnow.com/api/job-board-api").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "slug": "python-dev-acme-123",
                        "title": "Python Developer",
                        "company_name": "Acme",
                        "url": "https://arbeitnow.com/jobs/companies/acme/python-dev-123",
                        "location": "Berlin",
                        "remote": False,
                        "created_at": 1784712627,
                        "description": "vaga de python",
                    }
                ]
            },
        )
    )

    vagas = ArbeitnowSource().fetch()

    assert len(vagas) == 1
    vaga = vagas[0]
    assert vaga.id == "arbeitnow:python-dev-acme-123"
    assert vaga.localizacao == "Berlin"
    assert vaga.remoto is False


@respx.mock
def test_himalayas_source_mapeia_vagas():
    respx.get("https://himalayas.app/jobs/api/search").mock(
        return_value=Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Senior Python Developer, Brazil",
                        "companyName": "CI&T",
                        "applicationLink": "https://himalayas.app/companies/ci-t/jobs/python-dev",
                        "guid": "https://himalayas.app/companies/ci-t/jobs/python-dev",
                        "locationRestrictions": ["Brazil"],
                        "pubDate": 1784711650,
                        "excerpt": "vaga de python no brasil",
                    }
                ]
            },
        )
    )

    vagas = HimalayasSource(country="Brazil", q="python").fetch()

    assert len(vagas) == 1
    vaga = vagas[0]
    assert vaga.id == "himalayas:https://himalayas.app/companies/ci-t/jobs/python-dev"
    assert vaga.empresa == "CI&T"
    assert vaga.localizacao == "Brazil"
    assert vaga.remoto is None
