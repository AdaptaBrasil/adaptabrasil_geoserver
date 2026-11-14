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


def _simbolo(dimensao, cor):
    if dimensao == 2:
        return (
            "<sld:PolygonSymbolizer>"
            f'<sld:Fill><sld:CssParameter name="fill">{cor}</sld:CssParameter></sld:Fill>'
            f'<sld:Stroke><sld:CssParameter name="stroke">{CONTORNO}</sld:CssParameter>'
            '<sld:CssParameter name="stroke-width">0</sld:CssParameter></sld:Stroke>'
            "</sld:PolygonSymbolizer>"
        )
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
    """SLD 1.0 completo para uma legenda."""
    regras = []
    # Polígonos primeiro, para que linhas e pontos fiquem por cima
    for dimensao in (2, 1, 0):
        for faixa in faixas(itens):
            titulo = escape(faixa["label"])
            regras.append(
                "<sld:Rule>"
                f"<sld:Name>{titulo}</sld:Name><sld:Title>{titulo}</sld:Title>"
                "<ogc:Filter><ogc:And>"
                f"{_filtro_dimensao(dimensao)}{_filtro_valor(faixa['filtro'])}"
                "</ogc:And></ogc:Filter>"
                f"{_simbolo(dimensao, escape(faixa['color']))}"
                "</sld:Rule>"
            )

    nome = escape(nome_estilo)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" '
        'xmlns:ogc="http://www.opengis.net/ogc" xmlns:gml="http://www.opengis.net/gml" version="1.0.0">'
        f"<sld:NamedLayer><sld:Name>{nome}</sld:Name><sld:UserStyle>"
        f"<sld:Name>{nome}</sld:Name><sld:FeatureTypeStyle>"
        + "".join(regras)
        + "</sld:FeatureTypeStyle></sld:UserStyle></sld:NamedLayer></sld:StyledLayerDescriptor>"
    )
