# Role Rush — Lógica de programação e estrutura de código

> Explicação didática das decisões de design por trás do projeto, da mais
> estrutural (o que sustenta tudo) até as mais pontuais.

---

## 1. O padrão de plugin: uma interface, várias implementações

O coração arquitetural do projeto está em três linhas: [`sources/base.py`](src/monitor/sources/base.py).

```python
class Source(ABC):
    nome: str

    @abstractmethod
    def fetch(self) -> list[Vaga]:
        raise NotImplementedError
```

Isso é o **Strategy Pattern** (ou, em termos de princípios de design, o *"O" do
SOLID* — Open/Closed Principle: aberto para extensão, fechado para
modificação). A ideia central: `main.py` não sabe — e não *deveria* saber —
que existe Remotive, GitHub ou Adzuna. Ele só sabe que tem uma lista de
objetos que respondem a `.fetch()` e devolvem `list[Vaga]`:

```python
def coletar_vagas(fontes: list[Source]) -> list[Vaga]:
    for fonte in fontes:
        encontradas = fonte.fetch()   # não importa QUAL fonte é
```

**Por que isso importa de verdade:** sem essa abstração, `coletar_vagas`
teria um `if fonte == "remotive": ... elif fonte == "github": ...` que
cresce a cada fonte nova e mistura duas responsabilidades que deveriam ser
independentes — "como buscar dados de uma API específica" e "como
orquestrar a busca". Com a interface, adicionar o Adzuna significou **zero
alterações** em `filters.py`, `storage.py` ou `notifier.py` — só um arquivo
novo (`adzuna.py`) que implementa o contrato, e uma linha em
`montar_fontes()` pra registrá-lo. Isso é o teste real de uma boa
abstração: o "raio de explosão" de uma mudança fica contido.

---

## 2. O modelo `Vaga`: uma fronteira de tradução (Adapter Pattern)

Cada fonte fala um "idioma" JSON diferente — o Remotive chama a empresa de
`company_name`, o GitHub não tem campo de empresa nenhum (fica dentro do
título da issue), o Adzuna aninha tudo em `company.display_name`. Se o
resto do sistema (filtros, dedup, notificação) tivesse que lidar com três
formatos diferentes, cada um desses módulos precisaria saber sobre todas
as fontes — voltando ao mesmo problema do item 1.

A solução é ter **um único formato interno**, a dataclass `Vaga`
([`models.py`](src/monitor/models.py)), e cada fonte é responsável por
*traduzir* sua resposta bruta pra esse formato, num método privado
`_mapear()`. Por exemplo, em [`adzuna.py`](src/monitor/sources/adzuna.py):

```python
def _mapear(self, item: dict) -> Vaga:
    return Vaga(
        id=f"adzuna:{item['id']}",
        titulo=item.get("title", ""),
        empresa=(item.get("company") or {}).get("display_name", ""),
        ...
    )
```

Isso é literalmente o **Adapter Pattern**: adapta uma interface externa (a
API de terceiros, que eu não controlo) pra uma interface interna (que eu
controlo e desenhei pra ser conveniente). A partir do momento em que a
`Vaga` existe, `filters.py` nunca mais precisa saber se ela veio do
Remotive ou do Adzuna.

---

## 3. Pipeline em camadas: funções puras separadas de efeitos colaterais

`run()` em [`main.py`](src/monitor/main.py) é essencialmente um pipeline
ETL de quatro estágios:

```
coletar (I/O: rede) → filtrar (puro) → deduplicar (I/O: disco) → notificar (I/O: rede)
```

O detalhe pedagógico mais valioso aqui é a diferença de natureza entre
esses estágios. `aplicar_filtros()` em [`filters.py`](src/monitor/filters.py)
é uma **função pura**: dados entram, dados saem, nada de rede, nada de
disco, nada de estado mutável externo. `coletar_vagas`, `Storage` e
`TelegramNotifier` são **impuros** por natureza — fazem I/O.

Por que separar isso é importante na prática (não só em teoria)? Porque
**funções puras são triviais de testar** — é por isso que
[`test_filters.py`](tests/test_filters.py) não precisa de nenhum mock,
servidor fake ou banco temporário: é só chamar a função com um `Vaga` de
mentira e comparar o `bool` de saída. Já testar `storage.py` e as
`sources/` exige simular o mundo externo (SQLite em `tmp_path`, HTTP com
`respx`) — porque são efeitos colaterais de verdade. Separar "o que
decide" (puro) de "o que executa" (impuro) é o que torna a maior parte da
lógica de negócio testável sem infraestrutura.

---

## 4. Validação na borda: "parse, don't validate"

`config.py` usa Pydantic pra transformar o YAML solto (texto sem tipo, sem
garantia nenhuma) num objeto `Config` totalmente tipado e validado, **uma
única vez**, na entrada do sistema:

```python
def carregar_config(caminho) -> Config:
    dados = yaml.safe_load(...)
    return Config.model_validate(dados)   # explode aqui se algo estiver errado
```

Esse é o princípio "parse, don't validate": depois dessa linha, todo o
resto do código pode simplesmente confiar que
`config.filtros.palavras_chave` é uma `list[str]` — nunca precisa checar
`if "palavras_chave" in dados`, nunca lida com `None` inesperado, nunca lê
a chave errada silenciosamente. O erro acontece cedo, alto e claro (na
carga do config), em vez de tarde, baixo e confuso (um `KeyError` obscuro
no meio do `filters.py`, três chamadas de função depois). Repare que isso
também documenta o schema: quem abre `config.py` vê exatamente quais
campos existem e seus tipos, sem precisar ler `config.yaml` pra adivinhar.

---

## 5. Chave de dedup: por que `id` nunca pode ser o título

`storage.py` deduplica por `Vaga.id`, nunca por título — e cada fonte
constrói esse id com um **namespace explícito**: `f"remotive:{item['id']}"`,
`f"github:{self.repo}:{item['number']}"`, `f"adzuna:{item['id']}"`.

Duas razões pra isso, ambas custosas se ignoradas:

1. **Colisão entre fontes.** Sem o prefixo, o id `999` do Adzuna colidiria
   com um id `999` do Remotive — duas vagas completamente diferentes
   tratadas como a mesma.
2. **Títulos não são estáveis nem únicos.** "Desenvolvedor Python" aparece
   dezenas de vezes por semana em empresas diferentes; usar o título como
   chave faria o sistema descartar vagas genuinamente novas (falso
   duplicado) ou, pior, tratar duas vagas diferentes com o mesmo título
   como uma coisa só.

Isso conecta direto com **idempotência**: rodar `main.py` duas vezes
seguidas com os mesmos dados não pode gerar notificação duplicada. É por
isso que `INSERT OR IGNORE` (não `INSERT` puro) aparece em
[`storage.py`](src/monitor/storage.py) — rodar o `marcar_todas()` duas
vezes com a mesma lista não deve gerar erro nem duplicata. Veja o teste
que trava exatamente essa garantia:
[`test_marcar_todas_e_idempotente`](tests/test_storage.py).

---

## 6. Isolamento de falha: uma fonte quebrada não derruba o pipeline

Em [`main.py`](src/monitor/main.py):

```python
for fonte in fontes:
    try:
        encontradas = fonte.fetch()
    except Exception:
        logger.exception("Falha ao buscar vagas em %s", fonte.nome)
        continue   # segue pras próximas fontes
```

Isso não é defensividade genérica — foi validado na prática duas vezes:
quando `frontend-br/vagas` não existia (404) e quando testamos o Adzuna
sem credenciais (`RuntimeError` de propósito, veja
[`adzuna.py`](src/monitor/sources/adzuna.py)). Em ambos os casos, o
pipeline continuou rodando com as fontes que funcionavam, em vez de o
processo inteiro morrer por causa de uma fonte só. Esse é o princípio de
**isolamento de falha** (*fault isolation*/*bulkhead*): erros de um
componente não devem se propagar e derrubar componentes independentes
dele.

---

## 7. O incidente do token: por que log é uma superfície de segurança

Esse foi o exemplo mais concreto do projeto todo, porque *aconteceu de
verdade* durante o desenvolvimento. `logging.basicConfig(level=logging.INFO)`
parece inofensivo — mas ele não configura só o *nosso* logger, ele eleva o
nível de **todo logger do processo**, inclusive os internos do `httpx`,
que registram a URL completa de cada requisição. E a API do Telegram
embute o segredo na própria URL (`/bot<TOKEN>/sendMessage`) — não tem como
pedir pra essa API "manda o token só no header", o design dela é assim.

A lição de fundo: **um vazamento de segredo raramente é o código que
manipula o segredo diretamente** (`notifier.py` nunca imprime o token).
Ele vem de uma camada adjacente e "inocente" — nesse caso, uma lib de
terceiros logando o que parece ser um dado técnico neutro (uma URL). A
correção foi silenciar especificamente esses loggers em
[`main.py`](src/monitor/main.py):

```python
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
```

mantendo o nosso próprio log em INFO. É um caso real do princípio de
**menor exposição**: cada componente deveria logar o mínimo necessário pro
seu próprio propósito, não tudo que passa por ele.

---

## 8. Um bug pequeno, mas didático: `in` vs. `\b...\b`

Em [`filters.py`](src/monitor/filters.py), a comparação de palavra-chave
usa regex com word boundary, não `in`:

```python
return any(re.search(rf"\b{re.escape(termo)}\b", texto) for termo in termos)
```

Com `termo.lower() in texto`, a palavra-chave `"ia"` bateria em qualquer
trecho que contivesse a sequência de caracteres "ia" — inclusive dentro de
**"engenharia"**. É um erro de categoria clássico: confundir "é substring
de" com "é a mesma palavra que". `\b` ancora a busca nas bordas de uma
palavra, então "ia" bate em "Especialista em **IA**" mas não em
"engenh**aria**" nem em "necess**ária**". O teste
[`test_palavra_curta_nao_da_falso_positivo_em_substring`](tests/test_filters.py)
existe justamente pra travar essa garantia e impedir que alguém
"simplifique" de volta pro `in` no futuro.
