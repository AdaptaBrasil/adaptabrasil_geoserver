# AdaptaBrasil: mapas dos indicadores

App Flask que mostra os indicadores do AdaptaBrasil em mapas servidos pelo
GeoServer, no modelo da Sala de Situação do INPE: uma única layer
parametrizada (SQL view) atende todos os indicadores, anos e cenários.

## Como as peças se encaixam

```
Navegador ──► App Flask (este repositório) ──► PostgreSQL
   │            árvore de indicadores, legendas,
   │            estados, municípios, popup do hover
   │
   └──────────► GeoServer (fora do Docker)
                imagens do mapa (WMS), hover (GetFeatureInfo),
                downloads em CSV e shapefile (WFS)
```

- O **app** consulta o banco e entrega as páginas; o endereço público do
  GeoServer vai para o navegador, que pede os mapas direto a ele.
- O **GeoServer** roda fora do Docker, no mesmo servidor ou em outro, e guarda
  a configuração (layers e estilos) na pasta de dados dele.
- O **`scripts/configurar_geoserver.py`** cria ou atualiza a layer
  `adaptabrasil:indicador`, a layer de fundo e um estilo SLD por legenda da
  tabela `legend_items`. Rode de novo sempre que mudar `scripts/sld.py` ou as
  legendas no banco.

## Estrutura

| Caminho | O que é |
|---|---|
| `app.py` | Rotas do Flask e API (`/api/arvore`, `/api/indicadores`, `/api/geoobjetos`, ...) |
| `scripts/config.py` | Lê as variáveis de ambiente (`.env`) |
| `scripts/configurar_geoserver.py` | Publica a layer e os estilos no GeoServer (REST) |
| `scripts/sld.py` | Gera os estilos SLD a partir das faixas das legendas |
| `scripts/setor_censitario_raiz.sql` | Cria a raiz de nível 1 do Setor Censitário e o põe em primeiro na home |
| `static/js/mapa.js` | Mapa (OpenLayers): árvore, filtros, legenda, hover, downloads |
| `templates/` | Páginas (Jinja) |
| `Dockerfile`, `docker-compose.yml` | Deploy com Docker |

## Configuração (`.env`)

Copie o `.env.example` para `.env` e preencha as senhas. O `.env` não vai para
o Git nem para a imagem Docker.

| Variável | Para quê |
|---|---|
| `ADAPTABRASIL_DB_*` | Conexão com o PostgreSQL |
| `ADAPTABRASIL_GEOSERVER_URL`, `_USER`, `_PASSWORD` | API REST do GeoServer, usada só pelo `configurar_geoserver.py` |
| `ADAPTABRASIL_GEOSERVER_PUBLIC_URL` | Endereço do GeoServer que o navegador usa para os mapas |
| `ADAPTABRASIL_GEOSERVER_WORKSPACE`, `_DATASTORE`, `_LAYER` | Nomes no GeoServer |
| `APP_PORTA` | Porta do servidor onde o app atende no Docker (padrão 5000) |

## Desenvolvimento (venv)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip
FLASK_DEBUG=1 .venv/Scripts/python app.py          # http://127.0.0.1:5000
```

Com `FLASK_DEBUG=1` o app só escuta em localhost e recarrega sozinho ao salvar
um `.py`, exceto quando roda sob o depurador do PyCharm (o recarregador faria o
depurador parar a cada mudança).

No PyCharm há duas configurações prontas: **App (Flask)** e **Configurar
GeoServer**.

### Publicar os estilos no GeoServer

```bash
python scripts/configurar_geoserver.py --simular   # só grava os XML em scripts/saida_geoserver
python scripts/configurar_geoserver.py             # aplica no GeoServer
```

Se o `ADAPTABRASIL_GEOSERVER_URL` do `.env` usa um endereço que só vale de
dentro do servidor (por exemplo, `localhost`), troque o endereço só nessa
execução para rodar da sua máquina:

```bash
ADAPTABRASIL_GEOSERVER_URL=http://<servidor-geoserver>:8080/geoserver python scripts/configurar_geoserver.py
```

## Deploy com Docker

A imagem roda só o app Flask, com o gunicorn (2 processos × 8 threads). O
GeoServer e o banco continuam onde estão. O desenvolvimento continua no venv;
o Docker é para o servidor.

### Num servidor Linux

Pré-requisitos: Git, Docker com o plugin Compose (`docker compose version`),
acesso do servidor ao PostgreSQL e ao GeoServer, e um usuário no grupo
`docker`.

Primeira vez:

```bash
git clone https://github.com/AdaptaBrasil/adaptabrasil_geoserver.git
cd adaptabrasil_geoserver
cp .env.example .env            # preencha os endereços e as senhas
docker compose up -d --build
```

Libere a porta do app (`APP_PORTA`, padrão 5000) no firewall do servidor
(por exemplo, `sudo ufw allow 5000/tcp`) e, se houver, no firewall do provedor
de nuvem. O app fica em `http://<servidor>:5000`. Para servir em HTTPS ou na
porta 80, ponha um proxy reverso (nginx, Caddy) na frente da porta do app.

### Atualizar depois de novos commits

Na pasta do clone:

```bash
git pull
docker compose up -d --build
```

### Comandos do dia a dia

```bash
docker compose ps                  # está rodando?
docker compose logs -f app         # logs (Ctrl+C sai)
docker compose restart app         # reiniciar (para só reler o banco, use o /reload)
docker compose down                # parar e remover o contêiner
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/   # 200 = ok
```

O contêiner reinicia sozinho se cair ou se o servidor reiniciar
(`restart: unless-stopped`).

### Recarregar os dados do banco (`/reload`)

O app guarda em memória o que lê do banco: indicadores, hierarquia, setores da
home, legendas, estados, municípios e limites. Uma mudança no banco (por
exemplo, em `sep.order_by` ou um `REFRESH MATERIALIZED VIEW mv_hierarchy`) só
aparece no app depois de recarregar esses dados. O `/reload` faz isso sem
reiniciar o contêiner.

Ele só atende pedidos do próprio servidor. Depois de cada mudança no banco,
entre no servidor (SSH) e rode:

```bash
curl -X POST http://localhost:5000/reload     # use a APP_PORTA, se não for 5000
```

A resposta é `{"recarregado": true}`. De qualquer outra máquina, o `/reload`
responde 403. Na sua máquina, com o app rodando no PyCharm, também funciona
(`http://127.0.0.1:5000/reload`).

Como o app sabe que o pedido é do servidor: no Docker, um `curl localhost`
rodado no servidor chega ao contêiner com o IP do host (o gateway do
contêiner), e é esse IP, além de 127.0.0.1, que o `/reload` aceita. Se houver
um proxy reverso (nginx, Caddy) na frente do app, todo pedido de fora também
chegaria do host; por isso pedidos com `X-Forwarded-For`, `X-Real-IP` ou
`Forwarded` são recusados. Configure o proxy para mandar um desses cabeçalhos
(o Caddy já manda; no nginx, `proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for;`) ou para bloquear o caminho `/reload`.

O gunicorn roda 2 processos, cada um com o seu cache, e o `/reload` chega a só
um deles. Por isso ele também grava um arquivo-marca no diretório temporário do
contêiner; os outros processos veem a marca na requisição seguinte e
recarregam também. O próximo acesso a cada página fica um pouco mais lento,
porque relê o banco.

### Testar a imagem na sua máquina

Com o Docker Desktop aberto:

```bash
APP_PORTA=5056 docker compose up -d --build    # http://127.0.0.1:5056
docker compose down
```

### Se o contêiner não alcançar o banco

Dentro do contêiner, `localhost` é o próprio contêiner, e não o servidor. Se o
banco roda no mesmo servidor, não use `localhost` no `.env`: use o IP do
servidor ou o endereço do host:

```
# .env
ADAPTABRASIL_DB_HOST=host.docker.internal
```

```yaml
# docker-compose.yml, dentro de app:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

## O que o app precisa do GeoServer

Vale para qualquer GeoServer (testado com o 2.28). Antes de rodar o
`configurar_geoserver.py`:

1. **Workspace e datastore**: o script cria as layers e os estilos, mas não o
   workspace nem o datastore. Crie o workspace `adaptabrasil` e, nele, um
   datastore PostGIS `adaptabrasil` apontando para o banco do `.env`, schema
   `adaptabrasil_aluana`, com *Expose primary keys* desligado. Os nomes podem
   ser outros, desde que batam com `ADAPTABRASIL_GEOSERVER_WORKSPACE` e
   `_DATASTORE`. O servidor do GeoServer precisa alcançar o PostgreSQL.
2. **CORS**: o popup do hover pede o GetFeatureInfo ao GeoServer direto do
   navegador, a partir do endereço do app. Libere CORS no GeoServer para a
   origem do app (no `web.xml` da aplicação). Sem isso o mapa carrega, mas o
   popup não aparece, e o erro só se vê no console do navegador.
3. **HTTPS**: se o app for servido em HTTPS, o
   `ADAPTABRASIL_GEOSERVER_PUBLIC_URL` também precisa ser HTTPS; senão o
   navegador bloqueia os mapas.
4. **Formatos do WFS**: os downloads usam WFS com `outputFormat` `csv` e
   `SHAPE-ZIP`, que vêm ligados por padrão.

Depois, rode o `configurar_geoserver.py` (ver
[Publicar os estilos no GeoServer](#publicar-os-estilos-no-geoserver)) e
aponte o `ADAPTABRASIL_GEOSERVER_PUBLIC_URL` do app para o novo GeoServer.

## O que o app precisa do banco

PostgreSQL com PostGIS (hoje: PostgreSQL 16 e PostGIS 3.4, a extensão no
schema `public`). Os dados ficam no schema `adaptabrasil_aluana` (o nome vem de
`ADAPTABRASIL_DB_SCHEMA`), cujo dono é o usuário do app, `adaptabrasil_user`.
As geometrias estão em EPSG:4326. O app e o GeoServer precisam alcançar o
banco.

O que o app e a layer `indicador` leem:

| Objeto | Tipo | Para quê |
|---|---|---|
| `value` | tabela (~3 GB) | Valores dos indicadores; a layer usa o índice `value_unique` |
| `geoobject` | tabela (~2 GB) | Geometrias e nomes (municípios, setores, portos, rodovias, ferrovias) |
| `indicator`, `indicator_indicator`, `sep`, `scenario`, `legend_items`, `geoobjecttype`, `image` | tabelas pequenas | Árvore, setores da home, cenários, legendas |
| `state`, `county` | materialized views (de `geoobject`) | Filtros de estado e município, enquadramento do mapa |
| `mv_indiclevelyears`, `mv_hierarchy` | materialized views | Anos de cada indicador e a árvore; `mv_hierarchy` depende de `mv_indiclevelyears` |

### Migrar o banco

O schema tem ~42 GB, mas a maior parte não é usada pelo app: a materialized
view `geovalue` (27 GB), as tabelas `valores`, `valores2` e `contribution` e a
materialized view `census_track` (~7 GB juntas). Combine com quem cuida dos
dados se elas vão junto; o app precisa só dos objetos da tabela acima (~5 GB).

Cópia do schema inteiro:

```bash
# na origem
pg_dump -Fc -n adaptabrasil_aluana --no-owner --no-privileges \
  -h <host-origem> -p <porta> -U adaptabrasil_user -d adaptabrasil -f adaptabrasil_aluana.dump

# no destino: banco criado, CREATE EXTENSION postgis; e o usuário do app criado
pg_restore --no-owner --role=adaptabrasil_user \
  -h <host-destino> -p <porta> -U adaptabrasil_user -d adaptabrasil adaptabrasil_aluana.dump
```

O `pg_restore` recalcula as materialized views que tinham dados; a
`geovalue` é a que mais demora. Se alguma das usadas pelo app ficar vazia,
recalcule nesta ordem (não use a função `refreshallmaterializedviews()` do
schema: ela recalcula todas, a `geovalue` inclusive, e em ordem alfabética,
com a `mv_hierarchy` antes da `mv_indiclevelyears` de que ela depende):

```sql
REFRESH MATERIALIZED VIEW adaptabrasil_aluana.state;
REFRESH MATERIALIZED VIEW adaptabrasil_aluana.county;
REFRESH MATERIALIZED VIEW adaptabrasil_aluana.mv_indiclevelyears;
REFRESH MATERIALIZED VIEW adaptabrasil_aluana.mv_hierarchy;
```

O `scripts/setor_censitario_raiz.sql` já está aplicado nos dados e vai junto
na cópia.

Depois da cópia, aponte para o banco novo:

1. o `.env` do app (`ADAPTABRASIL_DB_*`) e reinicie o app;
2. o datastore `adaptabrasil` no GeoServer (host, porta, banco, schema,
   usuário e senha);
3. se o nome do schema mudar, rode de novo o `configurar_geoserver.py`,
   que grava o nome do schema no SQL da layer `indicador`.

## GeoServer no servidor atual

Esta seção descreve o servidor onde o app roda hoje; num GeoServer
administrado por outra equipe, vale a seção
[O que o app precisa do GeoServer](#o-que-o-app-precisa-do-geoserver).

Nesse servidor, o GeoServer (2.28, com o Jetty que vem no pacote binário) roda
fora do Docker, como serviço do systemd, com o usuário `ubuntu`:

| O quê | Onde |
|---|---|
| Instalação (`GEOSERVER_HOME`) | `~/inpe/geoserver` |
| Pasta de dados (`GEOSERVER_DATA_DIR`): workspace, layers, estilos, conexão com o banco | `~/inpe/geoserver/data_dir` |
| Serviço | `/etc/systemd/system/geoserver.service` |
| Variáveis para rodar à mão | `~/.profile` |
| Porta | 8080 (`http://<servidor-geoserver>:8080/geoserver`) |

```bash
sudo systemctl status geoserver        # está rodando?
sudo systemctl restart geoserver       # reiniciar (leva uns 10 s para voltar)
sudo journalctl -u geoserver -f        # logs (Ctrl+C sai)
```

Para mudar a instalação de pasta: pare o serviço, mova a pasta e troque o
caminho no `geoserver.service` (`WorkingDirectory`, `GEOSERVER_HOME` e
`ExecStart`) e no `~/.profile`; depois `sudo systemctl daemon-reload` e
`sudo systemctl start geoserver`. A configuração dentro da `data_dir` não tem
caminhos absolutos.

Depois de reiniciar, confira se o mapa sai como imagem, e não como XML de erro:

```bash
curl -s -o /dev/null -w "%{content_type}\n" \
  "http://localhost:8080/geoserver/adaptabrasil/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=adaptabrasil:mapa_cinza&STYLES=&SRS=EPSG:4326&BBOX=-74,-34,-28,6&WIDTH=200&HEIGHT=175&FORMAT=image/png"
# image/png = ok
```

Se vier `application/vnd.ogc.se_xml` com `No code "EPSG:4326"`, o GeoServer não
conseguiu abrir o banco de projeções que o GeoTools extrai em
`/tmp/GeoTools`. Isso acontece quando essa pasta foi criada pelo `root` (por
exemplo, num GeoServer iniciado com `sudo`). Corrija o dono e reinicie:

```bash
sudo chown -R ubuntu:ubuntu /tmp/GeoTools
sudo systemctl restart geoserver
```

## Observações

- Indicadores, hierarquia e legendas ficam em cache na memória do app. Depois
  de mudar o banco ou de um `REFRESH MATERIALIZED VIEW mv_hierarchy`, chame o
  [`/reload`](#recarregar-os-dados-do-banco-reload) ou reinicie o app.
- Na árvore, os indicadores de cada nível aparecem em ordem alfabética; os
  setores da página inicial seguem a ordem do sistema oficial (`sep.order_by`).
