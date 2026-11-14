"""
Remove o que sobrou do modelo antigo (uma view e uma layer por combinação
de indicador, cenário e ano), substituído pela layer parametrizada criada
pelo configurar_geoserver.py.

Remove:
  - no GeoServer: as layers vw_st_* do datastore e os estilos
    adaptabrasil_point, adaptabrasil_line e adaptabrasil_polygon;
  - no banco: as views vw_st_* do schema e a tabela views_adaptabrasil.

Antes de apagar, grava um backup em backup_legado/<data e hora>/ na raiz do
projeto: o SQL para recriar as views e a tabela, e o XML das layers e dos
estilos no GeoServer.

Rode o configurar_geoserver.py antes: o script se recusa a continuar se
alguma layer que fica (como o mapa_cinza) ainda depender de uma view vw_st_*.

Uso:
    python scripts/limpar_legado.py --simular  # só lista e grava o backup
    python scripts/limpar_legado.py            # grava o backup e apaga
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2 import sql as psql
import requests
from requests.auth import HTTPBasicAuth

import config

GEOSERVER = config.geoserver_config()
REST = GEOSERVER["url"].rstrip("/") + "/rest"
AUTH = HTTPBasicAuth(GEOSERVER["user"], GEOSERVER["password"])
WORKSPACE = GEOSERVER["workspace"]
DATASTORE = GEOSERVER["datastore"]
SCHEMA = config.DB_SCHEMA

PADRAO_LEGADO = re.compile(r"^vw_st_[a-z]+_scn_[0-9a-z]+_yr_\d+_id_\d+$")
ESTILOS_LEGADO = ["adaptabrasil_point", "adaptabrasil_line", "adaptabrasil_polygon"]
TABELA_CONTROLE = "views_adaptabrasil"

PASTA_BACKUP = Path(__file__).resolve().parent.parent / "backup_legado"

sys.stdout.reconfigure(encoding="utf-8")


def _get(caminho, **params):
    resposta = requests.get(f"{REST}/{caminho}", auth=AUTH, params=params, timeout=60)
    resposta.raise_for_status()
    return resposta


def _delete(caminho, **params):
    resposta = requests.delete(f"{REST}/{caminho}", auth=AUTH, params=params, timeout=120)
    if resposta.status_code not in (200, 404):
        raise RuntimeError(f"DELETE {caminho}: {resposta.status_code} {resposta.text[:300]}")


# =====================================
# INVENTÁRIO
# =====================================

def featuretypes_geoserver():
    dados = _get(f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes.json").json()
    lista = dados.get("featureTypes") or {}
    return [f["name"] for f in lista.get("featureType", [])]


def estilos_geoserver():
    dados = _get(f"workspaces/{WORKSPACE}/styles.json").json()
    lista = dados.get("styles") or {}
    return [s["name"] for s in lista.get("style", [])]


def views_banco(cur):
    cur.execute(
        "SELECT table_name FROM information_schema.views WHERE table_schema = %s",
        (SCHEMA,),
    )
    return sorted(r[0] for r in cur.fetchall() if PADRAO_LEGADO.match(r[0]))


def verificar_dependencias(featuretypes):
    """Layers que ficam não podem ler uma view que vai ser apagada."""
    problemas = []
    for nome in featuretypes:
        if PADRAO_LEGADO.match(nome):
            continue
        ft = _get(f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes/{nome}.json").json()
        nativo = ft["featureType"].get("nativeName", "")
        if PADRAO_LEGADO.match(nativo):
            problemas.append(f"{nome} (lê {nativo})")
    return problemas


# =====================================
# BACKUP
# =====================================

def gravar_backup(pasta, cur, views, layers, estilos):
    pasta.mkdir(parents=True)

    with open(pasta / "views.sql", "w", encoding="utf-8") as f:
        f.write(f"-- {len(views)} views de {SCHEMA}, removidas por limpar_legado.py\n")
        for v in views:
            cur.execute("SELECT pg_get_viewdef(%s::regclass, true)",
                        (f'"{SCHEMA}"."{v}"',))
            f.write(f'CREATE OR REPLACE VIEW "{SCHEMA}"."{v}" AS\n{cur.fetchone()[0]}\n\n')

    cur.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.{TABELA_CONTROLE}",))
    if cur.fetchone()[0] is not None:
        cur.execute(psql.SQL("SELECT view_name, type_geom, published FROM {}.{} ORDER BY 1").format(
            psql.Identifier(SCHEMA), psql.Identifier(TABELA_CONTROLE)))
        linhas = cur.fetchall()
        with open(pasta / f"{TABELA_CONTROLE}.sql", "w", encoding="utf-8") as f:
            f.write(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.{TABELA_CONTROLE}(\n"
                    "    view_name TEXT PRIMARY KEY,\n    type_geom TEXT,\n"
                    "    published BOOLEAN DEFAULT FALSE\n);\n")
            for nome, tipo, publicada in linhas:
                f.write(cur.mogrify(
                    f"INSERT INTO {SCHEMA}.{TABELA_CONTROLE} VALUES (%s, %s, %s);\n",
                    (nome, tipo, publicada)).decode("utf-8"))

    pasta_gs = pasta / "geoserver"
    pasta_gs.mkdir()
    for n, nome in enumerate(layers, 1):
        ft = _get(f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes/{nome}.xml").text
        layer = _get(f"layers/{WORKSPACE}:{nome}.xml").text
        (pasta_gs / f"{nome}.featuretype.xml").write_text(ft, encoding="utf-8")
        (pasta_gs / f"{nome}.layer.xml").write_text(layer, encoding="utf-8")
        if n % 100 == 0:
            print(f"  backup das layers: {n}/{len(layers)}")
    for nome in estilos:
        conteudo = _get(f"workspaces/{WORKSPACE}/styles/{nome}.sld").text
        (pasta_gs / f"{nome}.sld").write_text(conteudo, encoding="utf-8")


# =====================================
# PRINCIPAL
# =====================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--simular", action="store_true", help="só lista e grava o backup, não apaga nada")
    args = parser.parse_args()

    featuretypes = featuretypes_geoserver()
    layers = sorted(f for f in featuretypes if PADRAO_LEGADO.match(f))
    estilos = [e for e in ESTILOS_LEGADO if e in estilos_geoserver()]

    problemas = verificar_dependencias(featuretypes)
    if problemas:
        sys.exit("Layers que ficam ainda dependem de views antigas; rode o configurar_geoserver.py antes:\n  "
                 + "\n  ".join(problemas))

    with psycopg2.connect(**config.db_config()) as conn:
        with conn.cursor() as cur:
            views = views_banco(cur)

            print(f"GeoServer: {len(layers)} layers vw_st_* e {len(estilos)} estilos ({', '.join(estilos) or '-'})")
            print(f"Banco ({SCHEMA}): {len(views)} views vw_st_* e a tabela {TABELA_CONTROLE}")

            pasta = PASTA_BACKUP / datetime.now().strftime("%Y%m%d_%H%M%S")
            print(f"Gravando backup em {pasta}")
            gravar_backup(pasta, cur, views, layers, estilos)

            if args.simular:
                print("Simulação: nada foi apagado.")
                return

            # GeoServer primeiro: uma layer sem a view no banco daria erro ao ser lida
            for n, nome in enumerate(layers, 1):
                _delete(f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes/{nome}", recurse="true")
                if n % 100 == 0:
                    print(f"  layers removidas: {n}/{len(layers)}")
            print(f"Layers removidas do GeoServer: {len(layers)}")

            for nome in estilos:
                _delete(f"workspaces/{WORKSPACE}/styles/{nome}", purge="true")
            print(f"Estilos removidos do GeoServer: {len(estilos)}")

            # Banco: tudo numa transação (o with conn faz commit no fim, ou rollback se der erro)
            for v in views:
                cur.execute(psql.SQL("DROP VIEW {}.{}").format(psql.Identifier(SCHEMA), psql.Identifier(v)))
            cur.execute(psql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                psql.Identifier(SCHEMA), psql.Identifier(TABELA_CONTROLE)))
    print(f"Views removidas do banco: {len(views)}; tabela {TABELA_CONTROLE} removida.")
    print("Limpeza concluída.")


if __name__ == "__main__":
    main()
