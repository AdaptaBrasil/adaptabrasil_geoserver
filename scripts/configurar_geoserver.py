"""
Configura o GeoServer no modelo parametrizado (como a Sala de Situação do INPE).

Em vez de uma view no Postgres e uma layer publicada para cada combinação de
indicador, cenário e ano, o GeoServer passa a ter:

  - uma única layer (config.GEOSERVER_LAYER), que é uma SQL view do GeoServer
    com os parâmetros indicador, ano e cenario. O navegador escolhe o recorte
    em cada requisição, com VIEWPARAMS=indicador:2;ano:2020;cenario:0;
  - um estilo por legenda da tabela legend_items
    (config.GEOSERVER_PREFIXO_ESTILO + id), escolhido com STYLES=.

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
]

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
  AND (v.scenario_id = %cenario% OR (%cenario% = 0 AND v.scenario_id IS NULL))"""


# =====================================
# XML DA LAYER
# =====================================

def _bbox_xml(tag):
    coords = "".join(f"<{k}>{v}</{k}>" for k, v in BBOX.items())
    return f"<{tag}>{coords}<crs>EPSG:4326</crs></{tag}>"


def featuretype_xml():
    parametros = "".join(
        "<parameter>"
        f"<name>{nome}</name><defaultValue>{padrao}</defaultValue>"
        f"<regexpValidator>{escape(regex)}</regexpValidator>"
        "</parameter>"
        for nome, padrao, regex in PARAMETROS
    )
    return f"""<featureType>
  <name>{LAYER}</name>
  <nativeName>{LAYER}</nativeName>
  <title>Indicadores AdaptaBrasil</title>
  <abstract>Valor de um indicador por geoobjeto. Parâmetros: indicador, ano e cenario (0 = sem cenário).</abstract>
  <srs>EPSG:4326</srs>
  <projectionPolicy>FORCE_DECLARED</projectionPolicy>
  {_bbox_xml("nativeBoundingBox")}
  {_bbox_xml("latLonBoundingBox")}
  <enabled>true</enabled>
  <metadata>
    <entry key="JDBC_VIRTUAL_TABLE">
      <virtualTable>
        <name>{LAYER}</name>
        <sql>{escape(SQL_VIEW)}</sql>
        <escapeSql>false</escapeSql>
        <keyColumn>geoobject_id</keyColumn>
        <geometry><name>geom</name><type>Geometry</type><srid>4326</srid></geometry>
        {parametros}
      </virtualTable>
    </entry>
  </metadata>
</featureType>"""


def layer_xml(estilos):
    padrao = f"{config.GEOSERVER_PREFIXO_ESTILO}{config.LEGENDA_PADRAO}"
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


def salvar_layer(estilos):
    base = f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes"
    if _existe(f"{base}/{LAYER}.json"):
        # recalculate atualiza os atributos se o SQL mudou
        _enviar("PUT", f"{base}/{LAYER}", featuretype_xml(), "text/xml",
                params={"recalculate": "nativebbox,latlonbbox"})
        print(f"Layer atualizada: {WORKSPACE}:{LAYER}")
    else:
        _enviar("POST", base, featuretype_xml(), "text/xml")
        print(f"Layer criada: {WORKSPACE}:{LAYER}")

    _enviar("PUT", f"layers/{WORKSPACE}:{LAYER}", layer_xml(estilos), "text/xml")
    print(f"Estilos associados à layer: {len(estilos)}")


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

    if args.simular:
        PASTA_SIMULACAO.mkdir(exist_ok=True)
        for nome, conteudo in estilos.items():
            (PASTA_SIMULACAO / f"{nome}.sld").write_text(conteudo, encoding="utf-8")
        (PASTA_SIMULACAO / f"{LAYER}_featuretype.xml").write_text(featuretype_xml(), encoding="utf-8")
        (PASTA_SIMULACAO / f"{LAYER}_layer.xml").write_text(layer_xml(estilos), encoding="utf-8")
        print(f"{len(estilos)} estilos e a layer {LAYER} gravados em {PASTA_SIMULACAO}")
        return

    print(f"GeoServer: {REST} (workspace {WORKSPACE}, datastore {DATASTORE})")
    for nome, conteudo in estilos.items():
        salvar_estilo(nome, conteudo)
    salvar_layer(list(estilos))
    print("GeoServer configurado.")


if __name__ == "__main__":
    main()
