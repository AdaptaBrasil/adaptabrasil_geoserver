import re
import unicodedata
import psycopg2


# =========================
# FUNÇÃO PARA NORMALIZAR TEXTO
# =========================
def normalizar_nome(texto: str) -> str:
    """
    Remove acentos, espaços e caracteres especiais
    para gerar nomes válidos de views no PostgreSQL.
    """

    # Remove acentos
    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ASCII", "ignore").decode("ASCII")

    # Minúsculo
    texto = texto.lower()

    # Substitui espaços por _
    texto = texto.replace(" ", "_")

    # Remove caracteres especiais
    texto = re.sub(r"[^a-z0-9_]", "", texto)

    # Remove múltiplos _
    texto = re.sub(r"_+", "_", texto)

    # Remove _ do início/fim
    texto = texto.strip("_")

    return texto


# =========================
# CONFIGURAÇÃO DO BANCO
# =========================
DB_CONFIG = {
    "host": "localhost",
    "database": "adaptabrasil",
    "user": "adaptabrasil",
    "password": "",
    "port": "5432"
}


# =========================
# CONEXÃO
# =========================
with psycopg2.connect(**DB_CONFIG) as conn:

    with conn.cursor() as cur:

        # Busca combinações + shortname
        cur.execute("""
            SELECT DISTINCT
                v.indicator_id,
                v.scenario_id,
                v.year,
                i.shortname
            FROM value v
            JOIN indicator i
                ON v.indicator_id = i.id
            ORDER BY
                v.indicator_id,
                v.scenario_id,
                v.year;
        """)

        combinacoes = cur.fetchall()

        for indicator_id, scenario_id, year, shortname in combinacoes:

            # Normaliza o shortname
            shortname_limpo = normalizar_nome(shortname)

            # Nome da view
            view_name = (
               # f"vw_{shortname_limpo}"
                f"vw_scn_{scenario_id}"
                f"_yr_{year}"
                f"_id_{indicator_id}"
            )

            sql = f"""
            CREATE VIEW {view_name} AS
            SELECT
                g.name,
                g.geom,
                v.value,
                CASE
                    WHEN v.value IS NULL THEN 'Dado indisponível'
                    WHEN v.value >= 0.00 AND v.value <= 0.19 THEN 'Muito baixo'
                    WHEN v.value >= 0.20 AND v.value <= 0.39 THEN 'Baixo'
                    WHEN v.value >= 0.40 AND v.value <= 0.59 THEN 'Medio'
                    WHEN v.value >= 0.60 AND v.value <= 0.79 THEN 'Alto'
                    WHEN v.value >= 0.80 AND v.value <= 1.00 THEN 'Muito alto'
                    ELSE 'Fora do intervalo'
                END AS "CLASSE"
            FROM value v
            JOIN geoobject g
                ON v.geoobject_id = g.id
            WHERE
                v.indicator_id = {indicator_id}
                AND v.year = {year}
            """
            if scenario_id is not None:
              sql = sql + f""" and v.scenario_id = {scenario_id}"""
            sql = sql + ";"

            #sql = f"drop view if exists {view_name}"

            print(f"Criando view: {view_name}")
            cur.execute(sql)

print("Todas as views foram criadas com sucesso.")

#ta dando erro pq tem alguns q sao nulos e temos q ver se esses tbm sao mapas e como contornar isso