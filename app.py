import os
from collections import defaultdict
from functools import lru_cache

import psycopg2
from flask import Flask, render_template, request, abort, jsonify
from flask_cors import CORS

from scripts import config

app = Flask(__name__)
CORS(app)

SCHEMA = config.DB_SCHEMA

# URL do WMS do GeoServer, disponível em todos os templates
GEOSERVER_WMS_URL = config.geoserver_wms_url()

# Layer de fundo (municípios em cinza), também usada nas páginas sem indicador
LAYER_PADRAO = f"{config.geoserver_workspace()}:{config.GEOSERVER_LAYER_FUNDO}"

# Indicadores da home: título exibido na página e indicador raiz da árvore
# (filho de master = 0 em indicator_indicator)
INDICADORES = {
    "recursos_hidricos": {"titulo": "Recursos Hídricos", "raiz": 1},
    "seguranca_alimentar": {"titulo": "Segurança Alimentar", "raiz": 5000},
    "seguranca_energetica": {"titulo": "Segurança Energética", "raiz": 10000},
    "infraestrutura_portuaria": {"titulo": "Infraestrutura Portuária", "raiz": 40000},
    "saude": {"titulo": "Saúde", "raiz": 50000},
    "desastres_hidrologicos": {"titulo": "Desastres Hidrológicos", "raiz": 60000},
    "infraestrutura_ferroviaria": {"titulo": "Infraestrutura Ferroviária", "raiz": 80000},
    "infraestrutura_rodoviaria": {"titulo": "Infraestrutura Rodoviária", "raiz": 70000},
}


@app.context_processor
def geoserver():
    return {"geoserver_wms_url": GEOSERVER_WMS_URL}


def conectar():
    return psycopg2.connect(**config.db_config())


# =====================================
# CONSULTAS
# =====================================

@lru_cache(maxsize=1)
def carregar_indicadores():
    """
    Lê uma vez os indicadores e a hierarquia da materialized view mv_hierarchy.

    Ela traz um registro por indicador, com o pai (indicator_id_master), e só
    inclui os temas (sep) visíveis. Os dados mudam raramente; depois de um
    REFRESH MATERIALIZED VIEW mv_hierarchy, reinicie o app para recarregar.
    """
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT id, shortname, title, legend_id, level, indicator_id_master,
                   years, geometrytype
            FROM {SCHEMA}.mv_hierarchy
            ORDER BY indicator_id_master, id
        """)
        indicadores = {}
        filhos = defaultdict(list)
        for id_, shortname, title, legend_id, level, master, years, geometria in cur.fetchall():
            indicadores[id_] = {
                "id": id_, "nome": shortname, "titulo": title,
                "legenda": legend_id or config.LEGENDA_PADRAO,
                "nivel": level, "anos": years or [], "geometria": geometria,
            }
            if master is not None:
                filhos[master].append(id_)

    return indicadores, filhos


def montar_arvore(raiz):
    """Árvore aninhada a partir de raiz; ignora ciclos e repetições."""
    indicadores, filhos = carregar_indicadores()
    visitados = set()

    def no(id_):
        visitados.add(id_)
        dados = indicadores.get(id_, {"id": id_, "nome": "(sem nome)", "titulo": "",
                                      "legenda": config.LEGENDA_PADRAO})
        return {**dados, "filhos": [no(f) for f in filhos[id_] if f not in visitados]}

    return no(raiz)


@lru_cache(maxsize=1)
def carregar_legendas():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT legend_id, label, color, minvalue, maxvalue
            FROM {SCHEMA}.legend_items
            ORDER BY legend_id, "order"
        """)
        legendas = defaultdict(list)
        for legend_id, label, color, minvalue, maxvalue in cur.fetchall():
            legendas[legend_id].append(
                {"rotulo": label, "cor": color, "min": minvalue, "max": maxvalue}
            )
    return legendas


def buscar_opcoes(indicador_id):
    """Combinações de ano e cenário que têm dados para o indicador."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT DISTINCT v.year, COALESCE(v.scenario_id, 0), s.name
            FROM {SCHEMA}.value v
            LEFT JOIN {SCHEMA}.scenario s ON s.scenario_id = v.scenario_id
            WHERE v.indicator_id = %s
            ORDER BY 1, 2
        """, (indicador_id,))
        return [
            {"ano": ano, "cenario": cenario, "nome_cenario": nome or "Presente"}
            for ano, cenario, nome in cur.fetchall()
        ]


# =====================================
# PÁGINAS
# =====================================

@app.route('/')
def homepage():
    return render_template("home.html", map_layer=LAYER_PADRAO)

@app.route('/mapa')
def mapa():
    indicador = request.args.get("indicador", "recursos_hidricos")
    dados = INDICADORES.get(indicador)
    if dados is None:
        abort(404)
    mapa_config = {
        "wmsUrl": GEOSERVER_WMS_URL,
        "layer": f"{config.geoserver_workspace()}:{config.GEOSERVER_LAYER}",
        "layerFundo": LAYER_PADRAO,
        "prefixoEstilo": config.GEOSERVER_PREFIXO_ESTILO,
        "raiz": dados["raiz"],
    }
    return render_template("mapa.html", titulo=dados["titulo"], mapa_config=mapa_config)

@app.route('/teste')
def teste():
    return render_template("teste.html", map_layer=LAYER_PADRAO)

@app.route('/rascunho')
def rascunho():
    return render_template('rascunho.html')

@app.route('/basemapa')
def basemapa():
    return render_template('basemapa.html', map_layer=LAYER_PADRAO)


# =====================================
# API
# =====================================

@app.route('/api/arvore/<int:raiz>')
def api_arvore(raiz):
    indicadores, _ = carregar_indicadores()
    if raiz not in indicadores:
        abort(404)
    return jsonify(montar_arvore(raiz))

@app.route('/api/indicadores/<int:indicador_id>')
def api_indicador(indicador_id):
    indicadores, _ = carregar_indicadores()
    dados = indicadores.get(indicador_id)
    if dados is None:
        abort(404)
    return jsonify({
        **dados,
        "opcoes": buscar_opcoes(indicador_id),
        "itens_legenda": carregar_legendas().get(dados["legenda"], []),
    })


if __name__ == '__main__':
    # FLASK_DEBUG=1 liga o recarregamento automático e a página de erro detalhada.
    # Em debug o app só escuta em localhost: o depurador do Werkzeug executa
    # código Python e não pode ficar exposto na rede.
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    app.run(host='127.0.0.1' if debug else '0.0.0.0', port=5000, debug=debug)
