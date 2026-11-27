# PR #1: GeoServer parametrizado, no modelo da Sala de Situação do INPE
Mergeado em 2026-11-15T17:21:37Z · commit de merge 120b616cfc4b87c0ff5639af7894ae6386baed98
Original: https://github.com/AluanaCristine/adaptabrasil_geoserver/pull/1

## Resumo

Troca o modelo de "uma view no Postgres e uma layer no GeoServer para cada combinação de indicador × cenário × ano" (1.034 layers) por **uma única layer parametrizada**, como faz a [Sala de Situação do INPE](https://terrabrasilis.dpi.inpe.br/ams/) ([código](https://github.com/terrabrasilis/ams)).

O navegador escolhe o recorte em cada requisição WMS:

```
LAYERS=adaptabrasil:indicador
VIEWPARAMS=indicador:2;ano:2020;cenario:0     (cenario 0 = sem cenário, o presente)
STYLES=adaptabrasil_legenda_2
```

## O que mudou

**GeoServer** (`scripts/configurar_geoserver.py`, `scripts/sld.py`)
- `adaptabrasil:indicador`: SQL view do GeoServer sobre `value` + `geoobject`, com os parâmetros `indicador`, `ano` e `cenario` validados por regex (só dígitos). Usa o índice `value_unique`: cerca de 45 ms por recorte.
- Um estilo por legenda da tabela `legend_items` (13 estilos `adaptabrasil_legenda_*`), em vez do `CASE` fixo. Corrige as cores dos indicadores da legenda 1, que tem a escala invertida.
- `mapa_cinza` (fundo) virou SQL view dos municípios da `geoobject`. Antes lia uma das views antigas.
- O script pode ser rodado de novo quando as legendas mudarem. `--simular` só gera os XML.

**App**
- A barra lateral do mapa é montada a partir do banco, e não mais do HTML fixo. A hierarquia vem da materialized view `mv_hierarchy`.
- API nova: `/api/arvore/<raiz>` e `/api/indicadores/<id>` (anos, cenários e itens da legenda).
- `templates/mapa.html` e `static/js/mapa.js`: seletores de ano e cenário, legenda, valor no clique (GetFeatureInfo) e download em CSV e shapefile (WFS).
- URL pública do GeoServer vem do `.env` (`ADAPTABRASIL_GEOSERVER_PUBLIC_URL`), em vez de fixa nos templates.
- `app.run` lê `FLASK_DEBUG`; em debug escuta só em `127.0.0.1`.

**Removido**
- `criador_de_views_maps.py` e `publicador_de_views_maps.py`, e as run configurations deles.
- `scripts/limpar_legado.py` remove as views e layers `vw_st_*`, a tabela `views_adaptabrasil` e os estilos `adaptabrasil_point/_line/_polygon`, gravando backup antes.

**Setores, filtros e rodapé** (commit `c47b8c0`)
- Home: os setores estratégicos vêm do banco (filhos de master = 0) em vez de uma lista fixa; antes, os ícones abriam todos o mesmo mapa cinza. Entram também Biodiversidade, Agricultura Familiar (`sep.visible = false`) e Setor Censitário (indicadores sem pai, sob a raiz virtual 110000), com três ícones novos no padrão dos existentes. São 11 setores.
- Mapa: filtros **Estado** (padrão Brasil) e **Município** (habilitado ao escolher um estado), com listas das views `state` e `county`. A layer `indicador` ganhou os parâmetros `estado` e `municipio` (0 = todos). Municípios e setores censitários usam `state_id`/`county_id`; portos, rodovias e ferrovias usam a sigla (`geoobject.state`) e a geometria do município (portos com tolerância de ~5 km, por causa de Ilhéus). O mapa enquadra a área escolhida. API nova: `/api/estados`, `/api/estados/<id>/municipios` e `/api/limites`.
- Rodapé com barra de progresso verde e o tempo de carregamento do mapa.
- Polígonos sem linha de divisa: `stroke-width` 0 virava um traço de 1 px; agora o contorno tem a cor do preenchimento. O estilo `mapa_cinza` passa a ser gerado pelo script.
- Pool de conexões com o banco: abrir uma conexão remota levava ~1 s por requisição.

## Já aplicado no ambiente

- **GeoServer** (`<servidor-geoserver>:8080`): layer `indicador`, os 13 estilos e o `mapa_cinza` refeito já estão no ar. As 1.034 layers `vw_st_*` e os 3 estilos antigos foram removidos.
- **Banco** (`adaptabrasil_aluana`): as 1.034 views `vw_st_*` e a tabela `views_adaptabrasil` foram removidas. Há backup local (SQL das views e XML das layers).
- **GeoServer, depois do commit `c47b8c0`**: estilos sem linhas e layer `indicador` com os parâmetros `estado` e `municipio` já no ar.
- **Views `state` e `county`** (materializadas): criadas no banco, usadas pelos filtros.
- **`mv_indiclevelyears` e `mv_hierarchy`**: estavam sem dados nesse schema e foram populadas com `REFRESH MATERIALIZED VIEW`. Depois de carregar indicadores novos, é preciso dar refresh nas duas e reiniciar o app.

## Para colocar no servidor

1. Atualizar o código.
2. Acrescentar ao `.env` as linhas `ADAPTABRASIL_GEOSERVER_PUBLIC_URL` e `ADAPTABRASIL_GEOSERVER_LAYER` (ver `.env.example`).
3. Não definir `FLASK_DEBUG` em produção.

## Testes

- WMS renderizado para polígonos (municípios), linhas (ferrovias) e pontos (portos), com e sem cenário.
- `VIEWPARAMS` com SQL injetado (`cenario:0 OR 1=1`) é recusado pelo GeoServer.
- No navegador: árvore carregada, troca de ano e cenário, legenda e valor no clique, sem erros no console.
- Rotas e API testadas com o banco real; download em CSV conferido.
- Os 11 setores testados de ponta a ponta (árvore, WFS e WMS).
- Filtros: contagens por WFS iguais às do SQL (ex.: Bahia → portos Aratu, Ilhéus e Salvador; Campinas → 4 trechos de rodovia, 9 de ferrovia, 2.592 setores censitários). No navegador: Bahia, Salvador, Ilhéus e volta a Brasil, com o tempo no rodapé (~2,6 s para um município).

🤖 Generated with [Claude Code](https://claude.com/claude-code)



# PR #2: Mapa: hover, fundo de satélite, divisas por zoom e deploy com Docker
Mergeado em 2026-11-16T00:34:39Z · commit de merge 18b38795c4a34c3c30eb6876d01213be0bc5ec8b
Original: https://github.com/AluanaCristine/adaptabrasil_geoserver/pull/2

## O que muda

**Mapa**
- **Popup no hover**, como no webtests: o polígono sob o mouse ganha contorno escuro e um popup mostra o nome, o município com a sigla do estado e o valor, com a cor da faixa da legenda. Usa GetFeatureInfo do GeoServer e a nova rota `/api/geoobjetos/<id>`. Um toque também abre o popup. Sai o painel de valor no clique.
- **Fundo de satélite** (Esri World Imagery) no mapa e na página inicial, no lugar do fundo cinza; a layer do indicador fica com opacidade 0,78.
- **Brasil inteiro na abertura**: o mapa enquadra o país pelo tamanho real da tela, em vez de um zoom fixo que cortava o país em telas largas.
- **Divisas entre polígonos** finas e cinza-claras, só do zoom de estado em diante (abaixo de 1:10.000.000). Na visão do país, as linhas viravam uma mancha cinza.
- **Árvore de indicadores em ordem alfabética** em todos os níveis. Os setores da página inicial seguem a ordem oficial.

**Deploy e desenvolvimento**
- **Docker** para o deploy: `Dockerfile` (Python 3.13, gunicorn, sem root), `docker-compose.yml` (lê o `.env`, porta `APP_PORTA`, padrão 5000) e `.dockerignore`. O GeoServer continua fora do Docker.
- **README** com a arquitetura, o desenvolvimento e o passo a passo do deploy.
- Variáveis de ambiente ignoram espaços sobrando (uma URL colada com espaço no fim gerava 404 no GeoServer).
- O recarregador do Flask fica desligado sob o depurador do PyCharm, que parava a cada mudança num `.py`.

## Testes
- Hover, satélite e enquadramento conferidos no navegador, numa cópia local do app.
- Estilos publicados no GeoServer com o `configurar_geoserver.py` e conferidos no servidor (GetStyles).
- Imagem Docker gerada e testada localmente; o contêiner já roda no servidor da AWS, em `~/inpe/aluana_ic/app_adaptabrasil`.

## Depois do merge
No servidor, voltar a pasta para o `main` e atualizar:
```bash
cd ~/inpe/aluana_ic/app_adaptabrasil
git checkout main && git pull
docker compose up -d --build
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)


