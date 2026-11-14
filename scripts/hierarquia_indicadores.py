import sys
from collections import defaultdict
from pprint import pprint

import psycopg2

import config

# =====================================
# CONFIGURAÇÕES POSTGRES
# =====================================

DB_CONFIG = config.db_config()

# Os botões do primeiro nível da barra lateral têm master = 0
RAIZ = 0

# Garante que os caracteres da árvore (├── └──) saiam no console do Windows
sys.stdout.reconfigure(encoding="utf-8")


# =========================
# FUNÇÕES
# =========================
def buscar_filhos(cur):
    """
    Busca cada botão da barra lateral (detail) com seu respectivo antecessor (master)
    e devolve um dicionário de cada pai com a lista dos seus filhos.
    """
    cur.execute("""
        SELECT
            ii.indicator_id_master,
            ii.indicator_id_detail
        FROM indicator_indicator ii
        ORDER BY
            ii.indicator_id_master,
            ii.indicator_id_detail;
    """)

    filhos = defaultdict(list)
    for master, detail in cur.fetchall():
        filhos[master].append(detail)

    return filhos


def buscar_nomes(cur):
    """
    Devolve um dicionário id -> shortname de todos os indicadores.
    """
    cur.execute("SELECT id, shortname FROM indicator;")
    return dict(cur.fetchall())


def percorrer(filhos, master, resultado, visitados):
    """
    Percorre a árvore a partir de master, adicionando em resultado cada
    tupla (master, detail), com cada filho logo depois do seu pai.
    Ignora indicadores já visitados, para não entrar em laço infinito
    se a tabela tiver um ciclo (A -> B -> A).
    """
    for detail in filhos[master]:
        if detail in visitados:
            print(f"Aviso: ciclo ou repetição em {master} -> {detail}, ignorado")
            continue

        visitados.add(detail)
        resultado.append((master, detail))
        percorrer(filhos, detail, resultado, visitados)


def rotulo(no, nomes):
    """
    Texto exibido para um indicador: id seguido do shortname.
    """
    return f"{no} - {nomes.get(no, '(sem nome)')}"


def imprimir_arvore(no, filhos, nomes, prefixo="", eh_ultimo=True, eh_raiz=False):

    if eh_raiz:
        print(rotulo(no, nomes))
    else:
        conector = "└── " if eh_ultimo else "├── "
        print(prefixo + conector + rotulo(no, nomes))

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
            filhos,
            nomes,
            novo_prefixo,
            ultimo_filho,
            False
        )


# =========================
# CONEXÃO
# =========================
with psycopg2.connect(**DB_CONFIG) as conn:

    with conn.cursor() as cur:
        filhos_banco = buscar_filhos(cur)
        nomes = buscar_nomes(cur)

# Lista de tuplas (master, detail) na ordem da árvore
resultado = []
percorrer(filhos_banco, RAIZ, resultado, set())

pprint(resultado)

# Monta a relação master -> filhos só com o que foi alcançado a partir da raiz
filhos = defaultdict(list)
for master, detail in resultado:
    filhos[master].append(detail)

# Cada nó com master = 0 é a raiz de uma árvore
for raiz in filhos[RAIZ]:
    imprimir_arvore(
        raiz,
        filhos,
        nomes,
        eh_raiz=True
    )

print(len(resultado))
