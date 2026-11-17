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
docker compose restart app         # reiniciar (por exemplo, depois de um REFRESH da mv_hierarchy)
docker compose down                # parar e remover o contêiner
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/   # 200 = ok
```

O contêiner reinicia sozinho se cair ou se o servidor reiniciar
(`restart: unless-stopped`).

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

## Observações

- Indicadores, hierarquia e legendas ficam em cache na memória do app. Depois
  de um `REFRESH MATERIALIZED VIEW mv_hierarchy`, reinicie o app.
- Na árvore, os indicadores de cada nível aparecem em ordem alfabética; os
  setores da página inicial seguem a ordem do sistema oficial (`sep.order_by`).
