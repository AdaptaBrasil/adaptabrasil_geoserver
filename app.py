from flask import Flask, render_template, request, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Layer padrão enquanto o indicador não tem uma layer própria no GeoServer
LAYER_PADRAO = "adaptabrasil:mapa_cinza"

# Indicadores da home: título exibido na página e layer do GeoServer
INDICADORES = {
    "recursos_hidricos": {"titulo": "Recursos Hídricos", "layer": LAYER_PADRAO},
    "seguranca_alimentar": {"titulo": "Segurança Alimentar", "layer": LAYER_PADRAO},
    "seguranca_energetica": {"titulo": "Segurança Energética", "layer": LAYER_PADRAO},
    "infraestrutura_portuaria": {"titulo": "Infraestrutura Portuária", "layer": LAYER_PADRAO},
    "saude": {"titulo": "Saúde", "layer": LAYER_PADRAO},
    "desastres_hidrologicos": {"titulo": "Desastres Hidrológicos", "layer": LAYER_PADRAO},
    "infraestrutura_ferroviaria": {"titulo": "Infraestrutura Ferroviária", "layer": LAYER_PADRAO},
    "infraestrutura_rodoviaria": {"titulo": "Infraestrutura Rodoviária", "layer": LAYER_PADRAO},
}

@app.route('/')
def homepage():
    return render_template("home.html", map_layer=LAYER_PADRAO)

@app.route('/mapa')
def mapa():
    indicador = request.args.get("indicador", "recursos_hidricos")
    dados = INDICADORES.get(indicador)
    if dados is None:
        abort(404)
    return render_template("mapa.html", map_layer=dados["layer"],
                           titulo=dados["titulo"])

@app.route('/teste')
def teste():
    return render_template("teste.html", map_layer=LAYER_PADRAO)

@app.route('/rascunho')
def rascunho():
    return render_template('rascunho.html')

@app.route('/basemapa')
def basemapa():
    return render_template('basemapa.html', map_layer=LAYER_PADRAO)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
