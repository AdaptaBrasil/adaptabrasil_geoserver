"""
Configurações do banco e do GeoServer, lidas de variáveis de ambiente.

Os valores vêm do arquivo .env na raiz do projeto (que não vai para o Git)
ou de variáveis de ambiente já definidas no sistema, que têm prioridade.
Os nomes têm o prefixo ADAPTABRASIL_ para não colidir com variáveis
de outros projetos (como DB_HOST).
Para criar o .env, copie o .env.example e preencha os valores.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# .env na raiz do projeto, independente da pasta de onde o script é executado
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _obrigatoria(nome):
    valor = os.getenv(nome)
    if valor is None:
        raise RuntimeError(
            f"Variável de ambiente {nome} não definida. "
            f"Copie o .env.example para .env e preencha os valores."
        )
    return valor


# =====================================
# POSTGRES
# =====================================
DB_SCHEMA = os.getenv("ADAPTABRASIL_DB_SCHEMA", "adaptabrasil_aluana")


def db_config():
    """Parâmetros de conexão para psycopg2.connect(**db_config())."""
    return {
        "host": _obrigatoria("ADAPTABRASIL_DB_HOST"),
        "database": os.getenv("ADAPTABRASIL_DB_NAME", "adaptabrasil"),
        "user": _obrigatoria("ADAPTABRASIL_DB_USER"),
        "password": _obrigatoria("ADAPTABRASIL_DB_PASSWORD"),
        "port": os.getenv("ADAPTABRASIL_DB_PORT", "5432"),
        "options": f"-c search_path={DB_SCHEMA},public",
    }


# =====================================
# GEOSERVER
# =====================================
def geoserver_config():
    """URL, credenciais, workspace e datastore do GeoServer."""
    return {
        "url": _obrigatoria("ADAPTABRASIL_GEOSERVER_URL"),
        "user": _obrigatoria("ADAPTABRASIL_GEOSERVER_USER"),
        "password": _obrigatoria("ADAPTABRASIL_GEOSERVER_PASSWORD"),
        "workspace": geoserver_workspace(),
        "datastore": os.getenv("ADAPTABRASIL_GEOSERVER_DATASTORE", "adaptabrasil"),
    }


# Layer única do GeoServer: uma SQL view parametrizada por indicador, ano e cenário
GEOSERVER_LAYER = os.getenv("ADAPTABRASIL_GEOSERVER_LAYER", "indicador")

# Layer de fundo (municípios em cinza), também uma SQL view, e o estilo dela
GEOSERVER_LAYER_FUNDO = "mapa_cinza"
GEOSERVER_ESTILO_FUNDO = "mapa_cinza"

# Prefixo dos estilos gerados a partir da tabela legend_items (um por legenda)
GEOSERVER_PREFIXO_ESTILO = "adaptabrasil_legenda_"

# Legenda usada quando o indicador não tem legend_id
LEGENDA_PADRAO = int(os.getenv("ADAPTABRASIL_LEGENDA_PADRAO", "2"))


def geoserver_wms_url():
    """
    URL do WMS que o navegador usa para buscar os mapas.

    É a URL pública do GeoServer, diferente da ADAPTABRASIL_GEOSERVER_URL,
    que o publicador usa de dentro do servidor (localhost). Não exige as
    credenciais, porque o app Flask só precisa da URL.
    """
    url = _obrigatoria("ADAPTABRASIL_GEOSERVER_PUBLIC_URL").rstrip("/")
    return f"{url}/{geoserver_workspace()}/wms"


def geoserver_workspace():
    return os.getenv("ADAPTABRASIL_GEOSERVER_WORKSPACE", "adaptabrasil")
