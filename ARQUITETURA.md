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
isso que o `marcar_todas()` em [`storage.py`](src/monitor/storage.py) é um
upsert (`INSERT ... ON CONFLICT(id) DO UPDATE`), não um `INSERT` puro —
rodar duas vezes com a mesma lista não gera erro nem duplicata, só avança o
`ultimo_visto`. Veja o teste que trava essa garantia:
[`test_marcar_todas_e_idempotente`](tests/test_storage.py).

O id resolve "é o mesmo anúncio?", mas não "é a mesma vaga?": a mesma vaga
aparece no Jobicy e no Remotive com ids diferentes, ou nove vezes no Jobicy,
uma por país ("Security Engineer (Remote - Denmark)", "... (Remote -
Spain)"). Pra isso existe uma segunda chave, a **impressão digital**
(`impressao_digital()` em [`filters.py`](src/monitor/filters.py)): empresa +
título normalizado, sem o qualificador de regime. Ela não substitui o id —
só decide se vale *notificar*. E ela é conservadora de propósito: sem
empresa (issues do GitHub) não há impressão digital, e parênteses que não
falam de regime ("(Backend)" vs "(Frontend)") continuam separando vagas.
Errar pra "notificar duas vezes" é barato; errar pra "engolir uma vaga" é o
pior resultado possível deste projeto.

---

## 6. Isolamento de falha: uma fonte quebrada não derruba o pipeline

Em [`main.py`](src/monitor/main.py):

```python
for fonte in fontes:
    try:
        encontradas = fonte.fetch()
    except Exception as erro:
        falhas[fonte.nome] = descrever_erro(erro)
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

A outra metade da lição veio depois, numa auditoria: **isolamento sem
aviso vira silêncio.** Na primeira versão, a falha só ia pro log — e o job
terminava verde. Pior ainda, uma fonte que "funciona" mas não rende nada é
indistinguível de uma saudável: os quatro repositórios de vagas do GitHub
passaram quatro meses entregando uma vaga, no total, sem ninguém perceber
(a causa era o filtro, item 9). Por isso `coletar_vagas` devolve também o
dicionário `falhas`, cada execução grava o funil por fonte (coletadas →
aprovadas → notificadas) e o [`saude.py`](src/monitor/saude.py) transforma
isso em dois avisos no Telegram: "fonte X quebrou" (só na transição de ok
pra falha, pra não repetir a cada 6 horas) e um resumo semanal que destaca
fonte quebrada, muda ou que nada passa no filtro.

O mesmo raciocínio vale um nível abaixo, dentro de cada fonte:
`Source._mapear_itens` mapeia item a item, então um item malformado é
descartado sem levar a fonte inteira junto. Mas se *nenhum* item é
reconhecido, o formato da API mudou — e isso vira falha (e aviso), não um
"zero vagas" calado.

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

O mesmo vazamento tinha uma segunda porta, achada depois: a *mensagem de
erro* do `httpx`. `raise_for_status()` gera `HTTPStatusError("Client error
'401' for url 'https://api.telegram.org/bot<TOKEN>/sendMessage'")`, e um
`logger.exception(...)` ou um traceback não tratado imprime isso inteiro (o
`app_key` da Adzuna vai na query string do mesmo jeito). No Actions o
mascaramento de secrets do GitHub escondia; num terminal local, não. Por
isso nenhum erro de rede é logado com `str(erro)`: `descrever_erro()` em
[`saude.py`](src/monitor/saude.py) só expõe status e tipo, e o notifier
lança `ErroTelegram`, que nunca carrega a URL.

---

## 8. Um bug pequeno, mas didático: `in` vs. `\b...\b`

Em [`filters.py`](src/monitor/filters.py), a comparação de palavra-chave
usa regex com word boundary, não `in`:

```python
re.compile(rf"(?<!\w){re.escape(base)}{continuacao}(?!\w)")
```

(Na primeira versão era `\b...\b`; os lookarounds fazem o mesmo papel e
ainda funcionam pra termos que terminam em símbolo, como "c++", onde um
`\b` final nunca casa — a mesma lição do `extracao.py`.)

Com `termo.lower() in texto`, a palavra-chave `"ia"` bateria em qualquer
trecho que contivesse a sequência de caracteres "ia" — inclusive dentro de
**"engenharia"**. É um erro de categoria clássico: confundir "é substring
de" com "é a mesma palavra que". `\b` ancora a busca nas bordas de uma
palavra, então "ia" bate em "Especialista em **IA**" mas não em
"engenh**aria**" nem em "necess**ária**". O teste
[`test_palavra_curta_nao_da_falso_positivo_em_substring`](tests/test_filters.py)
existe justamente pra travar essa garantia e impedir que alguém
"simplifique" de volta pro `in` no futuro.

---

## 9. "Não sei" não é "não": o filtro de local e o `remoto=None`

`Vaga.remoto` é um booleano de três estados: `True`, `False` e `None`
(a fonte não informa). O filtro de local original tratava qualquer coisa
diferente de `True` como presencial — e presencial só passa se citar
Brasília. Resultado: as issues do GitHub e as vagas do Himalayas, que
chegam com `None`, eram descartadas em massa. "[Remoto] Desenvolvedor
Python Pleno" não passava.

A correção em [`filters.py`](src/monitor/filters.py) é `eh_remota()`: o que
a fonte disser vale; se ela não souber, o título decide ("[Remoto]",
"remote", "home office"). As fontes também passaram a informar melhor:
o GitHub lê as labels da issue ("Remoto", "Presencial", "Híbrido") e o
Himalayas, que só lista remotas, passou a dizer `True`.

O problema simétrico era o ruído: `remoto=True` passava sempre, inclusive
"remoto só nos EUA". Agora existe `filtros.remoto_aceito` no config: uma
remota com restrição de país só passa se a restrição citar um desses termos
(Brasil, LATAM, worldwide…) ou a região de `localizacao`. Remota sem
restrição declarada continua passando — de novo, "não sei" não vira "não".

Toda comparação passa por `normalizar()`: sem HTML (Remotive e Jobicy
mandam HTML cru; o Greenhouse, escapado duas vezes), sem acento e em
minúsculas. E um termo terminado em `*` casa qualquer continuação
("desenvolvedor*" pega desenvolvedora e desenvolvedores).

---

## 10. Só é "visto" o que foi entregue

A ordem das operações no fim de `run()` decide se uma falha causa perda
ou repetição de aviso. A versão original marcava tudo como visto depois do
laço de envio — então uma falha na 15ª mensagem (um 429 do Telegram, por
exemplo) fazia as 14 primeiras serem reenviadas a cada execução e as
seguintes nunca chegarem. E, sem credenciais do Telegram, o código só
avisava no log e marcava tudo como visto: perda silenciosa.

Agora o notifier chama um callback `ao_enviar(vaga)` a cada entrega, e é
ele que grava a vaga como vista. Junto com isso:

- 429 espera o `retry_after`; 5xx e rede têm recuo exponencial; há uma
  pausa de 1,1 s entre mensagens.
- um 400 numa mensagem específica é reenviado sem HTML, pra ela não virar
  uma "pílula venenosa" que trava a fila pra sempre.
- `max_por_execucao` limita a rajada; o excedente não é marcado e vem na
  próxima execução, mais recentes primeiro. Acima de `agrupar_acima`,
  várias vagas vão na mesma mensagem.
- sem credenciais, localmente só imprime (sem gravar nada); no Actions, o
  job falha.
- o workflow commita o `vagas.db` mesmo quando o monitor falhou
  (`if: !cancelled()`) — senão o progresso parcial se perderia.

E a retenção: `run()` só marcava as vagas *novas*, então o `ultimo_visto`
nunca avançava e a poda por `ultimo_visto` se comportava exatamente como a
poda antiga por `visto_em`. Os testes de `storage.py` passavam, porque
nenhum deles exercitava o caminho de `run()`. O teste
[`test_run_atualiza_ultimo_visto_de_vaga_que_reaparece...`](tests/test_main.py)
agora cobre a integração.
