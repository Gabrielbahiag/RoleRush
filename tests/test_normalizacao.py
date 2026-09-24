from pathlib import Path

import pytest

from monitor.curriculo.normalizacao import detectar_idioma, normalizar_texto

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vagas"


def _ler(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


def _linhas(texto: str) -> list[str]:
    return [linha for linha in texto.splitlines() if linha]


def test_html_vira_texto_limpo():
    texto = normalizar_texto("<p>Buscamos <strong>Python</strong> sênior.</p><p>Vaga remota.</p>")

    assert "<p>" not in texto
    assert "<strong>" not in texto
    assert "Buscamos Python sênior." in texto
    assert "Vaga remota." in texto


def test_entidades_html_sao_decodificadas():
    assert "P&D" in normalizar_texto("<p>Time de P&amp;D</p>")


def test_html_duplamente_escapado_do_greenhouse_vira_texto():
    # o Greenhouse devolve HTML escapado dentro do JSON: &lt;p&gt;...&lt;/p&gt;
    assert normalizar_texto("&lt;p&gt;We are hiring&lt;/p&gt;").strip() == "We are hiring"


def test_listas_html_viram_linhas_separadas():
    assert _linhas(normalizar_texto("<ul><li>Python</li><li>SQL</li></ul>")) == ["Python", "SQL"]


def test_markdown_vira_texto_limpo_preservando_linhas():
    bruto = "## Requisitos\n\n- **Python** avançado\n- [SQL](https://exemplo.com) básico\n"

    texto = normalizar_texto(bruto)

    assert "##" not in texto
    assert "**" not in texto
    assert "](" not in texto
    assert _linhas(texto) == ["Requisitos", "Python avançado", "SQL básico"]


def test_quebra_de_linha_e_preservada_para_deteccao_de_secao():
    # a extração depende das linhas pra separar "Requisitos" de "Diferenciais";
    # colapsar tudo em uma linha só quebraria essa separação.
    assert len(_linhas(normalizar_texto("<p>Requisitos:</p><p>Python</p>"))) == 2


def test_espacos_horizontais_sao_colapsados():
    assert normalizar_texto("Python      e     SQL") == "Python e SQL"


def test_texto_vazio_nao_quebra():
    assert normalizar_texto("") == ""


def test_detecta_portugues():
    texto = "Buscamos uma pessoa desenvolvedora para atuar no time de dados."

    assert detectar_idioma(texto) == "pt"


def test_detecta_ingles():
    texto = "We are looking for a developer to join our data team."

    assert detectar_idioma(texto) == "en"


def test_texto_sem_sinal_de_idioma_cai_no_padrao_deterministico():
    # sem stopword de nenhum idioma não há o que decidir: o padrão é fixo
    # pra manter a saída reproduzível.
    assert detectar_idioma("Python SQL Docker") == "pt"


@pytest.mark.parametrize(
    "arquivo,esperado",
    [
        ("remotive_en.html", "en"),
        ("greenhouse_escaped.html", "en"),
        ("github_pt.md", "pt"),
        ("adzuna_pt.html", "pt"),
    ],
)
def test_detecta_idioma_em_descricoes_reais_das_fontes(arquivo, esperado):
    assert detectar_idioma(normalizar_texto(_ler(arquivo))) == esperado
