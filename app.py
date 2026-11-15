import os
import re
import sys
import threading
import unicodedata
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache

from psycopg2.pool import ThreadedConnectionPool
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

# Setores estratégicos: os filhos de master = 0 na mv_hierarchy (ver carregar_setores).
# Aqui ficam só o endereço (/mapa?indicador=...) e o ícone local dos setores que já
# tinham um; um setor novo no banco ganha um endereço derivado do nome e usa a
# imagem da tabela image.
SETORES_LOCAIS = {
    1: "recursos_hidricos",
    5000: "seguranca_alimentar",
    10000: "seguranca_energetica",
    40000: "infraestrutura_portuaria",
    50000: "saude",
    60000: "desastres_hidrologicos",
    70000: "infraestrutura_rodoviaria",
    80000: "infraestrutura_ferroviaria",
    90000: "biodiversidade",
    100000: "agricultura_familiar",
    110000: "setor_censitario",  # raiz virtual, ver _incluir_setores_fora_da_mv
}


@app.context_processor
def geoserver():
    return {"geoserver_wms_url": GEOSERVER_WMS_URL}


_pool = None
_pool_trava = threading.Lock()


@contextmanager
def conectar():
    """
    Conexão de um pool, para usar com `with conectar() as conn`.

    O banco é remoto e abrir uma conexão leva ~1 s; o pool reaproveita as
    abertas. Ao sair do with, a transação é confirmada (ou desfeita, se houve
    erro) e a conexão volta ao pool; se ela caiu, é descartada.
    """
    global _pool
    with _pool_trava:
        if _pool is None:
            _pool = ThreadedConnectionPool(1, 8, **config.db_config())
    conn = _pool.getconn()
    try:
        with conn:
            yield conn
    finally:
        _pool.putconn(conn, close=bool(conn.closed))


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
                   years, geometrytype, imageurl, sep_order_by
            FROM {SCHEMA}.mv_hierarchy
            ORDER BY indicator_id_master, id
        """)
        indicadores = {}
        filhos = defaultdict(list)
        for (id_, shortname, title, legend_id, level, master, years, geometria,
             imagem, ordem) in cur.fetchall():
            indicadores[id_] = {
                "id": id_, "nome": shortname, "titulo": title,
                "legenda": legend_id or config.LEGENDA_PADRAO,
                "nivel": level, "anos": years or [], "geometria": geometria,
                "imagem": imagem, "ordem": ordem,
            }
            if master is not None:
                filhos[master].append(id_)

        _incluir_setores_fora_da_mv(cur, indicadores, filhos)

    return indicadores, filhos


def _incluir_setores_fora_da_mv(cur, indicadores, filhos):
    """
    Acrescenta os indicadores que a mv_hierarchy deixa de fora, para que todos
    os setores do banco apareçam no app:

      - os de setores com sep.visible = false (Agricultura Familiar), que têm
        hierarquia completa em indicator_indicator;
      - os sem pai em indicator_indicator (Setor Censitário), que ficam
        pendurados numa raiz virtual com o nome do setor (sep.name).

    A raiz virtual usa o primeiro múltiplo de 10000 abaixo do menor id do
    setor (110000 para os indicadores 110021 a 110064), como as raízes reais.
    """
    cur.execute(f"""
        SELECT i.id, i.shortname, i.title, i.legend_id, i.level, ii.indicator_id_master,
               got.geometrytype, img.imageurl, s.order_by, s.name
        FROM {SCHEMA}.indicator i
        JOIN {SCHEMA}.sep s ON s.id = i.sep_id
        LEFT JOIN {SCHEMA}.indicator_indicator ii ON ii.indicator_id_detail = i.id
        LEFT JOIN {SCHEMA}.geoobjecttype got ON got.id = i.geoobjecttype_id
        LEFT JOIN {SCHEMA}.image img ON img.indicator_id = i.id
        WHERE i.id NOT IN (SELECT id FROM {SCHEMA}.mv_hierarchy)
        ORDER BY s.order_by, ii.indicator_id_master NULLS FIRST, i.id
    """)
    orfaos = defaultdict(list)  # (ordem, nome do setor) -> ids sem pai
    for (id_, shortname, title, legend_id, level, master, geometria,
         imagem, ordem, setor) in cur.fetchall():
        if id_ in indicadores:
            continue
        indicadores[id_] = {
            "id": id_, "nome": shortname, "titulo": title,
            "legenda": legend_id or config.LEGENDA_PADRAO,
            "nivel": level, "anos": [], "geometria": geometria,
            "imagem": imagem, "ordem": ordem,
        }
        if master is not None:
            filhos[master].append(id_)
        elif level != 1:
            orfaos[(ordem, setor)].append(id_)

    for (ordem, setor), ids in orfaos.items():
        raiz = min(ids) // 10000 * 10000
        if raiz in indicadores:
            raise RuntimeError(f"Raiz virtual {raiz} do setor {setor} já é um indicador")
        indicadores[raiz] = {
            "id": raiz, "nome": setor, "titulo": setor, "legenda": config.LEGENDA_PADRAO,
            "nivel": 1, "anos": [], "geometria": None, "imagem": None, "ordem": ordem,
        }
        filhos[0].append(raiz)
        filhos[raiz].extend(ids)


def _slug(texto):
    """'Desastres geo-hidrológicos' -> 'desastres_geo_hidrologicos'."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


@lru_cache(maxsize=1)
def carregar_setores():
    """
    Setores estratégicos da home, na ordem do sistema oficial (sep.order_by).

    São as raízes das árvores de indicadores: os filhos de master = 0, tanto
    os da mv_hierarchy quanto os que ela deixa de fora (sep.visible = false
    e indicadores sem pai).
    Devolve {slug: setor}, em que setor tem raiz, titulo e ícone.
    """
    indicadores, filhos = carregar_indicadores()
    raizes = sorted((indicadores[i] for i in filhos[0] if i in indicadores),
                    key=lambda d: (d["ordem"] is None, d["ordem"], d["id"]))
    setores = {}
    for dados in raizes:
        local = SETORES_LOCAIS.get(dados["id"])
        slug = local or _slug(dados["nome"]) or str(dados["id"])
        setores[slug] = {
            "raiz": dados["id"], "titulo": dados["nome"],
            # Arquivo em static/ ou, para setor sem ícone local, a URL da tabela image
            "icone_local": f"img/{local}.png" if local else None,
            "icone_url": dados["imagem"],
        }
    return setores


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


@lru_cache(maxsize=1)
def carregar_estados():
    """Estados da view state, em ordem alfabética."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, name, state FROM {SCHEMA}.state ORDER BY name")
        return [{"id": id_, "nome": nome, "sigla": sigla} for id_, nome, sigla in cur.fetchall()]


@lru_cache(maxsize=32)
def carregar_municipios(estado_id):
    """Municípios do estado, da view county, em ordem alfabética."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, name FROM {SCHEMA}.county WHERE state_id = %s ORDER BY name",
                    (estado_id,))
        return [{"id": id_, "nome": nome} for id_, nome in cur.fetchall()]


@lru_cache(maxsize=256)
def buscar_limites(estado_id, municipio_id):
    """[oeste, sul, leste, norte] do município ou do estado, em EPSG:4326."""
    if municipio_id:
        sql, param = f"SELECT ST_Extent(geom) FROM {SCHEMA}.county WHERE id = %s", municipio_id
    else:
        sql, param = f"SELECT ST_Extent(geom) FROM {SCHEMA}.state WHERE id = %s", estado_id
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM ({sql}) t(e)", (param,))
        limites = cur.fetchone()
    return None if limites[0] is None else list(limites)


@lru_cache(maxsize=4096)
def buscar_rotulo_geoobjeto(geoobjeto_id):
    """
    Rótulos do popup do hover. A sigla do estado vai na linha da cidade: num
    município, o próprio nome ("Igaratá/SP"); num setor censitário, o
    município a que ele pertence ("Alexandria/RN"), com o código do setor no
    título. O GeoServer só devolve nome e valor.
    """
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT CASE WHEN c.id IS NOT NULL AND c.id <> g.id THEN g.name::text
                        WHEN g.state IS NULL THEN g.name::text
                        ELSE concat(g.name, '/', g.state) END,
                   CASE WHEN c.id IS NULL OR c.id = g.id THEN NULL
                        WHEN c.state IS NULL THEN c.name::text
                        ELSE concat(c.name, '/', c.state) END
            FROM {SCHEMA}.geoobject g
            LEFT JOIN {SCHEMA}.geoobject c ON c.id = g.county_id
            WHERE g.id = %s
        """, (geoobjeto_id,))
        linha = cur.fetchone()
    if linha is None:
        return None
    return {"nome": linha[0], "municipio": linha[1]}


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
    return render_template("home.html", map_layer=LAYER_PADRAO, setores=carregar_setores())

@app.route('/mapa')
def mapa():
    setores = carregar_setores()
    indicador = request.args.get("indicador") or next(iter(setores), None)
    dados = setores.get(indicador)
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

@app.route('/api/estados')
def api_estados():
    return jsonify(carregar_estados())

@app.route('/api/estados/<int:estado_id>/municipios')
def api_municipios(estado_id):
    return jsonify(carregar_municipios(estado_id))

@app.route('/api/limites')
def api_limites():
    estado = request.args.get("estado", 0, type=int)
    municipio = request.args.get("municipio", 0, type=int)
    limites = buscar_limites(estado, municipio) if estado or municipio else None
    if limites is None:
        abort(404)
    return jsonify(limites)

@app.route('/api/geoobjetos/<int:geoobjeto_id>')
def api_geoobjeto(geoobjeto_id):
    rotulo = buscar_rotulo_geoobjeto(geoobjeto_id)
    if rotulo is None:
        abort(404)
    return jsonify(rotulo)

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
    # Sob o depurador do PyCharm (pydevd) o recarregamento fica desligado: para
    # reiniciar, o Werkzeug encerra o processo com sys.exit(3), e o depurador
    # para nesse SystemExit como se fosse um erro.
    sob_depurador = "pydevd" in sys.modules
    app.run(host='127.0.0.1' if debug else '0.0.0.0', port=5000, debug=debug,
            use_reloader=debug and not sob_depurador)
