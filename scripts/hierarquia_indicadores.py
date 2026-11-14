import psycopg2

# =====================================
# CONFIGURAÇÕES POSTGRES
# =====================================

DB_CONFIG = {
    "host": "3.224.52.81",
    "database": "adaptabrasil",
    "user": "adaptabrasil_user",
    "password": "142857",
    "port": "6543",
    "options": "-c search_path=adaptabrasil_aluana,public",
}


# =========================
# CONEXÃO
# =========================
with psycopg2.connect(**DB_CONFIG) as conn:

    with conn.cursor() as cur:

        # Busca cada botão da barra lateral (detail) com seu respectivo antecessor (master)
        cur.execute("""
            SELECT
                ii.indicator_id_master,
                ii.indicator_id_detail
            FROM indicator_indicator ii;
        """)
        #Lista de tuplas do select acima
        combinacoes = cur.fetchall()

        #Cria um dicionário de cada pais com seus respectivos filhos
        from collections import defaultdict

        filhos = defaultdict(list)

        for master, detail in combinacoes:
            filhos[master].append((master, detail))

        resultado = []


        #definição da função percorrer, que ordena cada filho seguido do seu pai, para depois adicionar na variavel resultado, que é uma lista de tuplas
        def percorrer(master, nivel) :
            nivel+= 1
            for tupla in filhos[master]:
                resultado.append(tupla)

                detail = tupla[1]
                percorrer(detail, nivel)

        #executa a função percorrer
        percorrer(0)

        from pprint import pprint
        pprint(resultado)




        from collections import defaultdict

        # Cria a relação master -> filhos
        filhos = defaultdict(list)

        # Usa DIRETAMENTE a lista resultado
        for master, detail in resultado:
            filhos[master].append(detail)


        def imprimir_arvore(no, prefixo="", eh_ultimo=True, eh_raiz=False):

            if eh_raiz:
                print(no)
            else:
                conector = "└── " if eh_ultimo else "├── "
                print(prefixo + conector + str(no))

            filhos_do_no = filhos[no]

            for i, filho in enumerate(filhos_do_no):
                ultimo_filho = i == len(filhos_do_no) - 1

                if eh_raiz:
                    novo_prefixo = ""
                else:
                    novo_prefixo = prefixo + (
                        "    " if eh_ultimo else "│   "
                    )

                imprimir_arvore(
                    filho,
                    novo_prefixo,
                    ultimo_filho,
                    False
                )


        # Encontra os nós que têm master = 0
        raizes = filhos[0]

        for raiz in raizes:
            imprimir_arvore(
                raiz,
                eh_raiz=True
            )


        print (len(resultado))



