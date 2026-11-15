"""
Gera os estilos SLD do GeoServer a partir da tabela legend_items.

Cada legenda vira um estilo com uma regra por faixa de valor. Como a layer
única mistura polígonos (municípios), linhas (trechos de estrada e ferrovia)
e pontos (portos), cada faixa tem três regras, separadas pela dimensão da
geometria: sem isso o GeoServer pintaria as linhas como polígonos fechados.
"""
from xml.sax.saxutils import escape

# Visual igual ao dos estilos antigos (adaptabrasil_polygon, _line e _point)
CONTORNO = "#232323"

# Linha de divisa entre polígonos: bem fina e cinza claro
DIVISA_COR = "#D9D9D9"
DIVISA_LARGURA = "0.5"
# A divisa só aparece de perto. Na visão do país, com milhares de polígonos
# pequenos, as linhas viram uma mancha cinza. 1:10.000.000 fica entre o
# zoom 5 (Brasil inteiro, ~1:17 mi) e o zoom 6 (um estado, ~1:8,7 mi).
DIVISA_ESCALA_MAXIMA = 10_000_000


def faixas(itens):
    """
    Converte os itens de uma legenda em faixas de filtro.

    itens: lista de dicts com label, color, minvalue e maxvalue.
    Devolve uma lista de dicts com label, color e filtro, em que filtro é:
      ("nulo",)                -> value IS NULL
      ("igual", v)             -> value = v
      ("intervalo", lo, lo_incl, hi, hi_incl), com hi None para sem limite

    As faixas do banco têm buracos (0.0-0.19 e depois 0.2-0.39) e às vezes se
    tocam (0-96 e 96-169). Para não deixar valor sem cor nem pintar um valor
    duas vezes, cada faixa vai do seu mínimo até o mínimo da faixa seguinte
    (exclusive). A última vai até o seu máximo (inclusive). Uma faixa com o
    mesmo mínimo da seguinte (0-0 e depois 0-1) vale só para aquele valor.
    """
    com_valor = sorted(
        (i for i in itens if i["minvalue"] is not None),
        key=lambda i: (i["minvalue"], i["maxvalue"] if i["maxvalue"] is not None else 0),
    )
    resultado = []
    lo_incl = True

    for n, item in enumerate(com_valor):
        lo = item["minvalue"]
        seguinte = com_valor[n + 1] if n + 1 < len(com_valor) else None

        if seguinte is None:
            filtro = ("intervalo", lo, lo_incl, item["maxvalue"], True)
        elif seguinte["minvalue"] == lo:
            filtro = ("igual", lo)
            lo_incl = False  # a faixa seguinte começa logo acima desse valor
            resultado.append({"label": item["label"], "color": item["color"], "filtro": filtro})
            continue
        else:
            filtro = ("intervalo", lo, lo_incl, seguinte["minvalue"], False)

        lo_incl = True
        resultado.append({"label": item["label"], "color": item["color"], "filtro": filtro})

    for item in itens:
        if item["minvalue"] is None:
            resultado.append({"label": item["label"], "color": item["color"], "filtro": ("nulo",)})

    return resultado


def _comparacao(operador, valor):
    return (
        f"<ogc:{operador}><ogc:PropertyName>value</ogc:PropertyName>"
        f"<ogc:Literal>{valor}</ogc:Literal></ogc:{operador}>"
    )


def _filtro_valor(filtro):
    tipo = filtro[0]
    if tipo == "nulo":
        return "<ogc:PropertyIsNull><ogc:PropertyName>value</ogc:PropertyName></ogc:PropertyIsNull>"
    if tipo == "igual":
        return _comparacao("PropertyIsEqualTo", filtro[1])

    _, lo, lo_incl, hi, hi_incl = filtro
    partes = [_comparacao("PropertyIsGreaterThanOrEqualTo" if lo_incl else "PropertyIsGreaterThan", lo)]
    if hi is not None:
        partes.append(_comparacao("PropertyIsLessThanOrEqualTo" if hi_incl else "PropertyIsLessThan", hi))
    if len(partes) == 1:
        return partes[0]
    return "<ogc:And>" + "".join(partes) + "</ogc:And>"


def _filtro_dimensao(dimensao):
    # dimension(geom): 0 = ponto, 1 = linha, 2 = polígono
    return (
        "<ogc:PropertyIsEqualTo>"
        '<ogc:Function name="dimension"><ogc:PropertyName>geom</ogc:PropertyName></ogc:Function>'
        f"<ogc:Literal>{dimensao}</ogc:Literal>"
        "</ogc:PropertyIsEqualTo>"
    )


def _poligono(cor):
    """
    Polígono sem divisa: contorno de 1 px da cor do próprio preenchimento.

    Sem Stroke nenhum, o antialiasing deixa frestas claras entre polígonos
    vizinhos; o contorno da mesma cor cobre as frestas sem desenhar divisa.
    A divisa visível vem de _estilo_divisa, só quando o mapa está aproximado.
    """
    return (
        "<sld:PolygonSymbolizer>"
        f'<sld:Fill><sld:CssParameter name="fill">{cor}</sld:CssParameter></sld:Fill>'
        f'<sld:Stroke><sld:CssParameter name="stroke">{cor}</sld:CssParameter>'
        '<sld:CssParameter name="stroke-width">1</sld:CssParameter></sld:Stroke>'
        "</sld:PolygonSymbolizer>"
    )


def _estilo_divisa(filtrar_poligonos=True):
    """
    FeatureTypeStyle que desenha a divisa fina e clara por cima dos polígonos,
    só abaixo de DIVISA_ESCALA_MAXIMA (mapa aproximado).
    """
    filtro = f"<ogc:Filter>{_filtro_dimensao(2)}</ogc:Filter>" if filtrar_poligonos else ""
    return (
        "<sld:FeatureTypeStyle><sld:Rule><sld:Name>divisa</sld:Name>"
        f"{filtro}"
        f"<sld:MaxScaleDenominator>{DIVISA_ESCALA_MAXIMA}</sld:MaxScaleDenominator>"
        "<sld:LineSymbolizer><sld:Stroke>"
        f'<sld:CssParameter name="stroke">{DIVISA_COR}</sld:CssParameter>'
        f'<sld:CssParameter name="stroke-width">{DIVISA_LARGURA}</sld:CssParameter>'
        "</sld:Stroke></sld:LineSymbolizer></sld:Rule></sld:FeatureTypeStyle>"
    )


def gerar_sld_fundo(nome_estilo, cor="#AAAAAA"):
    """Estilo da layer de fundo: municípios cinza, com divisa só de perto."""
    nome = escape(nome_estilo)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" '
        'xmlns:ogc="http://www.opengis.net/ogc" xmlns:gml="http://www.opengis.net/gml" version="1.0.0">'
        f"<sld:NamedLayer><sld:Name>{nome}</sld:Name><sld:UserStyle>"
        f"<sld:Name>{nome}</sld:Name><sld:FeatureTypeStyle><sld:Rule>"
        f"{_poligono(cor)}"
        "</sld:Rule></sld:FeatureTypeStyle>"
        f"{_estilo_divisa(filtrar_poligonos=False)}"
        "</sld:UserStyle></sld:NamedLayer></sld:StyledLayerDescriptor>"
    )


def _simbolo(dimensao, cor):
    if dimensao == 2:
        return _poligono(cor)
    if dimensao == 1:
        return (
            "<sld:LineSymbolizer><sld:Stroke>"
            f'<sld:CssParameter name="stroke">{cor}</sld:CssParameter>'
            '<sld:CssParameter name="stroke-width">2</sld:CssParameter>'
            '<sld:CssParameter name="stroke-linecap">square</sld:CssParameter>'
            "</sld:Stroke></sld:LineSymbolizer>"
        )
    return (
        "<sld:PointSymbolizer><sld:Graphic><sld:Mark>"
        "<sld:WellKnownName>circle</sld:WellKnownName>"
        f'<sld:Fill><sld:CssParameter name="fill">{cor}</sld:CssParameter></sld:Fill>'
        f'<sld:Stroke><sld:CssParameter name="stroke">{CONTORNO}</sld:CssParameter></sld:Stroke>'
        "</sld:Mark><sld:Size>10</sld:Size></sld:Graphic></sld:PointSymbolizer>"
    )


def gerar_sld(nome_estilo, itens):
    """
    SLD 1.0 completo para uma legenda.

    Três FeatureTypeStyle, desenhados nessa ordem: o preenchimento dos
    polígonos, a divisa entre eles (só de perto) e, por cima de tudo, as
    linhas (estradas, ferrovias) e os pontos (portos).
    """
    def regras(dimensoes):
        resultado = []
        for dimensao in dimensoes:
            for faixa in faixas(itens):
                titulo = escape(faixa["label"])
                resultado.append(
                    "<sld:Rule>"
                    f"<sld:Name>{titulo}</sld:Name><sld:Title>{titulo}</sld:Title>"
                    "<ogc:Filter><ogc:And>"
                    f"{_filtro_dimensao(dimensao)}{_filtro_valor(faixa['filtro'])}"
                    "</ogc:And></ogc:Filter>"
                    f"{_simbolo(dimensao, escape(faixa['color']))}"
                    "</sld:Rule>"
                )
        return "".join(resultado)

    nome = escape(nome_estilo)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" '
        'xmlns:ogc="http://www.opengis.net/ogc" xmlns:gml="http://www.opengis.net/gml" version="1.0.0">'
        f"<sld:NamedLayer><sld:Name>{nome}</sld:Name><sld:UserStyle>"
        f"<sld:Name>{nome}</sld:Name>"
        f"<sld:FeatureTypeStyle>{regras((2,))}</sld:FeatureTypeStyle>"
        f"{_estilo_divisa()}"
        f"<sld:FeatureTypeStyle>{regras((1, 0))}</sld:FeatureTypeStyle>"
        "</sld:UserStyle></sld:NamedLayer></sld:StyledLayerDescriptor>"
    )
