"""
Configura o GeoServer no modelo parametrizado (como a Sala de Situação do INPE).

Em vez de uma view no Postgres e uma layer publicada para cada combinação de
indicador, cenário e ano, o GeoServer passa a ter:

  - uma única layer (config.GEOSERVER_LAYER), que é uma SQL view do GeoServer
    com os parâmetros indicador, ano e cenario. O navegador escolhe o recorte
    em cada requisição, com VIEWPARAMS=indicador:2;ano:2020;cenario:0;
  - um estilo por legenda da tabela legend_items
    (config.GEOSERVER_PREFIXO_ESTILO + id), escolhido com STYLES=;
  - a layer de fundo (config.GEOSERVER_LAYER_FUNDO), também uma SQL view,
    com os municípios da tabela geoobject, e o seu estilo cinza
    (config.GEOSERVER_ESTILO_FUNDO).

Os polígonos não têm linha de divisa (ver sld._poligono_sem_divisa).

Cenário 0 significa "sem cenário" (scenario_id nulo, o dado do presente).

O script pode ser executado de novo sempre que as legendas mudarem: ele cria
o que falta e atualiza o que já existe.

Uso:
    python scripts/configurar_geoserver.py            # aplica no GeoServer
    python scripts/configurar_geoserver.py --simular  # só grava os XML em scripts/saida_geoserver
"""
import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import psycopg2
import requests
from requests.auth import HTTPBasicAuth

import config
import sld

GEOSERVER = config.geoserver_config()
REST = GEOSERVER["url"].rstrip("/") + "/rest"
AUTH = HTTPBasicAuth(GEOSERVER["user"], GEOSERVER["password"])
WORKSPACE = GEOSERVER["workspace"]
DATASTORE = GEOSERVER["datastore"]
LAYER = config.GEOSERVER_LAYER
LAYER_FUNDO = config.GEOSERVER_LAYER_FUNDO
SCHEMA = config.DB_SCHEMA

PASTA_SIMULACAO = Path(__file__).resolve().parent / "saida_geoserver"

# Recorte do Brasil (ST_Extent da tabela geoobject), em EPSG:4326
BBOX = {"minx": -74.0, "miny": -33.76, "maxx": -28.83, "maxy": 5.28}

# Parâmetros da SQL view: nome, valor padrão e validação.
# A validação só aceita dígitos: os valores entram direto no SQL.
PARAMETROS = [
    ("indicador", "2", r"^\d+$"),
    ("ano", "2020", r"^\d+$"),
    ("cenario", "0", r"^\d+$"),
    ("estado", "0", r"^\d+$"),
    ("municipio", "0", r"^\d+$"),
]

# Filtros de área (0 = todos), com os ids das views state e county:
#   - estado: municípios e setores censitários têm state_id; portos, rodovias
#     e ferrovias têm só a sigla na coluna state (o state_id dos portos usa
#     outra numeração);
#   - municipio: municípios (county_id = o próprio id) e setores têm county_id;
#     portos, rodovias e ferrovias (geoobjecttype 6, 7 e 8) são filtrados pela
#     geometria do município, e só quando o indicador é de um desses tipos.
#     Pontos aceitam até 0,05 grau (~5 km), porque há portos no mar, fora do
#     polígono (Ilhéus). O filtro vira uma lista de ids calculada uma vez, com
#     um pré-filtro pelo retângulo do município (&&): escrito como OR na linha,
#     o Postgres testava a geometria de ~10 mil objetos e acionava o JIT,
#     levando de 0,7 a 3 s em vez de ~0,15 s.
#
# %cenario% = 0 seleciona o dado sem cenário. Depois da substituição os
# termos viram constantes e o Postgres usa o índice value_unique nos dois casos.
SQL_VIEW = f"""SELECT
    v.geoobject_id,
    g.name,
    g.geom,
    v.value
FROM {SCHEMA}.value v
JOIN {SCHEMA}.geoobject g ON g.id = v.geoobject_id
WHERE v.indicator_id = %indicador%
  AND v.year = %ano%
  AND (v.scenario_id = %cenario% OR (%cenario% = 0 AND v.scenario_id IS NULL))
  AND (%estado% = 0 OR g.state_id = %estado%
       OR g.state = (SELECT s.state FROM {SCHEMA}.state s WHERE s.id = %estado%))
  AND (%municipio% = 0 OR v.geoobject_id IN (
        SELECT o.id FROM {SCHEMA}.geoobject o WHERE o.county_id = %municipio%
        UNION ALL
        SELECT o.id FROM {SCHEMA}.county c
        JOIN {SCHEMA}.geoobject o
          ON o.geoobjecttype_id IN (6, 7, 8) AND o.geom && ST_Expand(c.geom, 0.05)
        WHERE c.id = %municipio%
          AND EXISTS (SELECT 1 FROM {SCHEMA}.indicator i
                      WHERE i.id = %indicador% AND i.geoobjecttype_id IN (6, 7, 8))
          AND ST_DWithin(c.geom, o.geom, CASE WHEN o.geoobjecttype_id = 6 THEN 0.05 ELSE 0 END)))"""

# Fundo: os municípios (geoobjecttype_id = 1), sem parâmetros
SQL_FUNDO = f"""SELECT g.id, g.name, g.geom
FROM {SCHEMA}.geoobject g
WHERE g.geoobjecttype_id = 1"""


# =====================================
# XML DAS LAYERS
# =====================================

def _bbox_xml(tag):
    coords = "".join(f"<{k}>{v}</{k}>" for k, v in BBOX.items())
    return f"<{tag}>{coords}<crs>EPSG:4326</crs></{tag}>"


def featuretype_xml(nome, titulo, resumo, sql, chave, parametros=()):
    """FeatureType de uma SQL view do GeoServer (JDBC_VIRTUAL_TABLE)."""
    params = "".join(
        "<parameter>"
        f"<name>{p}</name><defaultValue>{padrao}</defaultValue>"
        f"<regexpValidator>{escape(regex)}</regexpValidator>"
        "</parameter>"
        for p, padrao, regex in parametros
    )
    return f"""<featureType>
  <name>{nome}</name>
  <nativeName>{nome}</nativeName>
  <title>{escape(titulo)}</title>
  <abstract>{escape(resumo)}</abstract>
  <srs>EPSG:4326</srs>
  <projectionPolicy>FORCE_DECLARED</projectionPolicy>
  {_bbox_xml("nativeBoundingBox")}
  {_bbox_xml("latLonBoundingBox")}
  <enabled>true</enabled>
  <metadata>
    <entry key="JDBC_VIRTUAL_TABLE">
      <virtualTable>
        <name>{nome}</name>
        <sql>{escape(sql)}</sql>
        <escapeSql>false</escapeSql>
        <keyColumn>{chave}</keyColumn>
        <geometry><name>geom</name><type>Geometry</type><srid>4326</srid></geometry>
        {params}
      </virtualTable>
    </entry>
  </metadata>
</featureType>"""


def featuretype_indicador():
    return featuretype_xml(
        LAYER, "Indicadores AdaptaBrasil",
        "Valor de um indicador por geoobjeto. Parâmetros: indicador, ano, cenario (0 = sem cenário), "
        "estado e municipio (0 = todos).",
        SQL_VIEW, "geoobject_id", PARAMETROS,
    )


def featuretype_fundo():
    return featuretype_xml(LAYER_FUNDO, "Municípios (fundo)", "Municípios do Brasil, fundo cinza do mapa.",
                           SQL_FUNDO, "id")


def layer_xml(padrao, estilos=()):
    outros = "".join(
        f"<style><name>{e}</name><workspace>{WORKSPACE}</workspace></style>" for e in estilos
    )
    return (
        "<layer>"
        f"<defaultStyle><name>{padrao}</name><workspace>{WORKSPACE}</workspace></defaultStyle>"
        f"<styles>{outros}</styles>"
        "</layer>"
    )


# =====================================
# BANCO
# =====================================

def buscar_legendas():
    """Devolve {legend_id: [itens]} da tabela legend_items."""
    legendas = {}
    with psycopg2.connect(**config.db_config()) as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT legend_id, label, color, minvalue, maxvalue
            FROM {SCHEMA}.legend_items
            ORDER BY legend_id, "order"
        """)
        for legend_id, label, color, minvalue, maxvalue in cur.fetchall():
            legendas.setdefault(legend_id, []).append(
                {"label": label, "color": color, "minvalue": minvalue, "maxvalue": maxvalue}
            )
    return legendas


# =====================================
# GEOSERVER (REST)
# =====================================

def _existe(caminho):
    return requests.get(f"{REST}/{caminho}", auth=AUTH, timeout=30).status_code == 200


def _enviar(metodo, caminho, corpo, tipo, params=None):
    resposta = requests.request(
        metodo, f"{REST}/{caminho}", data=corpo.encode("utf-8"), auth=AUTH,
        headers={"Content-Type": tipo}, params=params, timeout=120,
    )
    if resposta.status_code not in (200, 201):
        raise RuntimeError(f"{metodo} {caminho}: {resposta.status_code} {resposta.text[:500]}")


def salvar_estilo(nome, conteudo_sld):
    base = f"workspaces/{WORKSPACE}/styles"
    tipo = "application/vnd.ogc.sld+xml"
    if _existe(f"{base}/{nome}.json"):
        _enviar("PUT", f"{base}/{nome}", conteudo_sld, tipo)
        print(f"Estilo atualizado: {nome}")
    else:
        _enviar("POST", base, conteudo_sld, tipo, params={"name": nome})
        print(f"Estilo criado: {nome}")


def _eh_sql_view(caminho):
    resposta = requests.get(f"{REST}/{caminho}.json", auth=AUTH, timeout=30)
    return "JDBC_VIRTUAL_TABLE" in resposta.text


def salvar_featuretype(nome, xml):
    base = f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes"
    caminho = f"{base}/{nome}"

    if _existe(f"{caminho}.json") and not _eh_sql_view(caminho):
        # Layer antiga publicada a partir de uma tabela ou view do banco
        # (era o caso do mapa_cinza). O GeoServer não troca a origem de uma
        # layer existente, então ela é removida e criada de novo, com o mesmo nome.
        resposta = requests.delete(f"{REST}/{caminho}", auth=AUTH, params={"recurse": "true"}, timeout=120)
        if resposta.status_code != 200:
            raise RuntimeError(f"DELETE {caminho}: {resposta.status_code} {resposta.text[:500]}")
        print(f"Layer antiga removida para ser recriada como SQL view: {WORKSPACE}:{nome}")

    if _existe(f"{caminho}.json"):
        # recalculate atualiza os atributos se o SQL mudou
        _enviar("PUT", caminho, xml, "text/xml", params={"recalculate": "nativebbox,latlonbbox"})
        print(f"Layer atualizada: {WORKSPACE}:{nome}")
    else:
        _enviar("POST", base, xml, "text/xml")
        print(f"Layer criada: {WORKSPACE}:{nome}")


def salvar_layers(estilos):
    salvar_featuretype(LAYER, featuretype_indicador())
    padrao = f"{config.GEOSERVER_PREFIXO_ESTILO}{config.LEGENDA_PADRAO}"
    _enviar("PUT", f"layers/{WORKSPACE}:{LAYER}", layer_xml(padrao, estilos), "text/xml")
    print(f"Estilos associados à layer {LAYER}: {len(estilos)}")

    salvar_featuretype(LAYER_FUNDO, featuretype_fundo())
    _enviar("PUT", f"layers/{WORKSPACE}:{LAYER_FUNDO}", layer_xml(config.GEOSERVER_ESTILO_FUNDO), "text/xml")
    print(f"Estilo {config.GEOSERVER_ESTILO_FUNDO} associado à layer {LAYER_FUNDO}")


# =====================================
# PRINCIPAL
# =====================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--simular", action="store_true",
                        help=f"não altera o GeoServer, só grava os XML em {PASTA_SIMULACAO}")
    args = parser.parse_args()

    legendas = buscar_legendas()
    if config.LEGENDA_PADRAO not in legendas:
        sys.exit(f"A legenda padrão {config.LEGENDA_PADRAO} não existe em legend_items.")

    estilos = {f"{config.GEOSERVER_PREFIXO_ESTILO}{lid}": sld.gerar_sld(f"{config.GEOSERVER_PREFIXO_ESTILO}{lid}", itens)
               for lid, itens in legendas.items()}
    estilo_fundo = sld.gerar_sld_fundo(config.GEOSERVER_ESTILO_FUNDO)

    if args.simular:
        PASTA_SIMULACAO.mkdir(exist_ok=True)
        for nome, conteudo in estilos.items():
            (PASTA_SIMULACAO / f"{nome}.sld").write_text(conteudo, encoding="utf-8")
        (PASTA_SIMULACAO / f"{config.GEOSERVER_ESTILO_FUNDO}.sld").write_text(estilo_fundo, encoding="utf-8")
        (PASTA_SIMULACAO / f"{LAYER}_featuretype.xml").write_text(featuretype_indicador(), encoding="utf-8")
        (PASTA_SIMULACAO / f"{LAYER_FUNDO}_featuretype.xml").write_text(featuretype_fundo(), encoding="utf-8")
        print(f"{len(estilos)} estilos e as layers {LAYER} e {LAYER_FUNDO} gravados em {PASTA_SIMULACAO}")
        return

    print(f"GeoServer: {REST} (workspace {WORKSPACE}, datastore {DATASTORE})")
    salvar_estilo(config.GEOSERVER_ESTILO_FUNDO, estilo_fundo)
    for nome, conteudo in estilos.items():
        salvar_estilo(nome, conteudo)
    salvar_layers(list(estilos))
    print("GeoServer configurado.")


if __name__ == "__main__":
    main()
