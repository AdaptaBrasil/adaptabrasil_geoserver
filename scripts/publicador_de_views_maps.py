import psycopg2
import requests
from requests.auth import HTTPBasicAuth

# =====================================
# CONFIGURAÇÕES POSTGRES
# =====================================

DB_CONFIG = {
    "host": "localhost",
    "database": "adaptabrasil",
    "user": "adaptabrasil",
    "password": "",
    "port": "5432"
}

# =====================================
# CONFIGURAÇÕES GEOSERVER
# =====================================

GEOSERVER_URL = "http://localhost:8080/geoserver"

GEOSERVER_USER = "admin"
GEOSERVER_PASSWORD = "geoserver"

WORKSPACE = "adaptabrasil"
DATASTORE = "adaptabrasil"

# =====================================
# MAPEAMENTO DE ESTILOS
# =====================================

STYLE_MAP = {
    "ST_Point": "adaptabrasil_point",
    "ST_MultiLineString": "adaptabrasil_line",
    "ST_MultiPolygon": "adaptabrasil_polygon"
}

# =====================================
# FUNÇÕES
# =====================================

def layer_exists(layer_name):
    """
    Verifica se a layer já existe.
    """

    url = (
        f"{GEOSERVER_URL}/rest/layers/"
        f"{WORKSPACE}:{layer_name}.json"
    )

    response = requests.get(
        url,
        auth=HTTPBasicAuth(
            GEOSERVER_USER,
            GEOSERVER_PASSWORD
        )
    )

    return response.status_code == 200


def publish_layer(layer_name):
    """
    Publica uma view do PostGIS.
    """

    url = (
        f"{GEOSERVER_URL}/rest/workspaces/"
        f"{WORKSPACE}/datastores/"
        f"{DATASTORE}/featuretypes"
    )

    payload = {
        "featureType": {
            "name": layer_name,
            "nativeName": layer_name
        }
    }

    response = requests.post(
        url,
        json=payload,
        auth=HTTPBasicAuth(
            GEOSERVER_USER,
            GEOSERVER_PASSWORD
        ),
        headers={
            "Content-Type": "application/json"
        }
    )

    print(
        f"Publicação {layer_name}: "
        f"{response.status_code}"
    )


def apply_style(layer_name, style_name):
    """
    Define o estilo padrão da layer.
    """

    url = (
        f"{GEOSERVER_URL}/rest/layers/"
        f"{WORKSPACE}:{layer_name}"
    )

    payload = {
        "layer": {
            "defaultStyle": {
                "name": style_name
            }
        }
    }

    response = requests.put(
        url,
        json=payload,
        auth=HTTPBasicAuth(
            GEOSERVER_USER,
            GEOSERVER_PASSWORD
        ),
        headers={
            "Content-Type": "application/json"
        }
    )

    print(
        f"Style {style_name} aplicado em "
        f"{layer_name}: {response.status_code}"
    )


# =====================================
# PROCESSAMENTO
# =====================================

with psycopg2.connect(**DB_CONFIG) as conn:

    with conn.cursor() as cur:

        # ALTERE PARA SUA TABELA
        cur.execute("""
            SELECT
                view_name,
                geom_type
            FROM layer_metadata
        """)

        layers = cur.fetchall()

for layer_name, geom_type in layers:

    style_name = STYLE_MAP.get(geom_type)

    if not style_name:

        print(
            f"Geometria não mapeada: "
            f"{geom_type}"
        )
        continue

    try:

        if not layer_exists(layer_name):

            publish_layer(layer_name)

        apply_style(
            layer_name,
            style_name
        )

    except Exception as e:

        print(
            f"Erro em {layer_name}: {e}"
        )

print("Processamento concluído.")

#substutyir os nome, filtrar so pelos nao publicados e atualizar a tabela quando publicar