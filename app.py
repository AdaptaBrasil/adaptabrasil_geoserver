from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/')
def homepage():
    return render_template("home.html", map_layer=
        "adaptabrasil:BR_UF_2024")

@app.route('/mapa')
def mapa():
    return render_template("mapa.html", map_layer=
    "adaptabrasil:BR_UF_2024")

@app.route('/teste')
def teste():
    return render_template("teste.html", map_layer=
    "adaptabrasil:BR_UF_2024")

@app.route('/rascunho')
def rascunho():
    return render_template('rascunho.html')

if __name__ == '__main__':
    app.run()

@app.route('/basemapa')
def rascunho():
    return render_template('basemapa.html')

if __name__ == '__main__':
    app.run()