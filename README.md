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
   └──────────► GeoServer (3.224.52.81:8080, fora do Docker)
                imagens do mapa (WMS), hover (GetFeatureInfo),
                downloads em CSV e shapefile (WFS)
```

- O **app** consulta o banco e entrega as páginas; o endereço público do
  GeoServer vai para o navegador, que pede os mapas direto a ele.
- O **GeoServer** roda no servidor da AWS, fora do Docker, e guarda a
  configuração (layers e estilos) na pasta de dados dele.
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

O `.env` aponta o GeoServer para `localhost:8081`, que só existe de dentro do
servidor. Para rodar da sua máquina, troque o endereço só nessa execução:

```bash
ADAPTABRASIL_GEOSERVER_URL=http://3.224.52.81:8080/geoserver python scripts/configurar_geoserver.py
```

## Deploy com Docker

A imagem roda só o app Flask, com o gunicorn (2 processos × 8 threads). O
GeoServer e o banco continuam onde estão. O desenvolvimento continua no venv;
o Docker é para o servidor.

### No servidor da AWS (3.224.52.81)

O app fica em `~/inpe/aluana_ic/app_adaptabrasil`, um clone deste
repositório. Primeira vez:

```bash
cd ~/inpe/aluana_ic/app_adaptabrasil
git checkout geoserver-parametrizado
cp .env.example .env            # preencha as senhas
docker compose up -d --build
```

Libere a porta (`APP_PORTA`, padrão 5000) no Security Group da instância
(EC2 → Security → Inbound rules). O app fica em `http://3.224.52.81:5000`.

### Atualizar depois de novos commits

```bash
cd ~/inpe/aluana_ic/app_adaptabrasil
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

Dentro do contêiner, `localhost` é o próprio contêiner. O `.env` usa o IP
público do banco, o que costuma funcionar. Se o firewall bloquear o servidor
de acessar o próprio IP público, use o endereço do host:

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
