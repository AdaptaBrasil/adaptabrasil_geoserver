import psycopg2
import requests
from requests.auth import HTTPBasicAuth

import config

# =====================================
# CONFIGURAÇÕES POSTGRES
# =====================================

DB_CONFIG = config.db_config()

SCHEMA = config.DB_SCHEMA

# =====================================
# CONFIGURAÇÕES GEOSERVER
# =====================================

GEOSERVER = config.geoserver_config()

GEOSERVER_URL = GEOSERVER["url"]

GEOSERVER_USER = GEOSERVER["user"]
GEOSERVER_PASSWORD = GEOSERVER["password"]

WORKSPACE = GEOSERVER["workspace"]
DATASTORE = GEOSERVER["datastore"]

# =====================================
# MAPEAMENTO DE ESTILOS
# =====================================

STYLE_MAP = {
    "ST_Point": "adaptabrasil_point",
    "ST_MultiPoint": "adaptabrasil_point",
    "ST_LineString": "adaptabrasil_line",
    "ST_MultiLineString": "adaptabrasil_line",
    "ST_Polygon": "adaptabrasil_polygon",
    "ST_MultiPolygon": "adaptabrasil_polygon"
}

# =====================================
# FUNÇÕES
# =====================================

def layer_exists(layer_name):
    """
    Verifica se a layer já existe no GeoServer.
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
    Publica uma view do PostGIS como layer no GeoServer.
    """

    url = (
        f"{GEOSERVER_URL}/rest/workspaces/"
        f"{WORKSPACE}/datastores/"
        f"{DATASTORE}/featuretypes"
    )

    payload = {
        "featureType": {
            "name": layer_name,
            "nativeName": layer_name,
            'attributes': {'attribute': [{'binding': 'java.lang.String',
                                           'maxOccurs': 1,
                                           'minOccurs': 0,
                                           'name': 'name',
                                           'nillable': True},
                                          {'binding': 'org.locationtech.jts.geom.Geometry',
                                           'maxOccurs': 1,
                                           'minOccurs': 0,
                                           'name': 'geom',
                                           'nillable': True},
                                          {'binding': 'java.lang.Double',
                                           'maxOccurs': 1,
                                           'minOccurs': 0,
                                           'name': 'value',
                                           'nillable': True},
                                          {'binding': 'java.lang.String',
                                           'maxOccurs': 1,
                                           'minOccurs': 0,
                                           'name': 'CLASSE',
                                           'nillable': True}]},
            'latLonBoundingBox': {'crs': 'EPSG:4326',
                                  'maxx': -28.835907628999966,
                                  'maxy': 5.271841077172965,
                                  'minx': -73.99044996899995,
                                  'miny': -33.751177994239676},
            'nativeBoundingBox': {'crs': 'EPSG:4326',
                                  'maxx': -28.835907628999966,
                                  'maxy': 5.271841077172965,
                                  'minx': -73.99044996899995,
                                  'miny': -33.751177994239676},
            'srs': 'EPSG:4326',
            'internationalAbstract': '',
            'internationalTitle': '',
            'metadata': {'entry': {'$': 'false',
                                   '@key': 'cachingEnabled'}},
            'nativeCRS': 'GEOGCS["WGS 84", \r\n'
                         '  DATUM["World Geodetic System 1984", \r\n'
                         '    SPHEROID["WGS 84", 6378137.0, '
                         '298.257223563, AUTHORITY["EPSG","7030"]], \r\n'
                         '    AUTHORITY["EPSG","6326"]], \r\n'
                         '  PRIMEM["Greenwich", 0.0, '
                         'AUTHORITY["EPSG","8901"]], \r\n'
                         '  UNIT["degree", 0.017453292519943295], \r\n'
                         '  AXIS["Geodetic longitude", EAST], \r\n'
                         '  AXIS["Geodetic latitude", NORTH], \r\n'
                         '  AUTHORITY["EPSG","4326"]]',
            'simpleConversionEnabled': False,


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
        f"Publicação de {layer_name}: "
        f"{response.status_code}"
    )

    # O GeoServer responde 201 (Created) quando a publicação dá certo
    if response.status_code != 201:
        print(f"Falha ao publicar {layer_name}: {response.text}")
        return False

    return True


def apply_style(layer_name, style_name):
    """
    Aplica o estilo padrão à layer.
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
# BUSCA AS VIEWS NO BANCO
# =====================================

with psycopg2.connect(**DB_CONFIG) as conn:

    with conn.cursor() as cur:

        cur.execute(f"""
            SELECT
                view_name,
                type_geom
            FROM {SCHEMA}.views_adaptabrasil
            where published = FALSE
        """)

        layers = cur.fetchall()

# =====================================
# PUBLICAÇÃO DAS LAYERS
# =====================================

for layer_name, type_geom in layers:

    style_name = STYLE_MAP.get(type_geom)
    #layer_name = layer_name.lower() #as tabelas no postgres são sempre criadas com minusculo

    if not style_name:

        print(
            f"Geometria não mapeada: "
            f"{type_geom}"
        )
        continue

    try:

        if not layer_exists(layer_name):

            if not publish_layer(layer_name):
                # Continua com published = FALSE para tentar de novo na próxima execução
                continue

        # Marca como publicada: acabou de ser publicada ou já existia no GeoServer
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                tupla = (layer_name,)

                cur.execute(f"""
                            UPDATE {SCHEMA}.views_adaptabrasil
                            SET published = TRUE
                            WHERE view_name = %s;
                            """, tupla)


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